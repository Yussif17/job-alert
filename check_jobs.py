#!/usr/bin/env python3
"""
New-grad software engineering job monitor.

Pulls the machine-readable listings feed maintained by the SimplifyJobs
New-Grad-Positions repo, filters it down to active Software roles that
look relevant, diffs against a "seen" cache committed to this repo, and
emails you the list of any brand-new postings.

Env vars required (set as GitHub Actions secrets):
  SMTP_HOST      - SMTP server host (e.g. smtp.gmail.com)
  SMTP_USERNAME  - SMTP login username
  SMTP_PASSWORD  - SMTP login password (for Gmail, an App Password)
  EMAIL_TO       - address to send alerts to

Optional env vars:
  SMTP_PORT        - SMTP port (default 587, STARTTLS)
  EMAIL_FROM       - From address (defaults to SMTP_USERNAME)
  KEYWORDS         - comma-separated keywords to require in the title
                      (case-insensitive OR match). Leave unset to match
                      all active Software category postings.
  EXCLUDE_KEYWORDS - comma-separated keywords to exclude (e.g. "Senior,Staff")
  COMPANIES        - comma-separated company names to allow, replacing the
                      built-in TOP_COMPANIES list. Set to "*" to allow every
                      company.
"""

import json
import os
import re
import smtplib
import sys
import urllib.request
from email.mime.text import MIMEText

LISTINGS_URL = "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json"
SEEN_FILE = os.path.join(os.path.dirname(__file__), "seen.json")

DEFAULT_KEYWORDS = [
    "software engineer",
    "software developer",
    "swe",
    "backend",
    "full stack",
    "full-stack",
]
DEFAULT_EXCLUDE = [
    "senior",
    "staff",
    "principal",
    "manager",
    "sr.",
    "sr ",
]

# Companies whose new-grad SWE offers are generally considered better than
# Capital One / Roblox (comp, prestige, or both). Roblox and Capital One
# themselves are deliberately left out. Names are matched after normalize().
TOP_COMPANIES = [
    # Quant / HFT
    "jane street", "citadel", "citadel securities", "hudson river trading",
    "jump trading", "two sigma", "d e shaw", "de shaw", "tower research capital",
    "five rings capital", "five rings", "imc trading", "imc", "optiver",
    "susquehanna", "sig", "drw", "akuna capital", "headlands tech holdings",
    "the voleon group", "voleon", "radix trading", "xtx markets", "old mission",
    "millennium", "cubist", "point72", "bridgewater", "chicago trading company",
    "virtu financial",
    # AI labs / top AI startups
    "openai", "anthropic", "xai", "google deepmind", "deepmind", "scale ai",
    "anysphere", "cursor", "perplexity", "mistral", "cohere", "character ai",
    "harvey", "sierra", "decagon", "elevenlabs", "applied intuition",
    "databricks", "glean", "cerebras", "fireworks ai", "physical intelligence",
    # Big tech
    "google", "meta", "apple", "microsoft", "amazon", "nvidia", "netflix",
    "bytedance", "tiktok", "linkedin",
    # Top-paying public tech / late-stage
    "stripe", "palantir", "uber", "lyft", "airbnb", "doordash", "instacart",
    "pinterest", "snap", "snowflake", "coinbase", "robinhood", "figma", "ramp",
    "plaid", "brex", "notion", "rippling", "anduril", "affirm", "dropbox",
    "reddit", "discord", "datadog", "confluent", "verkada", "whatnot",
    "waymo", "nuro", "duolingo", "benchling",
]

US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO",
    "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA",
    "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "PR",
}
US_STATE_NAMES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
    "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
    "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west virginia", "wisconsin", "wyoming", "washington dc",
}
# Shorthand the feed uses for US locations.
US_ALIASES = {
    "united states", "usa", "us", "remote in usa", "remote in us", "remote",
    "sf", "south sf", "nyc", "la",
}

_SUFFIXES = re.compile(r"\b(inc|llc|ltd|corp|corporation|co|university|holdings? inc)$")


def normalize(name):
    name = re.sub(r"[^a-z0-9 ]", " ", name.lower())
    name = re.sub(r"\s+", " ", name).strip()
    return _SUFFIXES.sub("", name).strip()


def is_us_location(location):
    location = location.strip()
    if location.lower() in US_STATE_NAMES or location.lower() in US_ALIASES:
        return True
    parts = [p.strip() for p in location.split(",")]
    return len(parts) >= 2 and parts[-1] in US_STATE_CODES


def is_us_job(job):
    # Postings with no location listed are kept rather than silently dropped.
    locations = job.get("locations") or []
    return not locations or any(is_us_location(l) for l in locations)


def load_companies():
    raw = os.environ.get("COMPANIES", "")
    if raw.strip() == "*":
        return None
    names = [c for c in raw.split(",") if c.strip()] or TOP_COMPANIES
    return {normalize(c) for c in names}


def load_keywords(env_var, default):
    raw = os.environ.get(env_var, "")
    if not raw.strip():
        return default
    return [k.strip().lower() for k in raw.split(",") if k.strip()]


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen(seen_ids):
    with open(SEEN_FILE, "w") as f:
        json.dump(sorted(seen_ids), f, indent=2)


def fetch_listings():
    req = urllib.request.Request(LISTINGS_URL, headers={"User-Agent": "newgrad-job-monitor"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def matches(job, keywords, exclude_keywords, companies):
    if not is_us_job(job):
        return False
    if companies is not None and normalize(job.get("company_name", "")) not in companies:
        return False
    title = job.get("title", "").lower()
    if any(x in title for x in exclude_keywords):
        return False
    if not keywords:
        return True
    return any(k in title for k in keywords)


def format_job(job):
    locations = ", ".join(job.get("locations", [])) or "Location not listed"
    sponsorship = job.get("sponsorship", "Unknown")
    return (
        f"{job.get('company_name', 'Unknown Company')} — {job.get('title', 'Untitled role')}\n"
        f"{locations} · Sponsorship: {sponsorship}\n"
        f"{job.get('url', '')}"
    )


def send_email(smtp_host, smtp_port, username, password, from_addr, to_addr, jobs):
    body = "\n\n".join(format_job(job) for job in jobs)
    msg = MIMEText(body)
    msg["Subject"] = f"New-Grad Job Alert: {len(jobs)} new posting{'s' if len(jobs) != 1 else ''}"
    msg["From"] = from_addr
    msg["To"] = to_addr

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(username, password)
        smtp.sendmail(from_addr, [to_addr], msg.as_string())


def main():
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_username = os.environ.get("SMTP_USERNAME")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    email_to = os.environ.get("EMAIL_TO")
    if not all([smtp_host, smtp_username, smtp_password, email_to]):
        print("ERROR: SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, and EMAIL_TO must all be set.", file=sys.stderr)
        sys.exit(1)

    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    email_from = os.environ.get("EMAIL_FROM", smtp_username)

    keywords = load_keywords("KEYWORDS", DEFAULT_KEYWORDS)
    exclude_keywords = load_keywords("EXCLUDE_KEYWORDS", DEFAULT_EXCLUDE)
    companies = load_companies()

    listings = fetch_listings()
    seen = load_seen()

    active_software = [
        j for j in listings
        if j.get("active") and j.get("category") == "Software" and j.get("is_visible", True)
    ]

    new_matches = [
        j for j in active_software
        if j["id"] not in seen and matches(j, keywords, exclude_keywords, companies)
    ]

    # Always mark ALL currently-active software postings as seen, not just
    # matches, so changing your keyword filter later doesn't cause a flood
    # of "new" notifications for postings that were already active before.
    for j in active_software:
        seen.add(j["id"])

    # Oldest-first so the email reads chronologically.
    new_matches.sort(key=lambda j: j.get("date_posted", 0))

    print(f"Fetched {len(listings)} total listings, {len(active_software)} active software roles, "
          f"{len(new_matches)} new matches.")

    if new_matches:
        try:
            send_email(smtp_host, smtp_port, smtp_username, smtp_password, email_from, email_to, new_matches)
            print(f"Emailed {len(new_matches)} new posting(s) to {email_to}.")
        except Exception as e:
            print(f"Failed to send email: {e}", file=sys.stderr)

    save_seen(seen)


if __name__ == "__main__":
    main()

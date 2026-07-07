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
"""

import json
import os
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


def matches(job, keywords, exclude_keywords):
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

    listings = fetch_listings()
    seen = load_seen()

    active_software = [
        j for j in listings
        if j.get("active") and j.get("category") == "Software" and j.get("is_visible", True)
    ]

    new_matches = [
        j for j in active_software
        if j["id"] not in seen and matches(j, keywords, exclude_keywords)
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

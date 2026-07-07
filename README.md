# New-Grad SWE Job Monitor

Checks the [SimplifyJobs New-Grad-Positions](https://github.com/SimplifyJobs/New-Grad-Positions)
feed every hour and emails you the list of new active software-engineering postings.
Already-seen postings are tracked in `seen.json` so you only get notified once per job.

## Setup (10 minutes, one time)

### 1. Get SMTP credentials

Any SMTP provider works. For Gmail:

- Enable 2-Step Verification on the sending account, then create an
  [App Password](https://myaccount.google.com/apppasswords) — use that as `SMTP_PASSWORD`,
  not your normal login password.
- `SMTP_HOST` is `smtp.gmail.com`, `SMTP_USERNAME` is the full Gmail address.

### 2. Push this repo to GitHub

You've already got the local repo cloned at `Developer/job-alert`. Commit these files and push
to the remote (`git add . && git commit -m "initial commit" && git push`).

### 3. Add secrets

In your GitHub repo: **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.
Add each of these:

- `SMTP_HOST` — e.g. `smtp.gmail.com`
- `SMTP_USERNAME` — your SMTP login (e.g. full email address)
- `SMTP_PASSWORD` — your SMTP password / app password
- `EMAIL_TO` — the address you want alerts sent to

### 4. Turn it on

- Go to the **Actions** tab of your repo. If prompted, click "I understand my workflows, enable them."
- Click into "Check New-Grad SWE Jobs" → **Run workflow** to trigger a first run manually and
  confirm you get the email.
- After that it runs automatically every hour on its own — no server, no laptop needed to be on.
  You'll only actually receive an email on runs where there's at least one new matching posting.

## Customizing what gets posted

Open `.github/workflows/check-jobs.yml` and uncomment/edit these lines under `env:`:

```yaml
KEYWORDS: "software engineer,swe,backend"
EXCLUDE_KEYWORDS: "senior,staff,principal"
```

`KEYWORDS` is an OR match against the job title (case-insensitive) — a title matching any one
keyword passes. `EXCLUDE_KEYWORDS` filters out titles containing any of those words regardless
of keyword match. Defaults are already set in `check_jobs.py` to reasonable new-grad terms.

## Notes

- `seen.json` starts pre-seeded with all currently-active postings, so your first real run
  only surfaces genuinely new postings going forward — not a backlog dump of 700+ jobs.
- The workflow commits the updated `seen.json` back to the repo after each run, so state
  persists between runs.
- This only covers the SimplifyJobs feed. It's the most actively maintained new-grad list, but
  it's not exhaustive — worth still checking specific companies directly for ones you especially want.

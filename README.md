# LeetCode Daily

The LeetCode daily challenge, saved every day into [`problems/`](problems/), using the
[noworneverev/leetcode-api](https://github.com/noworneverev/leetcode-api) hosted API.

```
problems/
  2026-11-06_2747-count-zero-request-servers/
    README.md       statement, tags, hints (collapsed)
    solution.py     starter code
    problem.json    raw API data
```

## How it runs

A GitHub Actions workflow ([`.github/workflows/daily.yml`](.github/workflows/daily.yml))
downloads the day's problem and commits it at a random time between 8:00 AM and noon
Eastern. It checks in hourly. [`random_time.py`](.github/scripts/random_time.py) picks
the day's time, and only that run commits. If GitHub skips a check, the next one
catches up.

To fetch a problem right away, open the **Actions** tab, choose **Daily LeetCode**,
then **Run workflow**. The workflow skips the official editorial (`--no-editorial`),
because it's LeetCode's own content.

## Running it locally

Only needs Python 3.9 or newer, with no packages to install.

```powershell
python daily.py                     # python3 starter code, plus editorial.md
python daily.py --lang python3,cpp  # several languages (any LeetCode langSlug)
python daily.py --force             # re-download today; never overwrites solution files
```

`install-schedule.ps1` registers a Windows scheduled task that does the same thing on
this PC. Don't use it alongside the GitHub workflow: both would add the same folder,
and `git pull` would conflict.

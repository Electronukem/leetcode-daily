#!/usr/bin/env python3
"""Download today's LeetCode daily challenge.

Data comes from https://github.com/noworneverev/leetcode-api (hosted at
https://leetcode-api-pied.vercel.app). Standard library only.

Each new challenge goes into problems/<date>_<id>-<slug>/:
    README.md        problem statement, tags and collapsed hints
    solution.<ext>   starter code for each requested language
    editorial.md     official write-up, when the API has one (unless --no-editorial)
    problem.json     raw API responses

If today's challenge is already downloaded the script exits without touching
the network, so running it more than once a day is harmless.

Usage:
    python daily.py                      # python3 starter code
    python daily.py --lang python3,cpp   # several languages
    python daily.py --force              # refresh today's files (keeps your solutions)
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

API = "https://leetcode-api-pied.vercel.app"
ROOT = Path(__file__).resolve().parent
DEFAULT_OUT = ROOT / "problems"
LOG_FILE = ROOT / "daily.log"
# The scheduled run happens once a day, so be patient with a flaky connection
# (e.g. Wi-Fi still reconnecting after wake): waits 10s, 40s, then 160s.
RETRIES = 4

log = logging.getLogger("daily")

# langSlug -> (file extension, line-comment prefix)
LANGS = {
    "python3": ("py", "#"), "python": ("py", "#"), "pythondata": ("py", "#"),
    "cpp": ("cpp", "//"), "c": ("c", "//"), "java": ("java", "//"),
    "csharp": ("cs", "//"), "javascript": ("js", "//"), "typescript": ("ts", "//"),
    "golang": ("go", "//"), "kotlin": ("kt", "//"), "swift": ("swift", "//"),
    "rust": ("rs", "//"), "scala": ("scala", "//"), "dart": ("dart", "//"),
    "php": ("php", "//"), "ruby": ("rb", "#"), "elixir": ("ex", "#"),
    "erlang": ("erl", "%"), "racket": ("rkt", ";"), "bash": ("sh", "#"),
    "mysql": ("sql", "--"), "mssql": ("sql", "--"), "oraclesql": ("sql", "--"),
    "postgresql": ("sql", "--"),
}
# LeetCode's judge imports these implicitly; add them so the file runs locally.
PREAMBLE = {
    "python3": "from typing import *\n\n",
    "pythondata": "import pandas as pd\n\n",
}


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def fetch_json(path: str) -> dict:
    url = API + path
    req = urllib.request.Request(url, headers={
        "User-Agent": "leetcode-daily-downloader/1.0",
        "Accept": "application/json",
    })
    delay = 10
    for attempt in range(1, RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except (OSError, ValueError) as e:  # network errors, timeouts, bad JSON
            if attempt == RETRIES:
                raise RuntimeError(f"GET {url} failed after {RETRIES} tries: {e}") from e
            log.warning("GET %s failed (%s); retrying in %ss", url, e, delay)
            time.sleep(delay)
            delay *= 4
    raise AssertionError("unreachable")


# --------------------------------------------------------------------------- #
# HTML -> Markdown (just enough for LeetCode problem statements)
# --------------------------------------------------------------------------- #
class _HtmlToMarkdown(HTMLParser):
    INLINE = {"strong": "**", "b": "**", "em": "*", "i": "*"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.pre: list[str] | None = None  # buffer while inside <pre>
        self.code = 0                       # depth of inline <code>
        self.lists: list[list] = []         # stack of [tag, item_count]
        self.href: str | None = None

    def _close_marker(self, marker: str) -> None:
        # "<strong>0-indexed </strong>x" must become "**0-indexed** x", not "**0-indexed **x".
        last = self.out[-1] if self.out else ""
        stripped = last.rstrip()
        self.out[-1:] = [stripped, marker, last[len(stripped):]] if self.out else [marker]

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "pre":
            self.pre = []
        elif self.pre is not None:
            self.pre.append({"br": "\n", "sup": "^"}.get(tag, ""))
        elif tag == "img":
            img = f"![{a.get('alt') or ''}]({a.get('src') or ''})"
            self.out.append(img if self.lists else f"\n\n{img}\n\n")
        elif tag == "sup":
            self.out.append("^")
        elif tag == "sub":
            self.out.append("_")
        elif tag == "br":
            self.out.append("\\\n")
        elif tag == "code":
            if self.code == 0:
                self.out.append("`")
            self.code += 1
        elif self.code:
            return  # no markdown formatting inside inline code
        elif tag in self.INLINE:
            self.out.append(self.INLINE[tag])
        elif tag in ("p", "div"):
            if not self.lists:
                self.out.append("\n\n")
        elif tag in ("ul", "ol"):
            self.lists.append([tag, 0])
            self.out.append("\n")
        elif tag == "li":
            kind = self.lists[-1] if self.lists else ["ul", 0]
            kind[1] += 1
            indent = "   " * max(len(self.lists) - 1, 0)
            bullet = f"{kind[1]}." if kind[0] == "ol" else "-"
            self.out.append(f"\n{indent}{bullet} ")
        elif tag == "a":
            self.href = a.get("href")
            self.out.append("[")

    def handle_endtag(self, tag):
        if tag == "pre" and self.pre is not None:
            body = "".join(self.pre).replace("\xa0", " ").strip("\n").rstrip()
            self.out.append(f"\n\n```\n{body}\n```\n\n")
            self.pre = None
        elif self.pre is not None:
            return
        elif tag == "code" and self.code:
            self.code -= 1
            if self.code == 0:
                self._close_marker("`")
        elif self.code:
            return
        elif tag in self.INLINE:
            self._close_marker(self.INLINE[tag])
        elif tag in ("ul", "ol") and self.lists:
            self.lists.pop()
            self.out.append("\n\n")
        elif tag == "a":
            self.out.append(f"]({self.href or ''})")
            self.href = None

    def handle_data(self, data):
        if self.pre is not None:
            self.pre.append(data)
            return
        data = re.sub(r"\s+", " ", data.replace("\xa0", " "))
        if self.code == 0:
            data = re.sub(r"([\\`*_<])", r"\\\1", data)  # keep literal text literal
        if data.strip() or not (self.out and self.out[-1].endswith(("\n", " "))):
            self.out.append(data)

    def markdown(self) -> str:
        text = "".join(self.out)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n[ \t]+(?=[^\s\-\d]|$)", "\n", text)  # stray indents, but not list nesting
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def html_to_md(html: str) -> str:
    parser = _HtmlToMarkdown()
    parser.feed(html or "")
    parser.close()
    return parser.markdown()


# --------------------------------------------------------------------------- #
# Building the files
# --------------------------------------------------------------------------- #
def build_readme(daily: dict, detail: dict, url: str) -> str:
    q = daily["question"]
    tags = ", ".join(t["name"] for t in q.get("topicTags") or [])
    meta = [q.get("difficulty") and f"**{q['difficulty']}**"]
    if q.get("acRate") is not None:
        meta.append(f"{q['acRate']:.1f}% acceptance")
    meta.append(tags)

    content = q.get("content") or detail.get("content")
    body = html_to_md(content) if content else (
        "_Description unavailable (this may be a Premium problem). "
        f"See [LeetCode]({url})._"
    )

    parts = [
        f"# {q['questionFrontendId']}. {q['title']}",
        " · ".join(m for m in meta if m),
        f"Daily challenge for **{daily['date']}** · [Open on LeetCode]({url})",
        "---",
        body,
    ]
    hints = detail.get("hints") or []
    if hints:
        parts.append("## Hints")
        parts += [
            f"<details>\n<summary>Hint {i}</summary>\n\n{html_to_md(h)}\n\n</details>"
            for i, h in enumerate(hints, 1)
        ]
    return "\n\n".join(parts) + "\n"


def build_editorial(detail: dict, title: str) -> str | None:
    sol = detail.get("solution") or {}
    content = sol.get("content")
    if not content or not sol.get("canSeeDetail", True):
        return None
    content = re.sub(r"^\s*\[TOC\]\s*$", "", content, flags=re.M)
    # Code tabs are LeetCode playground iframes; they don't render locally.
    content = re.sub(
        r'<iframe[^>]*src="([^"]+)"[^>]*>\s*</iframe>',
        r"[View solution code on LeetCode](\1)",
        content,
    )
    return f"# Editorial: {title}\n\n> **Spoilers**: this is the official LeetCode solution.\n\n{content.strip()}\n"


def build_solutions(detail: dict, langs: list[str], title: str, url: str) -> dict[str, str]:
    snippets = {s["langSlug"]: s["code"] for s in detail.get("codeSnippets") or []}
    files: dict[str, str] = {}
    for lang in langs:
        if lang not in snippets:
            log.warning("No %s starter code for this problem (available: %s)",
                        lang, ", ".join(snippets) or "none")
            continue
        ext, comment = LANGS.get(lang, ("txt", "#"))
        name = f"solution.{ext}"
        if name in files:  # e.g. python + python3
            name = f"solution_{lang}.{ext}"
        code = snippets[lang].rstrip()
        last = code.rsplit("\n", 1)[-1]
        if ext == "py" and last.endswith(":"):  # empty body isn't valid Python
            code += "\n" + " " * (len(last) - len(last.lstrip()) + 4) + "pass"
        header = f"{comment} {title}\n{comment} {url}\n\n"
        files[name] = header + PREAMBLE.get(lang, "") + code + "\n"
    return files


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def existing_for(out: Path, date: str) -> Path | None:
    return next((p for p in out.glob(f"{date}_*") if p.is_dir()), None)


def write_new(folder: Path, files: dict[str, str]) -> None:
    """Write into a temp dir and rename, so a failed run never leaves a half folder."""
    tmp = Path(tempfile.mkdtemp(prefix=".tmp-", dir=folder.parent))
    for name, text in files.items():
        (tmp / name).write_text(text, encoding="utf-8", newline="\n")
    tmp.rename(folder)


def run(langs: list[str], out: Path, force: bool, editorial: bool = True) -> int:
    out.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).date().isoformat()  # LeetCode rolls over at 00:00 UTC
    if not force and (have := existing_for(out, today)):
        log.debug("Already have %s (%s); nothing to do.", today, have.name)
        print(f"Already downloaded: {have}")
        return 0

    daily = fetch_json("/daily")
    date, q = daily.get("date", ""), daily.get("question") or {}
    slug, qid = q.get("titleSlug", ""), q.get("questionFrontendId", "")
    # These end up in a path, so don't trust them blindly.
    if not (re.fullmatch(r"\d{4}-\d{2}-\d{2}", date)
            and re.fullmatch(r"[a-z0-9-]+", slug)
            and re.fullmatch(r"\d+", qid)):
        raise RuntimeError(f"Unexpected /daily response: {json.dumps(daily)[:300]}")

    if not force and (have := existing_for(out, date)):
        print(f"Already downloaded: {have} (API is still serving {date})")
        return 0

    try:
        detail = fetch_json(f"/problem/{urllib.parse.quote(slug)}")
    except RuntimeError as e:
        log.warning("Couldn't fetch problem details, saving the basics only: %s", e)
        detail = {}

    title = f"{qid}. {q.get('title', slug)}"
    url = f"https://leetcode.com/problems/{slug}/"
    files = {"README.md": build_readme(daily, detail, url)}
    files.update(build_solutions(detail, langs, title, url))
    if not editorial:
        detail.pop("solution", None)  # also keep it out of problem.json
    elif text := build_editorial(detail, title):
        files["editorial.md"] = text
    files["problem.json"] = json.dumps({"daily": daily, "detail": detail},
                                       indent=2, ensure_ascii=False) + "\n"

    folder = out / f"{date}_{qid}-{slug}"
    if folder.exists():  # only reachable with --force
        for name, text in files.items():
            path = folder / name
            if name.startswith("solution") and path.exists():
                continue  # never clobber the user's work
            path.write_text(text, encoding="utf-8", newline="\n")
        log.info("Refreshed %s", folder.name)
    else:
        write_new(folder, files)
        log.info("Downloaded %s [%s] -> %s", title, q.get("difficulty"), folder)
    print(folder)
    return 0


def setup_logging() -> None:
    log.setLevel(logging.DEBUG)
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.INFO)  # keep "already downloaded" runs out of the log file
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(fh)
    if sys.stderr:  # None under pythonw.exe (the scheduled task)
        sh = logging.StreamHandler()
        sh.setLevel(logging.WARNING)
        sh.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        log.addHandler(sh)


def main() -> int:
    ap = argparse.ArgumentParser(description="Download today's LeetCode daily challenge.")
    ap.add_argument("--lang", default="python3",
                    help="comma-separated langSlugs for starter code, e.g. python3,cpp,java "
                         f"(known: {', '.join(LANGS)})")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output folder (default: %(default)s)")
    ap.add_argument("--force", action="store_true",
                    help="re-download today's challenge; existing solution files are kept")
    ap.add_argument("--no-editorial", action="store_true",
                    help="skip LeetCode's official solution write-up (used for the public repo)")
    args = ap.parse_args()

    setup_logging()
    langs = [l.strip() for l in args.lang.split(",") if l.strip()]
    try:
        return run(langs, args.out.resolve(), args.force, editorial=not args.no_editorial)
    except Exception as e:  # noqa: BLE001 - last-resort logging for unattended runs
        log.error("%s", e, exc_info=not isinstance(e, RuntimeError))
        return 1


if __name__ == "__main__":
    sys.exit(main())

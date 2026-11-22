#!/usr/bin/env python3
"""
Preview the profile README locally, before you commit and push.

    python preview.py           # draws card.svg with sample numbers
    python preview.py --live    # draws it with your real GitHub stats
    python preview.py --no-open # build preview.html without opening a browser

It (1) runs generate.py, (2) renders README.md the way GitHub does, using
GitHub's own Markdown API when you're online, and (3) opens preview.html:
a GitHub-style page showing the README with your *local* card.svg in place
of the published one. Nothing is committed or pushed.

--live needs a token: either set GH_TOKEN, or install the GitHub CLI and run
`gh auth login` once; the script then borrows `gh auth token`.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = "melvin-tai/melvin-tai"


def token() -> str | None:
    if os.environ.get("GH_TOKEN"):
        return os.environ["GH_TOKEN"]
    if shutil.which("gh"):
        r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    return None


def render_markdown(text: str, tok: str | None) -> tuple[str, str]:
    """Return (html, how). Uses GitHub's renderer, which also applies GitHub's HTML sanitiser."""
    body = json.dumps({"text": text, "mode": "gfm", "context": REPO}).encode()
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "profile-preview"}
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    try:
        req = urllib.request.Request("https://api.github.com/markdown", data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode(), "rendered by GitHub's Markdown API (same sanitiser as github.com)"
    except Exception as e:
        # The README is plain HTML, so showing it as-is is a close approximation.
        return text, f"offline approximation (GitHub's Markdown API unreachable: {e.__class__.__name__})"


def use_local_card(html: str) -> str:
    """Point any <img> that loads card.svg (raw URL or GitHub's image proxy) at the local file."""
    stamp = int(time.time())
    return re.sub(r"<img\b[^>]*card\.svg[^>]*>",
                  lambda m: re.sub(r'\ssrc="[^"]*"', f' src="card.svg?v={stamp}"', m.group(0)), html)


PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Profile README preview</title>
<style>
  :root {{ color-scheme: dark; --bg:#0d1117; --box:#0d1117; --line:#30363d; --fg:#e6edf3; --muted:#9198a1; --link:#4493f8; }}
  body.light {{ color-scheme: light; --bg:#ffffff; --box:#ffffff; --line:#d1d9e0; --fg:#1f2328; --muted:#59636e; --link:#0969da; }}
  body {{ margin:0; background:var(--bg); color:var(--fg);
         font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans",Helvetica,Arial,sans-serif; }}
  .bar {{ position:sticky; top:0; display:flex; gap:8px; align-items:center; flex-wrap:wrap; padding:10px 16px;
          border-bottom:1px solid var(--line); background:var(--bg); z-index:1; }}
  .bar b {{ margin-right:8px; }}
  .bar button {{ font:inherit; color:var(--fg); background:transparent; border:1px solid var(--line);
                 border-radius:6px; padding:4px 10px; cursor:pointer; }}
  .bar button[aria-pressed="true"] {{ border-color:var(--link); color:var(--link); }}
  .note {{ color:var(--muted); font-size:12px; margin-left:auto; }}
  main {{ padding:24px 16px; }}
  .readme {{ margin:0 auto; border:1px solid var(--line); border-radius:6px; background:var(--box); padding:24px;
             width:var(--w,880px); max-width:100%; box-sizing:border-box; }}
  .crumb {{ font-size:12px; color:var(--muted); margin-bottom:16px; font-family:ui-monospace,monospace; }}
  .readme img {{ max-width:100%; height:auto; }}
  .readme a {{ color:var(--link); text-decoration:none; }} .readme a:hover {{ text-decoration:underline; }}
  .readme p {{ margin:0 0 16px; }} .readme sub {{ color:var(--muted); }}
</style></head>
<body>
<div class="bar">
  <b>Preview</b>
  <button data-theme="dark" aria-pressed="true">GitHub dark</button>
  <button data-theme="light" aria-pressed="false">GitHub light</button>
  <span>·</span>
  <button data-w="880px" aria-pressed="true">Desktop</button>
  <button data-w="360px" aria-pressed="false">Phone</button>
  <span>·</span>
  <button id="replay">Replay animation</button>
  <span class="note">{how}. Widths are approximate.</span>
</div>
<main><div class="readme">
  <div class="crumb">{repo} / README.md</div>
  {html}
</div></main>
<script>
  const pick = (sel, btn) => document.querySelectorAll(sel).forEach(b => b.setAttribute('aria-pressed', b === btn));
  document.querySelectorAll('[data-theme]').forEach(b => b.onclick = () => {{
    document.body.classList.toggle('light', b.dataset.theme === 'light'); pick('[data-theme]', b); }});
  document.querySelectorAll('[data-w]').forEach(b => b.onclick = () => {{
    document.querySelector('.readme').style.setProperty('--w', b.dataset.w); pick('[data-w]', b); }});
  document.getElementById('replay').onclick = () => document.querySelectorAll('img[src*="card.svg"]')
    .forEach(i => i.src = 'card.svg?v=' + Date.now());
</script>
</body></html>
"""


def main() -> None:
    live = "--live" in sys.argv
    tok = token()
    env = dict(os.environ)
    args = [sys.executable, str(ROOT / "generate.py")]
    if live:
        if not tok:
            sys.exit("--live needs GH_TOKEN, or the GitHub CLI after `gh auth login`.")
        env["GH_TOKEN"] = tok
    else:
        args.append("--demo")
    subprocess.run(args, check=True, env=env, cwd=ROOT)

    html, how = render_markdown((ROOT / "README.md").read_text(encoding="utf-8"), tok)
    out = ROOT / "preview.html"
    out.write_text(PAGE.format(html=use_local_card(html), how=escape(how), repo=REPO), encoding="utf-8")
    print(f"Wrote {out.name} ({how})")
    if "--no-open" not in sys.argv:
        webbrowser.open(out.as_uri())


if __name__ == "__main__":
    main()

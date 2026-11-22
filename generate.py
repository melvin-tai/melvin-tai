#!/usr/bin/env python3
"""
Night-shift profile card for GitHub: builds card.svg (always in night mode).

    python generate.py          # live GitHub stats (needs GH_TOKEN)
    python generate.py --demo   # sample numbers, for previewing locally

Everything you'd want to change is in profile.toml and ascii.txt.
Needs Python 3.11+. `pip install fonttools` embeds JetBrains Mono so the card
looks identical on every machine; without it, the viewer's monospace is used.
"""
from __future__ import annotations

import base64
import calendar
import datetime as dt
import io
import json
import math
import os
import random
import re
import sys
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache"
FONTS = ROOT / "fonts"
API = "https://api.github.com"

FONT_SIZE = 16
CHAR_W = 9.6          # JetBrains Mono advance = 0.6 em
LINE_H = 20
PAD = 18
TITLE_H = 34
GAP_CHARS = 3
BARS = "▁▂▃▄▅▆▇█"

THEME = dict(
    bg1="#0b1020", bg2="#161d31", bar="#0e1427", border="#27314d",
    text="#c9d1d9", key="#f2b056", value="#a5c8ff", dim="#4f5b76",
    add="#3fb950", rm="#f85149", eye="#ffc857", branch="#8b6b4a", blush="#ff7aa8",
    brow="#a5c8ff", disc="#7d93b8", talon="#f2b056",
    title="#e6edf3", star="#e6edf3", moon="#f4f1e6", moon_shadow="#222b42",
)

Seg = tuple[str, str]   # (text, css class); "" = base colour


# ── small helpers ────────────────────────────────────────────────────────

def add_months(d: dt.date, n: int) -> dt.date:
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def age(born: dt.date, today: dt.date) -> str:
    months = (today.year - born.year) * 12 + today.month - born.month
    if add_months(born, months) > today:
        months -= 1
    d = (today - add_months(born, months)).days
    y, m = divmod(months, 12)
    unit = lambda n, w: f"{n} {w}{'' if n == 1 else 's'}"
    return f"{unit(y, 'year')}, {unit(m, 'month')}, {unit(d, 'day')}"


def seg_len(segs: list[Seg]) -> int:
    return sum(len(t) for t, _ in segs)


def key_segs(key: str) -> list[Seg]:
    out: list[Seg] = []
    for i, part in enumerate(key.split(".")):
        if i:
            out.append((".", ""))
        out.append((part, "key"))
    return out


def dotted(key: list[Seg], value: list[Seg], width: int, indent: int = 2) -> list[Seg]:
    """'  Key: ········ value', right-aligned to exactly `width` characters."""
    n = width - (indent + seg_len(key) + 1 + seg_len(value))
    leader = " " + "·" * (n - 2) + " " if n >= 3 else " " * max(n, 1)
    return [(" " * indent, ""), *key, (":", ""), (leader, "dim"), *value]


def rule(title: str, width: int) -> list[Seg]:
    used = 3 + len(title) + 1
    return [("── ", "dim"), (title, "title"), (" ", ""), ("─" * (width - used), "dim")]


def fmt(n) -> str:
    return f"{n:,}" if isinstance(n, int) else str(n)


# ── the moon ─────────────────────────────────────────────────────────────

SYNODIC = 29.530588853
NEW_MOON = dt.datetime(2000, 1, 6, 18, 14, tzinfo=dt.timezone.utc)


def moon_phase(now: dt.datetime) -> tuple[float, float, str]:
    """(phase 0..1, illuminated fraction, name). 0 = new, 0.5 = full."""
    p = ((now - NEW_MOON).total_seconds() / 86400 / SYNODIC) % 1
    lit = (1 - math.cos(2 * math.pi * p)) / 2
    q = 1 / SYNODIC                      # ~one day either side of the exact moments
    for edge, name in [(q, "New Moon"), (0.25 - q, "Waxing Crescent"), (0.25 + q, "First Quarter"),
                       (0.5 - q, "Waxing Gibbous"), (0.5 + q, "Full Moon"), (0.75 - q, "Waning Gibbous"),
                       (0.75 + q, "Last Quarter"), (1 - q, "Waning Crescent"), (1.01, "New Moon")]:
        if p < edge:
            return p, lit, name
    return p, lit, "New Moon"


def moon_path(cx: float, cy: float, r: float, p: float) -> str:
    """Lit part of the disc: outer limb + elliptical terminator."""
    rx = abs(math.cos(2 * math.pi * p)) * r
    top, bot = f"{cx:.1f} {cy - r:.1f}", f"{cx:.1f} {cy + r:.1f}"
    if p < 0.5:   # waxing: lit on the right
        limb, term = 1, (0 if p < 0.25 else 1)
    else:         # waning: lit on the left
        limb, term = 0, (1 if p > 0.75 else 0)
    return f"M {top} A {r} {r} 0 0 {limb} {bot} A {rx:.2f} {r} 0 0 {term} {top} Z"


# ── GitHub API ───────────────────────────────────────────────────────────

class GitHub:
    def __init__(self, token: str):
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                        "User-Agent": "night-shift-profile-card"}

    def _request(self, method: str, url: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            return e.code, None

    def graphql(self, query: str, **variables):
        status, payload = self._request("POST", f"{API}/graphql", {"query": query, "variables": variables})
        if status != 200 or payload is None or payload.get("errors"):
            raise RuntimeError(f"GraphQL failed ({status}): {payload and payload.get('errors')}")
        return payload["data"]

    def repos(self, login: str, affiliations: list[str]) -> tuple[int, list[dict]]:
        q = """
        query($login: String!, $aff: [RepositoryAffiliation], $cursor: String) {
          user(login: $login) {
            repositories(first: 100, after: $cursor, ownerAffiliations: $aff) {
              totalCount
              pageInfo { hasNextPage endCursor }
              nodes {
                nameWithOwner isFork stargazerCount
                owner { login }
                languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
                  totalSize
                  edges { size node { name color } }
                }
                defaultBranchRef { target { oid } }
              }
            }
          }
        }"""
        nodes, cursor = [], None
        while True:
            page = self.graphql(q, login=login, aff=affiliations, cursor=cursor)["user"]["repositories"]
            nodes += page["nodes"]
            if not page["pageInfo"]["hasNextPage"]:
                return page["totalCount"], nodes
            cursor = page["pageInfo"]["endCursor"]

    def profile(self, login: str) -> dict:
        q = "query($login: String!) { user(login: $login) { createdAt followers { totalCount } } }"
        return self.graphql(q, login=login)["user"]

    def commit_contributions(self, login: str, since_year: int) -> int:
        now = dt.datetime.now(dt.timezone.utc)
        parts = [f'y{y}: contributionsCollection(from: "{y}-01-01T00:00:00Z", to: "{y}-12-31T23:59:59Z") '
                 f"{{ totalCommitContributions }}" for y in range(since_year, now.year + 1)]
        q = f"query($login: String!) {{ user(login: $login) {{ {' '.join(parts)} }} }}"
        return sum(v["totalCommitContributions"] for v in self.graphql(q, login=login)["user"].values())

    def stat(self, full_name: str, kind: str):
        return self._request("GET", f"{API}/repos/{full_name}/stats/{kind}")


def repo_stats(gh: GitHub, login: str, repos: list[dict]) -> tuple[int, int, list[int]]:
    """
    Per repo (cached by default-branch SHA):
      • lines added/deleted by `login`        ← stats/contributors
      • commits per hour of day, in each commit's own local time
                                              ← stats/punch_card (repos you own)
    GitHub computes these lazily; HTTP 202 means "ask again in a moment".
    """
    path = CACHE / "repos.json"
    cache = json.loads(path.read_text()) if path.exists() else {}
    pending: dict[tuple[str, str], str] = {}
    fresh: dict[str, dict] = {}
    for r in repos:
        if r["isFork"] or not r["defaultBranchRef"]:
            continue
        name, sha = r["nameWithOwner"], r["defaultBranchRef"]["target"]["oid"]
        if cache.get(name, {}).get("sha") == sha:
            continue
        fresh[name] = {"sha": sha, "add": 0, "del": 0, "hours": None}
        pending[(name, "contributors")] = sha
        if r["owner"]["login"].lower() == login.lower():
            pending[(name, "punch_card")] = sha

    failed: set[str] = set()
    for wait in (0, 3, 6, 10, 15, 20):
        if not pending:
            break
        time.sleep(wait)
        for (name, kind) in list(pending):
            status, data = gh.stat(name, kind)
            if status == 202:
                continue
            pending.pop((name, kind))
            if status not in (200, 204):
                print(f"  ! {name}: {kind} unavailable (HTTP {status})")
                failed.add(name)
                continue
            entry = fresh[name]
            if kind == "contributors":
                for c in data or []:
                    if (c.get("author") or {}).get("login", "").lower() == login.lower():
                        entry["add"] = sum(w["a"] for w in c["weeks"])
                        entry["del"] = sum(w["d"] for w in c["weeks"])
            else:
                hours = [0] * 24
                for _day, hour, n in data or []:
                    hours[hour] += n
                entry["hours"] = hours
    for name, _ in pending:
        print(f"  ! {name}: GitHub still computing stats; will retry next run")
        failed.add(name)

    for name, entry in fresh.items():
        if name not in failed:
            cache[name] = entry
    live = {r["nameWithOwner"] for r in repos}
    cache = {k: v for k, v in cache.items() if k in live}
    CACHE.mkdir(exist_ok=True)
    path.write_text(json.dumps(cache, indent=1, sort_keys=True) + "\n")

    hours = [0] * 24
    for v in cache.values():
        for h, n in enumerate(v.get("hours") or []):
            hours[h] += n
    return sum(v["add"] for v in cache.values()), sum(v["del"] for v in cache.values()), hours


def language_mix(repos: list[dict], cfg: dict) -> list[list]:
    """
    [[name, colour, share], ...] largest first, over your own non-fork repos.
    weight = "projects": every repo counts equally, split by its own language
    bytes, so one huge notebook full of saved outputs can't drown out the rest.
    weight = "bytes": raw byte totals, the way most stats cards do it.
    """
    weight = cfg.get("weight", "projects")
    exclude = set(cfg.get("exclude", []))
    min_bytes = cfg.get("min_bytes", 1000)
    totals: dict[str, float] = {}
    colours: dict[str, str] = {}
    for r in repos:
        if r["isFork"]:
            continue
        edges = [e for e in r["languages"]["edges"] if e["node"]["name"] not in exclude]
        size = sum(e["size"] for e in edges)
        if size < min_bytes:
            continue
        for e in edges:
            name = e["node"]["name"]
            colours[name] = e["node"]["color"] or "#8b949e"
            totals[name] = totals.get(name, 0) + (e["size"] / size if weight == "projects" else e["size"])
    grand = sum(totals.values()) or 1
    return [[n, colours[n], v / grand] for n, v in sorted(totals.items(), key=lambda kv: -kv[1])]


def fetch_stats(login: str, cfg: dict) -> dict:
    token = os.environ.get("GH_TOKEN") or os.environ.get("ACCESS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("no GH_TOKEN set")
    gh = GitHub(token)
    prof = gh.profile(login)
    owned_total, owned = gh.repos(login, ["OWNER"])
    _, affiliated = gh.repos(login, ["OWNER", "COLLABORATOR", "ORGANIZATION_MEMBER"])
    add, rm, hours = repo_stats(gh, login, affiliated)
    return {
        "created_at": prof["createdAt"][:10],
        "repos": owned_total,
        "stars": sum(r["stargazerCount"] for r in owned),
        "followers": prof["followers"]["totalCount"],
        "commits": gh.commit_contributions(login, int(prof["createdAt"][:4])),
        "loc_add": add, "loc_del": rm, "hours": hours,
        "languages": language_mix(owned, cfg.get("languages", {})),
    }


DEMO = {
    "created_at": "2023-02-14", "repos": 16, "stars": 12, "followers": 1, "commits": 486,
    "loc_add": 184_210, "loc_del": 39_877,
    "hours": [21, 26, 31, 24, 12, 4, 1, 0, 0, 1, 2, 3, 2, 4, 3, 5, 6, 5, 7, 8, 9, 12, 16, 19],
    "languages": [["Jupyter Notebook", "#DA5B0B", 0.46], ["JavaScript", "#f1e05a", 0.29],
                  ["Python", "#3572A5", 0.20], ["CSS", "#663399", 0.03], ["HTML", "#e34c26", 0.02]],
}


# ── card content ─────────────────────────────────────────────────────────

def build_info(cfg: dict, stats: dict | None, now: dt.datetime) -> list[list[Seg] | str]:
    """Rows for the right-hand column. A string row is a marker for special rendering."""
    width = cfg.get("line_width", 56)
    user, _, host = cfg["header"].partition("@")
    today = now.date()
    fills = {"github_age": "—", "age": "—"}
    if stats and stats.get("created_at"):
        fills["github_age"] = age(dt.date.fromisoformat(stats["created_at"]), today)
    if "birthday" in cfg:
        fills["age"] = age(cfg["birthday"], today)

    rows: list[list[Seg] | str] = ["prompt"]
    rows.append([(user, "key b"), ("@", ""), (host, "value b"), (" ", ""),
                 ("─" * (width - len(cfg["header"]) - 1), "dim")])

    for i, section in enumerate(cfg.get("section", [])):
        if i:
            rows += [[], rule(section.get("title", ""), width)]
        for row in section.get("rows", []):
            key, value = row
            if value == "{github_age}" and fills["github_age"] == "—":
                value = "—"
            for k, v in fills.items():
                value = value.replace("{" + k + "}", v)
            line = dotted(key_segs(key), [(value, "value")], width)
            if seg_len(line) > width:
                print(f"  ! '{key}' is {seg_len(line) - width} chars too long for line_width={width}")
            rows.append(line)

    ns = cfg.get("night_shift", {})
    if ns.get("show", True):
        night = set(ns.get("night_hours", [22, 23, 0, 1, 2, 3, 4]))
        hours = (stats or {}).get("hours") or []
        rows += [[], rule("Night Shift", width)]
        if sum(hours):
            top = max(hours)
            clock: list[Seg] = [("00 ", "dim")]
            for h, n in enumerate(hours):
                if n == 0:
                    clock.append((BARS[0], "dim"))
                else:
                    clock.append((BARS[1 + round(n / top * 6)], "value" if h in night else "key"))
            clock.append((" 23", "dim"))
            pct = round(100 * sum(hours[h] for h in night) / sum(hours))
            peak = hours.index(top)
            start, end = min(night, key=lambda h: (h - 12) % 24), max(night, key=lambda h: (h - 12) % 24)
            rows.append(dotted(key_segs("Commit Clock"), clock, width))
            rows.append(dotted(key_segs("After Dark"),
                               [(f"{pct}%", "value"), (f" ({start:02d}–{(end + 1) % 24:02d}h) · peak ", ""),
                                (f"{peak:02d}:00", "value")], width))
        else:
            rows.append(dotted(key_segs("Commit Clock"), [("—", "value")], width))
        _, lit, name = moon_phase(now)
        rows.append(dotted(key_segs("Moon Tonight"), [(name, "value"), (f" · {lit:.0%} lit", "")], width))

    if cfg.get("stats", {}).get("show", True):
        s = stats or {}
        v = lambda k: [(fmt(s.get(k, "—")), "value")]
        lw = 30
        rw = width - lw - 3
        half = lambda k, val, w: dotted(key_segs(k), val, w, indent=0)
        rows += [[], rule("GitHub Stats", width)]
        rows.append(dotted(key_segs("Repos"), v("repos"), lw) + [(" │ ", "dim")] + half("Stars", v("stars"), rw))
        rows.append(dotted(key_segs("Commits"), v("commits"), lw) + [(" │ ", "dim")] + half("Followers", v("followers"), rw))
        if cfg.get("stats", {}).get("lines_of_code", True):
            a, d = s.get("loc_add"), s.get("loc_del")
            if isinstance(a, int) and isinstance(d, int):
                rows.append(dotted(key_segs("Lines of Code"),
                                   [(fmt(a - d), "value"), (" (", ""), (f"+{fmt(a)}", "add"), (" ", ""),
                                    (f"−{fmt(d)}", "rm"), (")", "")], width))
            else:
                rows.append(dotted(key_segs("Lines of Code"), [("—", "value")], width))

    lang_cfg = cfg.get("languages", {})
    langs = (stats or {}).get("languages") or []
    if lang_cfg.get("show", True) and langs:
        rows += [[], rule("Languages", width), {"kind": "langbar", "langs": legend_groups(langs, lang_cfg)}]
        rows += legend_rows(legend_groups(langs, lang_cfg), width)
    rows += [[], "prompt_end"]                # blank line before the next prompt, like a real shell
    return rows


ALIASES = {"Jupyter Notebook": "Jupyter"}


def legend_groups(langs: list[list], cfg: dict) -> list[list]:
    """Top N languages; anything under 1.5% or past N folds into Other."""
    top = [l for l in langs[: cfg.get("max", 5)] if l[2] >= 0.015]
    rest = 1 - sum(l[2] for l in top)
    if rest > 0.005:
        top.append(["Other", "#6e7681", rest])
    return top


def legend_rows(groups: list[list], width: int) -> list[dict]:
    """'● Python 34%  ● Jupyter 30%  …', wrapped to the line width (max two rows)."""
    rows, cur, used = [], [], 2
    for name, colour, share in groups:
        label = ALIASES.get(name, name)
        pct = f"{share * 100:.0f}%" if share >= 0.01 else "<1%"
        item = 2 + len(label) + 1 + len(pct)            # dot + space + name + space + pct
        if cur and used + 2 + item > width:
            rows.append(cur)
            cur, used = [], 2
        used += (2 if cur else 0) + item
        cur.append((label, colour, pct))
    if cur:
        rows.append(cur)
    return [{"kind": "legend", "items": r} for r in rows[:2]]


MARKUP = re.compile(r"\{(\w+):([^}]*)\}")


def parse_art(line: str) -> list[Seg]:
    """ascii.txt markup: {class:text} colours that text (eye, key, dim, branch, value...)."""
    out: list[Seg] = []
    pos = 0
    for m in MARKUP.finditer(line):
        if m.start() > pos:
            out.append((line[pos:m.start()], ""))
        cls, body = m.groups()
        out.append((body, cls))
        pos = m.end()
    if pos < len(line):
        out.append((line[pos:], ""))
    return out


# ── fonts ────────────────────────────────────────────────────────────────

def font_faces(chars: set[str]) -> str:
    try:
        from fontTools import subset
        from fontTools.ttLib import TTFont
    except ImportError:
        return ""
    css = []
    for weight, file in ((400, "JetBrainsMono-Regular.ttf"), (700, "JetBrainsMono-Bold.ttf")):
        src = FONTS / file
        if not src.exists():
            continue
        font = TTFont(src)
        opts = subset.Options()
        opts.flavor = "woff"
        opts.layout_features = []          # no ligatures: keep the grid strictly monospaced
        opts.name_IDs = []
        sub = subset.Subsetter(opts)
        sub.populate(text="".join(sorted(chars)))
        sub.subset(font)
        buf = io.BytesIO()
        font.flavor = "woff"
        font.save(buf)
        b64 = base64.b64encode(buf.getvalue()).decode()
        css.append(f"@font-face {{ font-family: 'Card Mono'; font-weight: {weight}; "
                   f"src: url(data:font/woff;base64,{b64}) format('woff'); }}")
    return "\n".join(css)


# ── rendering ────────────────────────────────────────────────────────────

def render(cfg: dict, stats: dict | None, now: dt.datetime) -> str:
    t = THEME
    width = cfg.get("line_width", 56)
    info = build_info(cfg, stats, now)
    art_path = ROOT / cfg.get("ascii_art", "ascii.txt")
    art_raw = art_path.read_text(encoding="utf-8").rstrip("\n").split("\n") if art_path.exists() else []
    art = [parse_art(a) for a in art_raw]
    art_w = max((seg_len(a) for a in art), default=0)
    offset = max(len(info) - len(art), 0)                 # sit the art on the bottom row

    info_x = PAD + (art_w + GAP_CHARS) * CHAR_W
    art_mid = PAD + art_w * CHAR_W / 2
    W = round(info_x + width * CHAR_W + PAD)
    y0 = TITLE_H + 26
    H = round(y0 + (len(info) - 1) * LINE_H + PAD + 4)
    base = lambda row: y0 + row * LINE_H

    user, _, host = cfg["header"].partition("@")
    command = cfg.get("command", "neofetch")
    prompt_head: list[Seg] = [(f"{user}@{host}", "add b"), (":", ""), ("~", "value b"), ("$ ", "")]
    ph = seg_len(prompt_head)

    # timing (seconds)
    type_start, per_char = 0.35, 0.045
    typed = type_start + len(command) * per_char + 0.2
    step = 0.045

    out: list[str] = []
    chars: set[str] = set()

    def text_el(x: float, row: int, segs: list[Seg], delay: float | None, extra: str = "") -> str:
        n = seg_len(segs)
        if not n:
            return ""
        for s, _ in segs:
            chars.update(s)
        spans = "".join(f'<tspan class="{c}">{escape(s)}</tspan>' if c else escape(s) for s, c in segs)
        style = f' style="animation-delay:{delay:.2f}s"' if delay is not None else ""
        cls = "boot" if delay is not None else ""
        return (f'<text x="{x:.1f}" y="{base(row)}" textLength="{n * CHAR_W:.1f}" '
                f'lengthAdjust="spacingAndGlyphs" class="{cls} {extra}"{style}>{spans}</text>')

    # ── sky: tonight's moon, stars, the odd meteor ──
    sky_rows = offset + next((i for i, a in enumerate(art)
                              if any(s.strip() for s, c in a if c != "dim")), 0)
    sky_bottom = base(sky_rows) - 22
    cx, cy, r = PAD + 7.5 * CHAR_W, y0 + 22, 21
    sky: list[str] = []
    p, _, _ = moon_phase(now)
    rng = random.Random(cfg.get("username", "") + "stars")
    stars = []
    for _ in range(4000):                      # bounded: a short card has less sky
        if len(stars) >= 28:
            break
        x = rng.uniform(PAD + 4, info_x - 2.5 * CHAR_W)
        y = rng.uniform(TITLE_H + 12, sky_bottom)
        if math.hypot(x - cx, y - cy) < r + 16 or any(math.hypot(x - a, y - b) < 18 for a, b, _ in stars):
            continue
        stars.append((x, y, rng.choice([0.7, 0.9, 1.1, 1.4])))
    for i, (x, y, s) in enumerate(stars):
        dur, delay = rng.uniform(2.5, 6), rng.uniform(0, 5)
        if s > 1.3:   # a few four-point sparkles
            d = 3.2
            shape = (f'<path d="M{x:.1f} {y - d:.1f} Q{x:.1f} {y:.1f} {x + d:.1f} {y:.1f} Q{x:.1f} {y:.1f} '
                     f'{x:.1f} {y + d:.1f} Q{x:.1f} {y:.1f} {x - d:.1f} {y:.1f} Q{x:.1f} {y:.1f} {x:.1f} {y - d:.1f}Z"')
        else:
            shape = f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{s}"'
        sky.append(f'{shape} class="star" fill="{t["star"]}" fill-opacity="{0.35 + s / 3:.2f}" '
                   f'style="animation-duration:{dur:.1f}s;animation-delay:{delay:.1f}s"/>')
    mx0, my0 = info_x - 6 * CHAR_W, TITLE_H + 26
    sky.append(f'<g class="meteor"><line x1="{mx0:.0f}" y1="{my0}" x2="{mx0 - 46:.0f}" y2="{my0 + 22}" '
               f'stroke="url(#meteor)" stroke-width="1.4" stroke-linecap="round"/></g>')
    sky.append(f'<circle cx="{cx:.1f}" cy="{cy}" r="{r * 2.4:.0f}" fill="url(#halo)"/>')
    sky.append(f'<circle cx="{cx:.1f}" cy="{cy}" r="{r}" fill="{t["moon_shadow"]}"/>')
    sky.append(f'<clipPath id="lit"><path d="{moon_path(cx, cy, r, p)}"/></clipPath>')
    sky.append(f'<g clip-path="url(#lit)"><circle cx="{cx:.1f}" cy="{cy}" r="{r}" fill="{t["moon"]}"/>'
               f'<circle cx="{cx - 6:.1f}" cy="{cy - 5}" r="4.2" fill="#000" fill-opacity=".07"/>'
               f'<circle cx="{cx + 7:.1f}" cy="{cy + 6}" r="5.5" fill="#000" fill-opacity=".06"/>'
               f'<circle cx="{cx + 3:.1f}" cy="{cy - 10}" r="2.4" fill="#000" fill-opacity=".07"/>'
               f'<circle cx="{cx - 9:.1f}" cy="{cy + 9}" r="2" fill="#000" fill-opacity=".06"/></g>')

    # ── art ──
    # Characters marked {glare:…}, {eye:…}, {beak:…} or {blush:…} in ascii.txt are drawn
    # as small vector shapes instead of glyphs. "glare" is a hunting owl's eye: amber iris,
    # soft glow, and a lid angled down towards the beak; "eye" is the round, friendly one.
    sprites: list[str] = []
    for i, segs in enumerate(art):
        col, plain = 0, []
        for s, c in segs:
            if c in ("eye", "blush", "beak", "glare"):
                for j, ch in enumerate(s):
                    if ch.isspace():
                        continue
                    x, y = PAD + (col + j + 0.5) * CHAR_W, base(offset + i) - 5.5
                    if c == "glare":
                        inner = 1 if x < art_mid else -1          # direction of the beak
                        hi, lo = y - 12.0, y - 4.5                 # lid: high outside, low inside
                        ox, ix = x - 19 * inner, x + 19 * inner
                        cid = f"lid{len(sprites)}"
                        sprites.append(
                            f'<clipPath id="{cid}"><path d="M{ox:.1f} {hi:.1f} L{ix:.1f} {lo:.1f} '
                            f'L{ix:.1f} {y + 15:.1f} L{ox:.1f} {y + 15:.1f} Z"/></clipPath>'
                            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="23" fill="url(#eyeglow)"/>'
                            f'<g class="owleye"><g clip-path="url(#{cid})">'
                            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="15" fill="url(#iris)"/>'
                            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="15" fill="none" stroke="#8a4b08" stroke-width="1.2"/>'
                            f'<circle cx="{x + 0.6 * inner:.1f}" cy="{y + 0.6:.1f}" r="7.4" fill="#090603"/>'
                            f'<circle cx="{x - 3.2 * inner:.1f}" cy="{y - 1.2:.1f}" r="2" fill="#fff" fill-opacity=".9"/>'
                            f'</g><line x1="{ox + 3.5 * inner:.1f}" y1="{hi + 1.2:.1f}" x2="{ix - 2 * inner:.1f}" '
                            f'y2="{lo + 0.4:.1f}" stroke="{t["brow"]}" stroke-width="1.6" stroke-linecap="round"/></g>')
                    elif c == "eye":
                        sprites.append(
                            f'<g class="owleye"><circle cx="{x:.1f}" cy="{y:.1f}" r="10.5" fill="{t["eye"]}"/>'
                            f'<circle cx="{x:.1f}" cy="{y + 1:.1f}" r="6.6" fill="#1a1206"/>'
                            f'<circle cx="{x - 3.2:.1f}" cy="{y - 3:.1f}" r="2.7" fill="#fff"/>'
                            f'<circle cx="{x + 3:.1f}" cy="{y + 3.4:.1f}" r="1.2" fill="#fff" fill-opacity=".85"/></g>')
                    elif c == "beak":
                        sprites.append(f'<path d="M{x - 4.2:.1f} {y - 2.6:.1f} L{x + 4.2:.1f} {y - 2.6:.1f} '
                                       f'L{x:.1f} {y + 3.6:.1f} Z" fill="{t["key"]}" stroke="{t["key"]}" '
                                       f'stroke-width="1.6" stroke-linejoin="round"/>')
                    else:
                        sprites.append(f'<ellipse cx="{x:.1f}" cy="{y + 1:.1f}" rx="7.5" ry="4" '
                                       f'fill="{t["blush"]}" fill-opacity=".72"/>')
                s, c = " " * len(s), ""
            plain.append((s, c))
            col += len(s)
        out.append(text_el(PAD, offset + i, plain, typed + 0.1))
    if sprites:
        out.append(f'<g class="boot" style="animation-delay:{typed + 0.1:.2f}s">{"".join(sprites)}</g>')

    # ── info column ──
    k = 0
    for row, item in enumerate(info):
        if item == "prompt":
            head = text_el(info_x, row, prompt_head, None)
            cmd_x = info_x + ph * CHAR_W
            chars.update(command)
            typed_spans = "".join(f'<tspan class="ch" style="animation-delay:{type_start + i * per_char:.3f}s">'
                                  f'{escape(c)}</tspan>' for i, c in enumerate(command))
            out.append(head)
            out.append(f'<text x="{cmd_x:.1f}" y="{base(row)}" textLength="{len(command) * CHAR_W:.1f}" '
                       f'lengthAdjust="spacingAndGlyphs">{typed_spans}</text>')
            end_x = cmd_x + len(command) * CHAR_W
            out.append(f'<rect class="cursor cursor1" x="{end_x:.1f}" y="{base(row) - 14}" width="{CHAR_W:.1f}" '
                       f'height="18" fill="{t["text"]}"/>')
        elif isinstance(item, dict) and item["kind"] == "langbar":
            k += 1
            x0, x1 = info_x + 2 * CHAR_W, info_x + width * CHAR_W
            yb, hb = base(row) - 9, 9
            x, parts = x0, []
            for i, (_, colour, share) in enumerate(item["langs"]):
                w = (x1 - x0) * share
                gap = 2 if i < len(item["langs"]) - 1 else 0
                parts.append(f'<rect x="{x:.1f}" y="{yb}" width="{max(w - gap, 0.5):.1f}" height="{hb}" fill="{colour}"/>')
                x += w
            out.append(f'<clipPath id="barclip"><rect x="{x0:.1f}" y="{yb}" width="{x1 - x0:.1f}" height="{hb}" rx="4.5"/></clipPath>'
                       f'<g class="boot" style="animation-delay:{typed + k * step:.2f}s">'
                       f'<g class="grow" clip-path="url(#barclip)" style="transform-origin:{x0:.1f}px {yb}px;'
                       f'animation-delay:{typed + k * step:.2f}s">{"".join(parts)}</g></g>')
        elif isinstance(item, dict) and item["kind"] == "legend":
            k += 1
            segs: list[Seg] = [("  ", "")]
            dots = []
            for j, (label, colour, pct) in enumerate(item["items"]):
                if j:
                    segs.append(("  ", ""))
                dots.append((seg_len(segs), colour))
                segs += [("  ", ""), (label, ""), (" ", ""), (pct, "dim")]
            d = typed + k * step
            out.append(text_el(info_x, row, segs, d))
            circles = "".join(f'<circle cx="{info_x + (c + 0.45) * CHAR_W:.1f}" cy="{base(row) - 5}" r="4.2" fill="{col}"/>'
                              for c, col in dots)
            out.append(f'<g class="boot" style="animation-delay:{d:.2f}s">{circles}</g>')
        elif item == "prompt_end":
            k += 1
            d = typed + k * step
            out.append(text_el(info_x, row, prompt_head, d))
            out.append(f'<rect class="cursor cursor2" x="{info_x + ph * CHAR_W:.1f}" y="{base(row) - 14}" '
                       f'width="{CHAR_W:.1f}" height="18" fill="{t["text"]}" style="animation-delay:{d:.2f}s,{d:.2f}s"/>')
        else:
            k += 1
            out.append(text_el(info_x, row, item, typed + k * step))

    # ── title bar ──
    tz = now.strftime("%z")
    stamp = f"updated {now.day} {now:%b %Y}, {now:%H:%M} UTC{tz[0]}{int(tz[1:3])}" + (f":{tz[3:]}" if tz[3:] != "00" else "")
    title = cfg.get("title_bar", f"{user}@{host}: ~")
    chars.update(title + stamp)
    dots = "".join(f'<circle cx="{PAD + 6 + i * 20}" cy="{TITLE_H / 2}" r="6" fill="{c}"/>'
                   for i, c in enumerate(("#ff5f57", "#febc2e", "#28c840")))
    bar = (f'<rect width="{W}" height="{TITLE_H}" fill="{t["bar"]}"/>'
           f'<line x1="0" y1="{TITLE_H}" x2="{W}" y2="{TITLE_H}" stroke="{t["border"]}"/>{dots}'
           f'<text x="{W / 2:.0f}" y="{TITLE_H / 2 + 5}" text-anchor="middle" class="dim small">{escape(title)}</text>'
           f'<text x="{W - PAD}" y="{TITLE_H / 2 + 5}" text-anchor="end" class="dim small">{escape(stamp)}</text>')

    faces = font_faces(chars | set("0123456789"))
    shift = len(command) * CHAR_W
    css = f"""
{faces}
text {{ font-family: 'Card Mono', 'JetBrains Mono', ui-monospace, SFMono-Regular, Consolas, Menlo, monospace;
        font-size: {FONT_SIZE}px; white-space: pre; fill: {t['text']}; }}
.small {{ font-size: 12.5px; }}
.b, .title {{ font-weight: 700; }}
.key {{ fill: {t['key']}; }} .value {{ fill: {t['value']}; }} .dim {{ fill: {t['dim']}; }}
.add {{ fill: {t['add']}; }} .rm {{ fill: {t['rm']}; }} .title {{ fill: {t['title']}; }}
.eye {{ fill: {t['eye']}; font-weight: 700; }} .branch {{ fill: {t['branch']}; }}
.brow {{ fill: {t['brow']}; font-weight: 700; }} .disc {{ fill: {t['disc']}; }} .talon {{ fill: {t['talon']}; font-weight: 700; }}
@keyframes on {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
@keyframes blink {{ 50% {{ opacity: 0; }} }}
@keyframes type {{ from {{ transform: translateX(-{shift:.1f}px); }} to {{ transform: translateX(0); }} }}
@keyframes gone {{ to {{ opacity: 0; }} }}
@keyframes grow {{ from {{ transform: scaleX(0); }} to {{ transform: scaleX(1); }} }}
@keyframes twinkle {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: .25; }} }}
@keyframes owlblink {{ 0%, 91%, 97%, 100% {{ transform: scaleY(1); }} 94% {{ transform: scaleY(.08); }} }}
@keyframes meteor {{ 0%, 88% {{ opacity: 0; transform: translate(0, 0); }}
                     90% {{ opacity: 1; }} 97%, 100% {{ opacity: 0; transform: translate(-150px, 72px); }} }}
.boot {{ animation: on .35s ease-out both; }}
.ch {{ animation: on .01s linear both; }}
.cursor1 {{ animation: type {len(command) * per_char:.2f}s steps({len(command)}) {type_start}s both,
                       gone .01s linear {typed:.2f}s forwards; }}
.cursor2 {{ animation: on .01s linear both, blink 1.1s step-end infinite; }}
.grow {{ animation: grow .9s cubic-bezier(.2, .7, .2, 1) both; }}
.star {{ animation: twinkle 4s ease-in-out infinite; }}
.meteor {{ opacity: 0; animation: meteor 11s linear 4s infinite; }}
.owleye {{ transform-box: fill-box; transform-origin: center; animation: owlblink 5.5s ease-in-out 2.5s infinite; }}
@media (prefers-reduced-motion: reduce) {{
  * {{ animation: none !important; }}
  .cursor1, .meteor {{ opacity: 0; }}
}}
"""
    defs = (f'<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{t["bg1"]}"/>'
            f'<stop offset="1" stop-color="{t["bg2"]}"/></linearGradient>'
            f'<radialGradient id="iris" cx=".45" cy=".42" r=".6"><stop offset="0" stop-color="#ffe08a"/>'
            f'<stop offset=".55" stop-color="{t["eye"]}"/><stop offset="1" stop-color="#d9861c"/></radialGradient>'
            f'<radialGradient id="eyeglow"><stop offset=".45" stop-color="{t["eye"]}" stop-opacity=".22"/>'
            f'<stop offset="1" stop-color="{t["eye"]}" stop-opacity="0"/></radialGradient>'
            f'<radialGradient id="halo"><stop offset="0" stop-color="{t["moon"]}" stop-opacity=".28"/>'
            f'<stop offset="1" stop-color="{t["moon"]}" stop-opacity="0"/></radialGradient>'
            f'<linearGradient id="meteor" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff" stop-opacity="1"/>'
            f'<stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>'
            f'<clipPath id="card"><rect width="{W}" height="{H}" rx="12"/></clipPath>')
    body = "\n".join(x for x in out if x)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xml:space="preserve" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(cfg['header'])}: neofetch-style profile card">
<style>{css}</style>
<defs>{defs}</defs>
<g clip-path="url(#card)">
<rect width="{W}" height="{H}" fill="url(#bg)"/>
{bar}
<g class="boot" style="animation-delay:{typed:.2f}s">{''.join(sky)}</g>
{body}
</g>
<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="12" fill="none" stroke="{t['border']}"/>
</svg>
"""


# ── main ─────────────────────────────────────────────────────────────────

def main() -> None:
    cfg = tomllib.loads((ROOT / "profile.toml").read_text(encoding="utf-8"))
    login = cfg.get("username") or os.environ.get("GITHUB_REPOSITORY_OWNER", "")
    now = dt.datetime.now(ZoneInfo(cfg.get("timezone", "UTC")))

    stats_path = CACHE / "stats.json"
    if "--demo" in sys.argv:
        stats = DEMO
    else:
        try:
            stats = fetch_stats(login, cfg)
            CACHE.mkdir(exist_ok=True)
            stats_path.write_text(json.dumps(stats, indent=1) + "\n")
            print(f"Fetched stats for {login}: " + ", ".join(f"{k}={v}" for k, v in stats.items()
                                                             if k not in ("hours", "languages")))
            print("  languages: " + ", ".join(f"{n} {p:.0%}" for n, _, p in stats["languages"]))
        except Exception as e:     # keep the last good numbers rather than fail the build
            print("  ! could not fetch stats:", e)
            stats = json.loads(stats_path.read_text()) if stats_path.exists() else None
            if stats:
                print("  using last saved stats from cache/stats.json")

    (ROOT / "card.svg").write_text(render(cfg, stats, now), encoding="utf-8")
    print("Wrote card.svg")


if __name__ == "__main__":
    main()

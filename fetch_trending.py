#!/usr/bin/env python3
# coding=utf-8
"""
GitHub Trending 抓取脚本 —— 放在独立数据仓库中由 GitHub Actions 定时运行

职责：抓取 github.com/trending 的日/周/月榜，解析为 JSON 写入
data/trending/{daily,weekly,monthly}.json 并提交。

为什么由 Actions 抓：Actions runner 在境外，访问 github.com 稳定；
TrendRadar（NAS）改从 Gitee 拉这里的 JSON 文件（gitee.com 国内畅通），
彻底绕开 github.com 网页不可达的问题。

零依赖（标准库）。解析正则与 trendradar/crawler/github_trending.py
保持同步（GitHub 页面改版时两处一起更新）。
"""

import json
import os
import re
import urllib.request
from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "trending")
PERIODS = ["daily", "weekly", "monthly"]
LIMIT = 25

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# trending 页面结构（与 trendradar/crawler/github_trending.py 同步，2026-11 实测）
_ROW_SPLIT = '<article class="Box-row">'
_REPO_RE = re.compile(r'<h2[^>]*>\s*<a[^>]*href="/([^"]+?)"', re.S)
_DESC_RE = re.compile(r'<p class="col-9[^"]*"[^>]*>\s*(.*?)\s*</p>', re.S)
_LANG_RE = re.compile(r'itemprop="programmingLanguage">([^<]+)<')
_TOTAL_RE = re.compile(r'href="/[^"]+/stargazers".*?</svg>\s*([\d,]+)', re.S)
_PERIOD_RE = re.compile(r'([\d,]+)\s+stars\s+(today|this week|this month)')


def _clean_text(value):
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def _parse_count_str(text):
    try:
        return int(str(text).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0


def parse_trending_html(html, since):
    """解析 trending 页 HTML → 结构化条目列表"""
    repos = []
    for block in html.split(_ROW_SPLIT)[1:]:
        body = block.split("</article>")[0]

        m = _REPO_RE.search(body)
        if not m:
            continue
        repo = _clean_text(m.group(1))
        if "/" not in repo:
            continue

        desc = ""
        dm = _DESC_RE.search(body)
        if dm:
            desc = _clean_text(re.sub(r"<[^>]+>", "", dm.group(1)))

        lang = ""
        lm = _LANG_RE.search(body)
        if lm:
            lang = _clean_text(lm.group(1))

        stars, period_stars = 0, 0
        tm = _TOTAL_RE.search(body)
        if tm:
            stars = _parse_count_str(tm.group(1))
        pm = _PERIOD_RE.search(body)
        if pm:
            period_stars = _parse_count_str(pm.group(1))

        repos.append({
            "rank": len(repos) + 1,
            "repo": repo,
            "description": desc,
            "language": lang,
            "stars": stars,
            "period_stars": period_stars,
            "period": since,
            "url": f"https://github.com/{repo}",
        })
        if len(repos) >= LIMIT:
            break
    return repos


def fetch(since):
    url = f"https://github.com/trending/{since}"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=25) as resp:
        html = resp.read().decode("utf-8", "ignore")
    if _ROW_SPLIT.split(" ")[0].replace("<", "") not in html and "Box-row" not in html:
        title_m = re.search(r"<title>(.*?)</title>", html, re.S)
        title = title_m.group(1).strip()[:120] if title_m else "(no title)"
        print(f"[DEBUG] {since}: no Box-row in page. len={len(html)} title={title!r}")
        print(f"[DEBUG] head={html[:300]!r}")
    repos = parse_trending_html(html, since)
    if not repos:
        raise RuntimeError(f"no rows parsed for {since} (page structure changed?)")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "period": since,
        "source": "github.com/trending (github-actions)",
        "count": len(repos),
        "repos": repos,
    }


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    ok = 0
    for since in PERIODS:
        try:
            payload = fetch(since)
            path = os.path.join(DATA_DIR, since + ".json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=1)
            print(f"[OK] {since}: {payload['count']} repos -> {path}")
            ok += 1
        except Exception as e:
            print(f"[FAIL] {since}: {e}")
    if ok == 0:
        raise SystemExit("all periods failed — keeping previous data")


if __name__ == "__main__":
    main()

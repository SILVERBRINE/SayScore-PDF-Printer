"""Record star and installer-download history and draw them as SVG charts.

GitHub only reports current download totals, so a daily workflow appends one
row per day to downloads.csv; star dates come from the stargazers API.

    GITHUB_TOKEN=... python scripts/update_stats.py --repo owner/name --out stats-dir
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import urllib.request

ASSET_PREFIX = "SayScorePDF-Setup"


def api(path: str, accept: str = "application/vnd.github+json") -> list | dict:
    request = urllib.request.Request(f"https://api.github.com{path}", headers={
        "Accept": accept, "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "sayscore-stats"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def paged(path: str, accept: str = "application/vnd.github+json") -> list:
    items, page = [], 1
    while True:
        batch = api(f"{path}{'&' if '?' in path else '?'}per_page=100&page={page}", accept)
        items += batch
        if len(batch) < 100:
            return items
        page += 1


def star_dates(repo: str) -> list[date]:
    stars = paged(f"/repos/{repo}/stargazers", "application/vnd.github.star+json")
    return sorted(datetime.fromisoformat(s["starred_at"].replace("Z", "+00:00")).date() for s in stars)


def installer_downloads(repo: str) -> int:
    return sum(asset["download_count"]
               for release in paged(f"/repos/{repo}/releases") if not release["draft"]
               for asset in release["assets"] if asset["name"].startswith(ASSET_PREFIX))


def cumulative_by_day(days: list[date], until: date) -> list[tuple[date, int]]:
    if not days:
        return [(until, 0)]
    points, count, index, day = [], 0, 0, days[0]
    while day <= until:
        while index < len(days) and days[index] <= day:
            count, index = count + 1, index + 1
        points.append((day, count))
        day += timedelta(days=1)
    return points


def chart(title: str, points: list[tuple[date, int]], color: str) -> str:
    width, height, left, right, top, bottom = 640, 240, 48, 16, 40, 32
    plot_w, plot_h = width - left - right, height - top - bottom
    peak = max(1, max(value for _, value in points))
    span = max(1, (points[-1][0] - points[0][0]).days)

    def xy(day: date, value: int) -> str:
        x = left + plot_w * (day - points[0][0]).days / span
        y = top + plot_h * (1 - value / peak)
        return f"{x:.1f},{y:.1f}"

    line = " ".join(xy(day, value) for day, value in points)
    area = f"{left},{top + plot_h} {line} {left + plot_w},{top + plot_h}"
    text = 'font-family="-apple-system,Segoe UI,sans-serif" fill="#8b949e"'
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <text x="{left}" y="24" {text} font-size="15" font-weight="600">{title} · {points[-1][1]:,}</text>
  <line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="#8b949e" stroke-opacity="0.4"/>
  <polygon points="{area}" fill="{color}" fill-opacity="0.15"/>
  <polyline points="{line}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round"/>
  <text x="{left - 8}" y="{top + 4}" {text} font-size="11" text-anchor="end">{peak:,}</text>
  <text x="{left - 8}" y="{top + plot_h}" {text} font-size="11" text-anchor="end">0</text>
  <text x="{left}" y="{height - 10}" {text} font-size="11">{points[0][0].isoformat()}</text>
  <text x="{left + plot_w}" y="{height - 10}" {text} font-size="11" text-anchor="end">{points[-1][0].isoformat()}</text>
</svg>
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    today = date.today()

    history = args.out / "downloads.csv"
    rows: dict[date, int] = {}
    if history.is_file():
        with history.open(newline="", encoding="utf-8") as file:
            rows = {date.fromisoformat(r["date"]): int(r["downloads"]) for r in csv.DictReader(file)}
    rows[today] = installer_downloads(args.repo)
    with history.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["date", "downloads"])
        writer.writerows((day.isoformat(), rows[day]) for day in sorted(rows))

    downloads = sorted(rows.items())
    if len(downloads) == 1:
        downloads.insert(0, (today - timedelta(days=1), 0))
    (args.out / "downloads.svg").write_text(chart("Installer downloads", downloads, "#2f81f7"), encoding="utf-8")
    stars = cumulative_by_day(star_dates(args.repo), today)
    if len(stars) == 1:
        stars.insert(0, (today - timedelta(days=1), 0))
    (args.out / "stars.svg").write_text(chart("GitHub Stars", stars, "#e3b341"), encoding="utf-8")
    print(f"downloads={rows[today]} stars={stars[-1][1]}")


if __name__ == "__main__":
    main()

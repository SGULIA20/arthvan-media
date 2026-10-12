"""Weekly ad radar: read competitors' public Play listings and YouTube results, store a snapshot, diff against last week.
python -m radar.collect            writes radar/snapshots/YYYY-MM-DD.json and prints a summary
"""
import html, json, re, ssl, sys, urllib.parse, urllib.request
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
_ctx = ssl.create_default_context(cafile="/etc/ssl/cert.pem") if Path("/etc/ssl/cert.pem").exists() else ssl.create_default_context()


def get(url: str) -> str:
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40, context=_ctx).read().decode("utf-8", "ignore")


def play(pkg: str) -> dict:
    s = get(f"https://play.google.com/store/apps/details?id={pkg}&hl=en&gl=IN")
    def m(rx):
        x = re.search(rx, s, re.S); return html.unescape(x.group(1)).strip() if x else None
    about = m(r'data-g-id="description"[^>]*>(.*?)</div>')
    about = re.sub(r"<[^>]+>", " ", about or "")[:1500]
    return {"title": m(r'<h1[^>]*><span[^>]*>([^<]*)'), "short": m(r'name="description" content="([^"]*)'),
            "installs": m(r'(\d[\d,.]*[KMB]?\+?)\s*</div><div[^>]*>Downloads'), "rating": m(r'itemprop="starRating"[^>]*><div[^>]*>([\d.]+)'),
            "updated": m(r'Updated on</div><div[^>]*>([^<]*)'), "about": re.sub(r"\s+", " ", about)}


def youtube(q: str) -> list:
    s = get("https://www.youtube.com/results?search_query=" + urllib.parse.quote(q) + "&sp=CAI%253D")  # newest first
    vids, seen = [], set()
    for vid, title in re.findall(r'"videoId":"([A-Za-z0-9_-]{11})".{0,400}?"title":\{"runs":\[\{"text":"([^"]{3,120})"', s):
        if vid not in seen:
            seen.add(vid); vids.append({"id": vid, "title": html.unescape(title)})
        if len(vids) >= 6:
            break
    return vids


def main() -> int:
    watch = json.loads((HERE / "watchlist.json").read_text())
    snap = {"date": date.today().isoformat(), "apps": {}}
    for app, comps in watch.items():
        snap["apps"][app] = {}
        for c in comps:
            row = {"name": c["name"]}
            try:
                row["play"] = play(c["play"])
            except Exception as e:
                row["play_error"] = f"{type(e).__name__}"
            try:
                row["youtube"] = youtube(c["yt"])
            except Exception as e:
                row["youtube_error"] = f"{type(e).__name__}"
            snap["apps"][app][c["name"]] = row
            p = row.get("play") or {}
            print(f"{app:10s} {c['name']:12s} installs {p.get('installs') or '?':6s} updated {p.get('updated') or '?':14s} videos {len(row.get('youtube', []))}")
    out = HERE / "snapshots"; out.mkdir(exist_ok=True)
    (out / f"{snap['date']}.json").write_text(json.dumps(snap, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

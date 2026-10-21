"""Relays the founder's evening scorecard (built by the sg-content repo, saved as logs/evening-latest.txt there) through THIS bot,
so both bots show the same table (founder, 21 Oct 2026). Sends only a card dated today; otherwise says it is missing."""
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

from . import notify

URL = "https://raw.githubusercontent.com/SGULIA20/sg-content/main/logs/evening-latest.txt"


def fetch(url: str = URL) -> str:
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"scorecard not fetched: {str(e)[:120]}", flush=True)
        return ""


def message(card: str, today) -> str:
    stamp = today.strftime("%a %d %b %Y")
    if card.strip() and stamp in card.splitlines()[0]:
        return card
    return f"📋 Evening status {stamp}: the scorecard from the content pipeline is not available yet (its job may have run late)."


def main(argv=None) -> int:
    today = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).date()      # the card is dated in India time
    text = message(fetch(), today)
    print(text)
    return 0 if notify.send(text) else 1


if __name__ == "__main__":
    sys.exit(main())

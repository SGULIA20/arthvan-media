# Daily autoposter: design

Date: 2026-10-10. Owner: Sanjeev Gulia. Status: approved by the founder in chat on 2026-10-10.
The founder waived spec and plan review gates ("you dont need to show me anything for any approval").

## Goal
Every day at 18:00 Lagos time (17:00 UTC), publish one content set to the founder's Instagram
account (sanjeev_gulia, Creator account) in three formats: a swipeable feed post, a Reel with
music, and a Story. The set promotes ONE app per day. The apps alternate: Waypoint, ScoreMyBiz,
Waypoint, ... Nothing needs the founder's attention. Facebook gets the Reel through Meta Accounts
Centre sharing (set up by the founder). LinkedIn, Threads and YouTube are out of scope for now.

## Non-goals
Clickable links (Instagram does not allow them in captions or via API), paid ads, comment or DM
automation, LinkedIn, deleting posts.

## Architecture
GitHub Actions workflow in the public repo SGULIA20/arthvan-media. No server, no Mac required.

1. Cron 17:00 UTC (and manual dispatch with mode: render | prepare | post).
2. `select`: pure function of the date (Lagos time). Even/odd day index picks the app; a counter
   picks the next item in that app's bank; the item picks its visual theme and music seed.
3. `lint`: guardrails. A failing item is skipped and the next item is tried (max 5), then the run fails loudly.
4. `render`: Playwright (Chromium) draws each slide from an HTML template. Static 4:5 JPEG slides for the
   post, an animated 9:16 frame sequence for the Reel and Story, encoded with ffmpeg together with music.
5. `music`: original tracks synthesised with numpy per day (no copyright risk), mood per app.
6. `publish`: commit the day's media under out/YYYY-MM-DD/, wait until the raw.githubusercontent.com URLs
   answer, create every Instagram container, wait until all are FINISHED, only then publish post, Reel, Story.
   Nothing is public unless all three are ready.
7. `log`: append to logs/posts.jsonl. A second run on the same date does nothing (idempotent).

Secrets (GitHub Actions secrets): IG_ACCESS_TOKEN, IG_USER_ID. No other secrets.

## Content
content/apps.json holds per-app facts: Play Store link, palette, icon, footer, allowed fixed numbers, banned phrases.
content/<app>.json holds the item bank. An item is a list of slides (hook, stat, bars, steps, quote) plus a caption
body and hashtags. One definition yields all three formats, so the post, Reel and Story always agree.
Play Store links: ScoreMyBiz https://play.google.com/store/apps/details?id=com.scoremybiz.app
Waypoint https://play.google.com/store/apps/details?id=com.arthvananalytics.waypoint

## Guardrails (hard, enforced by lint)
- Only facts the product does today. No invented statistics. Digits are allowed only for the fixed facts in
  apps.json or inside a slide marked `sample`, which renders an "Example" tag and adds the disclaimer.
- Money content carries "Example figures for illustration. Not financial advice."
- Waypoint: no privacy, safety, security, anonymity guarantees and no mental-health claims. The 9 Oct 2026 audit
  found such claims were false. Banned: nobody, no one can, never, guarantee, private, privacy, secure, encrypted,
  safe, untraceable, therapy, anxiety, depression, mental health, cure, heal.
- Global: no "best", "number one", "guaranteed", "risk-free", income or profit promises.
- Every caption ends with the app's Play Store link and "Link in bio".
- A PAUSE repository variable set to 1 stops all posting.

## Failure handling
GitHub emails the owner when a run fails. The token (60 days, created 2026-10-10, expires about 2026-12-09) is
refreshed by a weekly workflow; if the refresh returns a different token string the workflow fails so the
founder is told. Scheduled workflows can be disabled after 60 days without repo activity; daily commits keep it active.

## Testing
Unit tests for select (alternation, determinism, wrap-around) and lint (banned phrases, number rule, links).
Render checks: resolution, duration, audio stream present, frames not blank. A manual `prepare` run in Actions
exercises everything except the final publish call, which is already proven by the live demo on 2026-10-10.

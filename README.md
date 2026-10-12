# arthvan-media

Daily autoposter for the Instagram account sanjeev_gulia. Every day at 18:00 Lagos time (17:00 UTC) a GitHub
Actions job publishes one set in three formats: a swipeable post, a Reel with music, and a Story.
Waypoint and ScoreMyBiz alternate by date. Design: `docs/superpowers/specs/2026-10-10-daily-autoposter-design.md`.

## How a day works
1. `engine/select_item.py` picks the app (alternating) and the next item in that app's bank.
2. `engine/lint.py` rejects items that break the guardrails (invented numbers, Waypoint privacy or safety claims,
   promises). A rejected item is skipped and the next one is tried, up to five times.
3. `engine/render.py` draws the slides and the video; `engine/music.py` writes an original track.
4. Media is committed under `out/YYYY-MM-DD/`, then fetched back from raw.githubusercontent.com to confirm it is live.
5. `engine/instagram.py` prepares every container and only publishes when all three are ready.
6. The result is appended to `logs/posts.jsonl`. A second run on the same date does nothing.

## LinkedIn
Once a week, on Tuesdays (`linkedin_weekday` in content/apps.json), after Instagram publishes, that day's slides go to the founder's personal LinkedIn profile as one swipeable post
(`engine/linkedin.py`). The text carries the Play Store URL as a clickable link. It runs only when the secrets
`LINKEDIN_ACCESS_TOKEN` and `LINKEDIN_PERSON_URN` exist. A LinkedIn failure never affects Instagram: the run exits 1
(you get an email) and a re-run retries only LinkedIn. The token lasts about 60 days and cannot be refreshed by a
program. A weekly check warns from day 50 using the variable `LINKEDIN_TOKEN_DATE`. To log in again, run
`python3 -m engine.linkedin_auth` in this folder on your Mac, press Allow, and it stores everything.
One-time setup: create the app at linkedin.com/developers (products: Share on LinkedIn, Sign In with LinkedIn using
OpenID Connect), add redirect URL `http://localhost:3000/callback`, put the client id and secret in
`~/arthvan-social/.env`.

## Threads
Every day, after Instagram, the same slides go to the founder's Threads profile (sanjeev_gulia) as one carousel with
up to 500 characters of text and the clickable Play Store link (`engine/threads.py`). Runs only when the secrets
`THREADS_ACCESS_TOKEN` and `THREADS_USER_ID` exist. Failure is isolated like LinkedIn; a re-run retries only Threads.
The token lasts 60 days and is refreshed by the weekly job. Setup: a Meta app with the Threads use case, your account
as Threads Tester (accept under Threads app > Settings > Account > Website permissions), token from the dashboard.

## Pause, run, inspect
- Pause everything: set the repository variable `PAUSE` to `1` (Settings, Secrets and variables, Variables), or add a file named `PAUSE`.
- Manual run: Actions, daily-post, Run workflow. `render` only draws, `prepare` does everything except publish, `post` publishes.
- If a run fails GitHub emails the repository owner. Read the run log; no secret is ever printed.
- Instagram's API cannot delete posts. Remove a post in the app.

## Secrets
Repository secrets `IG_ACCESS_TOKEN` and `IG_USER_ID`. The token lasts 60 days (created 2026-10-10, expires about
2026-12-09). `refresh-token` runs weekly; if Instagram ever returns a different token it fails so you know to
generate a new one in the Meta developer dashboard (app Arthvan Daily Poster, Instagram API setup) and update the secret.

## Content
`content/waypoint.json` and `content/scoremybiz.json` hold the item banks (20 each, so about 40 days before repeats).
`content/apps.json` holds Play Store links, palettes, allowed numbers and banned phrases. Run `python -m pytest -q`
after editing; the tests lint every item. Facts only; sample figures need `"sample": true`.

## Known limits
Captions cannot contain clickable links (Instagram rule), so every caption says "Link in bio" and shows the Play URL as text.
GitHub disables scheduled workflows after 60 days without repository activity; the daily commits keep it active.

## Story ads (characters)
Lumi (ScoreMyBiz), Mira (Waypoint) and the founder (suit for ScoreMyBiz, casual for Waypoint) are Pixar-style images the
founder makes in the Gemini app; cut-outs live in `engine/assets/characters/`. `python -m engine.mouth` builds the aligned
talking-head frames; `python -m engine.story stories/<id>.json <out>` renders a story on the Mac (voices are macOS `say`).
A story with `post_on` and its MP4 in `stories/out/` replaces that day's post: Instagram Reel + Story, LinkedIn native video.

Before writing any new script: re-capture the app screens from the latest build (`store/capture_scoremybiz.py <lang> <dir>`,
`store/capture_waypoint.py <dir>`), read the app repos' recent commits for new features, and keep screens in the ad's language.

## Ad radar (competitors)
Every Monday the weekly report also runs `radar/collect.py` (public Play listings + newest YouTube videos for the apps in
`radar/watchlist.json`) and `radar/report.py` (theme counts, who pushes what, changes since last week, suggested themes).
No Meta scraping, no paid data. Snapshots in `radar/snapshots/`, reports in `radar/reports/`. Add competitors by editing the watch list.

## YouTube Shorts
Every day's Reel (and every story ad) also uploads as a public Short to the channel mapped to that app:
ScoreMyBiz → SGLearning, Waypoint → Arthvan (ex SGMythWorld). Needs secrets `YT_CLIENT_ID`, `YT_CLIENT_SECRET` and
`YT_<APP>_REFRESH_TOKEN`, created once with `python -m engine.youtube_auth scoremybiz|waypoint` (browser consent, choose
the channel). Title gets "#Shorts", description carries the Play link (clickable on YouTube). One quota unit per upload
of the 10,000 daily allowance. A YouTube failure never affects the other channels; a re-run retries YouTube only.

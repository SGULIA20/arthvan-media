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

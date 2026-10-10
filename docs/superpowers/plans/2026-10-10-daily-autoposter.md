# Daily Autoposter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** Publish one Instagram set (swipeable post, Reel, Story) every day at 17:00 UTC, alternating Waypoint and ScoreMyBiz, with no human step.

**Architecture:** Python engine run by a GitHub Actions cron. Pure functions (select, lint, captions) are unit tested; Playwright and ffmpeg render media; an Instagram client prepares all containers before publishing any.

**Tech Stack:** Python 3.12, numpy, playwright (chromium), ffmpeg, GitHub Actions, Instagram API with Instagram Login (graph.instagram.com v25.0), pytest.

**Spec:** docs/superpowers/specs/2026-10-10-daily-autoposter-design.md

## Global Constraints
- Run time 17:00 UTC (18:00 Lagos, UTC+1, no DST). The set date is the Lagos calendar date.
- Apps alternate by date; epoch 2026-10-11 is Waypoint, next day ScoreMyBiz.
- Reel and Story: 1080x1920, 30 fps, H.264 + AAC, 15 to 30 seconds. Post slides: 1080x1350 baseline JPEG.
- Captions end with the app's Play Store link and "Link in bio". Links: ScoreMyBiz https://play.google.com/store/apps/details?id=com.scoremybiz.app, Waypoint https://play.google.com/store/apps/details?id=com.arthvananalytics.waypoint
- Secrets only IG_ACCESS_TOKEN and IG_USER_ID. Token never printed or logged.
- Waypoint banned phrases and the digit rule are enforced by lint (spec, Guardrails).
- Nothing becomes public unless post, Reel and Story containers are all FINISHED.

## Review Focus
- Run lands near midnight UTC: date must come from Lagos time, so 23:30 UTC belongs to the next Lagos date.
- Workflow reruns the same day: second run must publish nothing.
- First item in the bank fails lint: the next item is used; if all five tried fail, exit non-zero without posting.
- One container errors during preparation: nothing is published.
- Raw GitHub URL not yet serving the new file: retry, then fail without posting.
- ffmpeg or Chromium missing or output invalid (no audio, wrong size, blank frames): fail before any Instagram call.

## File Structure
- engine/config.py: load apps.json and banks, validate item shape.
- engine/select_item.py: date to app and item.
- engine/lint.py: guardrails and caption building.
- engine/music.py: numpy track synthesis, m4a export.
- engine/render.py + engine/templates/deck.html: slides and video.
- engine/instagram.py: API client.
- engine/run_daily.py: orchestrator, git helper, idempotency log.
- content/apps.json, content/waypoint.json, content/scoremybiz.json.
- .github/workflows/daily-post.yml, refresh-token.yml. tests/ mirrors engine/.

### Task 1: Config and item schema
**Files:** Create engine/config.py, content/apps.json, tests/test_config.py
**Interfaces:** Produces `load_apps() -> dict[str, dict]`, `load_bank(app: str) -> list[dict]`, `validate_item(item: dict) -> list[str]` (empty list means valid). An item has `id`, `template` (one of "ink", "dusk", "spark"), `caption` (str), `hashtags` (list), `slides` (3 to 6 dicts with `kind` in hook, stat, bars, steps, quote and `text`/`sub`/`rows`/`items` fields, optional `sample: true`).
- [ ] Test: `test_validate_item_flags_missing_fields` (item without slides returns a message mentioning "slides"); `test_load_apps_has_both_apps_with_play_urls` (both Play links from Global Constraints).
- [ ] Run tests, expect FAIL; implement; expect PASS; commit.

### Task 2: Selection
**Files:** Create engine/select_item.py, tests/test_select.py
**Interfaces:** Consumes Task 1. Produces `lagos_date(now_utc: datetime) -> date`, `pick(day: date, banks: dict[str, list], skip: int = 0) -> Selection(app, item, bank_index)`; `skip` advances within the app's bank for lint fallback.
- [ ] Tests: alternation (2026-10-11 waypoint, 10-12 scoremybiz, 10-13 waypoint); same input same output; bank wrap-around; `lagos_date(2026-10-11T23:30Z) == 2026-10-12`; `skip=1` returns the next item.
- [ ] Run, FAIL, implement, PASS, commit.

### Task 3: Lint and captions
**Files:** Create engine/lint.py, tests/test_lint.py
**Interfaces:** Produces `lint_item(app_cfg: dict, item: dict) -> list[str]` and `build_captions(app_cfg: dict, item: dict) -> tuple[str, str]` (post caption, reel caption).
- [ ] Tests: Waypoint item containing "nobody can see you" fails; "secure" fails; a digit outside the allowlist fails unless the slide has `sample: true`; a sample slide adds the money disclaimer to both captions; both captions end with the Play link line and contain "Link in bio"; caption length under 2200 characters; at most 5 hashtags.
- [ ] Run, FAIL, implement, PASS, commit.

### Task 4: Content banks
**Files:** Create content/waypoint.json, content/scoremybiz.json, tests/test_banks.py
- [ ] Test: every item in both banks passes `validate_item` and `lint_item`, ids are unique, each bank has at least 20 items, and every `template` value is used at least once per bank.
- [ ] Write 20 items per app from the facts in the spec only; run, PASS, commit.

### Task 5: Music
**Files:** Create engine/music.py, tests/test_music.py
**Interfaces:** Produces `synth(app: str, seed: int, seconds: float, sr: int = 44100) -> np.ndarray` (float32, shape (n, 2), peak at most 0.9) and `write_m4a(samples, path)` via ffmpeg.
- [ ] Tests: deterministic for equal seed; different seeds differ; not silent (RMS above 0.01); no clipping; length equals seconds*sr; app moods differ (tempo field in a returned info dict).
- [ ] Run, FAIL, implement, PASS, commit.

### Task 6: Renderer
**Files:** Create engine/render.py, engine/templates/deck.html, tests/test_render.py
**Interfaces:** Produces `render_set(sel: Selection, app_cfg: dict, out_dir: Path, fps: int = 30) -> RenderedSet(slides: list[Path], reel: Path, story: Path)`; `verify_set(rs) -> list[str]` using ffprobe and pixel statistics.
- [ ] Tests (marked slow): rendering one item per app gives 4:5 JPEG slides, a 1080x1920 H.264 video 15 to 30 seconds with an AAC stream, and `verify_set` returns an empty list; a blank image makes `verify_set` report a problem.
- [ ] Implement deck.html with `render(t)`; generate frames with Playwright; encode with ffmpeg; run, PASS, view frames of both apps, commit.

### Task 7: Instagram client
**Files:** Create engine/instagram.py, tests/test_instagram.py
**Interfaces:** Produces `prepare_set(ig_id, token, urls: SetUrls, captions) -> Prepared`, `publish_set(ig_id, token, prepared) -> dict[str, str]`, `refresh_token(token) -> dict`. HTTP goes through one `call(method, path, token, params)` function that tests replace.
- [ ] Tests with a fake `call`: publish is never called when any container reports ERROR; publish order is post, reel, story; the token never appears in raised errors.
- [ ] Run, FAIL, implement, PASS, commit.

### Task 8: Orchestrator
**Files:** Create engine/run_daily.py, tests/test_run_daily.py
**Interfaces:** Consumes Tasks 1 to 7. Produces CLI `python -m engine.run_daily --mode render|prepare|post [--date YYYY-MM-DD]`, `already_posted(log_path, day) -> bool`, `wait_for_urls(urls, timeout_s) -> None`.
- [ ] Tests with fakes: second run same date posts nothing; lint failure falls back to the next item, five failures exit 1; PAUSE=1 exits 0 without rendering; URL wait timeout raises before any Instagram call.
- [ ] Run, FAIL, implement (commit and push out/YYYY-MM-DD, prune folders older than 14 days, append logs/posts.jsonl), PASS, commit.

### Task 9: Workflows
**Files:** Create .github/workflows/daily-post.yml, .github/workflows/refresh-token.yml, README.md
- [ ] daily-post: cron `0 17 * * *`, dispatch input mode, concurrency group, `permissions: contents: write`, installs numpy and playwright, runs tests, then `python -m engine.run_daily`.
- [ ] refresh-token: weekly cron; fails if the returned token differs from the stored one.
- [ ] Verify both parse as YAML and contain the cron lines.

### Task 10: Go live and verify
- [ ] Set secrets IG_ACCESS_TOKEN and IG_USER_ID from the local .env without printing them.
- [ ] Push; dispatch daily-post with mode render, then mode prepare; both must succeed.
- [ ] Run the full local test suite and a code review of the branch diff; record results in README.

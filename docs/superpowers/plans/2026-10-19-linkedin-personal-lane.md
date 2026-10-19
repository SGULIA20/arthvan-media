# LinkedIn Personal Lane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Post one short, hand-written, picture-backed LinkedIn post a day to the founder's profile, and answer `/comment <post>` on Telegram with two comment drafts.

**Architecture:** A JSON bank + a lane module (`engine/linkedin_personal.py`: lint, pick, text, render, run) reusing `engine/linkedin.py` for the API, `engine/run_daily.git_publish` for the log, `engine/notify.send` for Telegram. A new workflow runs it daily. Comment drafts are a thin Gemini wrapper wired into `engine/tg_commands.answer`.

**Tech Stack:** Python 3.12, Playwright Chromium, ffmpeg, pytest, GitHub Actions.

**Spec:** docs/superpowers/specs/2026-10-19-linkedin-personal-lane-design.md

## Global Constraints
- English only; no numbers unless the item has a `facts` note; global `banned_phrases` apply; no em-dash anywhere in post text.
- 3 to 5 hashtags including `#SGLearning`; hook ≤ 120 chars; body ≤ 900; whole post ≤ 1300.
- Picture 1080 x 1350 JPEG; fonts from `engine/fonts`; one accent per pillar.
- Log channel name `linkedin_personal`; never two posts on one day; PAUSE honoured.
- Waypoint never on LinkedIn (unchanged).

## Review Focus
- A re-run after a successful post must print "already posted" and exit 0 (Task 4 test).
- A bank with every item used must still pick (least recent) and not crash (Task 2 test).
- `/comment` with no text must answer with usage, not call Gemini (Task 6 test).
- Multi-image carousel with one slide must fall back to single-image, with 7 slides lint must refuse (Task 1 + 3 tests).
- Reserved LinkedIn characters in hooks (parentheses, colons) must be escaped: `commentary()` already does it (Task 3 test asserts the escape).

---

### Task 1: Bank + lint
**Files:** Create `content/linkedin_personal.json`, `engine/linkedin_personal.py`; Test `tests/test_linkedin_personal.py`.
**Produces:** `load_personal(root=ROOT) -> dict` (`{"settings","items"}`), `lint_personal(item, settings) -> list[str]`, `PILLARS = ("model","finance","ai","world","founder")`.
- [ ] Tests: `test_every_bank_item_passes_lint`, `test_lint_refuses_digits_without_facts`, `test_lint_refuses_em_dash_and_six_hashtags`, `test_lint_refuses_seven_slides`, `test_bank_ids_unique_and_pillars_rotate` (no two consecutive items share a pillar).
- [ ] Run: `pytest tests/test_linkedin_personal.py -q` → FAIL (module missing).
- [ ] Implement module + write 45 items in the founder's voice.
- [ ] Run → PASS. Commit `feat: LinkedIn personal lane bank + lint`.

### Task 2: Selection and text
**Produces:** `used_ids(log: Path) -> list[str]` (published linkedin_personal ids, oldest first), `pick(day, items, log) -> dict`, `build_text(item, settings) -> tuple[str, list]`, `alt_text(card) -> str`.
- [ ] Tests: `test_pick_takes_first_unused_in_bank_order`, `test_pick_wraps_to_least_recent_when_all_used`, `test_build_text_is_hook_body_question_and_tags_with_sglearning_last`.
- [ ] Implement; run → PASS. Commit.

### Task 3: Picture + API
**Files:** Create `engine/templates/linkedin_card.html`; Modify `engine/linkedin.py` (add `create_single_image_post(token, author_urn, text, image_urn, alt) -> str`, `post_images(token, person_urn, text, tags, paths, alts) -> str`); `engine/linkedin_personal.py: render_cards(item, out_dir) -> list[Path]` (slow test, marked).
- [ ] Tests in `tests/test_linkedin.py`: `test_single_image_post_uses_media_content`, `test_post_images_picks_single_or_multi`. In `tests/test_linkedin_personal.py`: `test_render_cards_makes_one_jpeg_per_card` (marked slow, checks 1080x1350 via render.verify_image).
- [ ] Implement; run → PASS. Render one card locally and look at it. Commit.

### Task 4: run() + CLI
**Produces:** `run(mode, day, *, root, env, deps) -> int`; `Deps` dataclass (post_images, render_cards, git_publish, notify) for tests; `python -m engine.linkedin_personal [render|prepare|post] [--date]`.
- [ ] Tests: `test_post_logs_published_and_notifies`, `test_second_run_same_day_is_a_noop`, `test_pause_stops_posting`, `test_failed_post_logs_failed_and_returns_1`, `test_prepare_renders_but_never_posts`.
- [ ] Implement; run → PASS. Commit.

### Task 5: Workflow
**Files:** Create `.github/workflows/linkedin-personal.yml`; Test `tests/test_workflows.py`.
- [ ] Test: `test_linkedin_personal_runs_at_09_07_india_and_defaults_to_render`.
- [ ] Implement (mirror daily-post.yml: checkout main, python 3.12, ffmpeg, pip, chromium, unit tests, git identity, PAUSE from vars, secrets LINKEDIN_*, TELEGRAM_*). Run → PASS. Commit.

### Task 6: Comment drafts on Telegram
**Files:** Create `engine/comment_drafts.py` (`drafts(post_text, *, ask=gemini.ask) -> str`), Modify `engine/tg_commands.py` (`/comment`, HELP), `.github/workflows/telegram-commands.yml` (GEMINI_API_KEY env); Tests `tests/test_comment_drafts.py`, `tests/test_tg_commands.py`.
- [ ] Tests: `test_prompt_carries_voice_rules_and_post`, `test_empty_post_returns_usage_without_asking`, `test_comment_command_replies_with_drafts`, `test_gemini_failure_is_a_friendly_message`.
- [ ] Implement; run → PASS. Commit.

### Task 7: Verify and hand over
- [ ] `python -m pytest -q -m "not slow"` all green; `python -m engine.linkedin_personal prepare` on the Mac; look at the picture; code-review the diff; update memory; give the founder the push + first-run steps.

# LinkedIn personal lane: design (19 Oct 2026)

## What the founder asked for
One short LinkedIn post a day on his personal profile, in English, in the style of his own picture posts of
July to September 2026 (frameworks, theories, models, MBA and CIMA learnings, business stories, geography and
India facts, founder notes, AI for finance teams), each with a picture that belongs to the post and 3 to 5
relevant hashtags. Posts must stay small. Comments on other people's posts stay manual: he pastes a post, the
bot answers with comment drafts in his voice.

## Facts that shape the design (probed 19 Oct with the live token)
- The LinkedIn token has `openid profile w_member_social`: it can create posts but cannot read his posts, his
  feed, or comments (every read returned 403). Liking or commenting on the feed through the API is therefore
  impossible; browser bots are out (terms of service, account restriction while he is job hunting).
- His old posts are not on this Mac; he pasted nine of them in chat. They are now the voice reference in
  `~/.claude/skills/linkedin-writer/references/sample-posts.md`.
- The engine already posts to LinkedIn (`engine/linkedin.py`: images, multi-image, video) and runs on
  GitHub Actions with Playwright Chromium, ffmpeg, Telegram and Gemini available.

## Design
**Bank, not a generator.** `content/linkedin_personal.json` holds hand-written items (45 at launch, five
pillars in rotation: `model`, `finance`, `ai`, `world`, `founder`). Every item: `id`, `pillar`, `hook`,
`body`, `question`, `hashtags`, `card` (picture spec) and optional `slides` (2 to 6 cards = a swipeable
carousel), optional `facts` note that permits digits. No Gemini text in the post path: nothing invented goes out.

**Lint before posting** (`engine/linkedin_personal.py: lint_personal`): global banned phrases, digits only
with a `facts` note, hook at most 120 characters, body at most 900, whole post at most 1300, question ends
with "?", 3 to 5 hashtags including `#SGLearning`, no em-dash, card title at most 60 characters, at most 5
points of at most 70 characters, unique ids.

**Selection** (`pick`): items go out in bank order; an item is "used" once `logs/posts.jsonl` has a
published `linkedin_personal` entry with its id. When all are used the least recently used one goes first.
One post a day at most; `PAUSE` (file or variable) stops it like everything else.

**Picture** (`render_cards`): Playwright renders `engine/templates/linkedin_card.html` at 1080 x 1350 per
card: pillar label, title, up to five points, "Sanjeev Gulia · SG Learning" footer, one accent colour per
pillar, the repo's Inter and Plex fonts. One card = single-image post; `slides` = multi-image post.

**Posting** (`engine/linkedin_personal.py: run(mode, day)`): modes `render`, `prepare`, `post`. `post`
logs `{"date","channel":"linkedin_personal","item","status","id"}` to `logs/posts.jsonl`, commits and pushes
the log like the daily set, and sends one Telegram line with the post link. A failure is logged with
`status: failed` and the error text; the workflow fails loudly (GitHub emails him).

**Schedule** `.github/workflows/linkedin-personal.yml`: cron `37 3 * * *` (09:07 India, 04:37 Lagos; the
audience is 87% India) with a `37 4 * * *` safety net; the engine never posts twice on one day.
`workflow_dispatch` with mode defaulting to `render`.

**Comment drafts** (`engine/comment_drafts.py`, Telegram `/comment <pasted post>`): Gemini flash-lite writes
two comments in his voice (under 60 words, specific, one adds his experience, one asks a question, no
"Great post", no em-dash). Reply within the 5-minute command poll. He pastes the one he likes by hand.

**Not built:** auto likes, auto comments, reading his LinkedIn, Waypoint on LinkedIn (his 19 Oct rule), PDF
document carousels (multi-image posts give the swipe already).

## Done means
Tests pass (`python -m pytest -q -m "not slow"`), one card rendered locally and looked at, a `prepare` run
on the Mac shows the exact text and picture for tomorrow, the workflow file validates. The founder pushes.

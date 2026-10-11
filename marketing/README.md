# Marketing packs

One folder per product, month and platform. Every asset carries product, date, country-language, platform and
campaign in its name. Captions per platform live in Captions/, storyboards in Storyboards/, performance notes in
Performance/. `campaign-register.csv` is the running register; results stay "unknown" until a platform reports them.

Status words: DRAFT · READY FOR REVIEW · APPROVED · SCHEDULED · PUBLISHED · PERFORMANCE REVIEWED.
Packs here are never published by the autoposter. A pack is published only after the founder approves it.
Assets are rendered by engine/render.py from content/*.json items (the editable source); re-render instead of editing exports.

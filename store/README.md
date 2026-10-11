# Store assets pipeline

`render_store.py <app> <shots_dir> <plan.json>` turns raw phone screenshots into framed Play Store
screenshots (1080×1920) and a feature graphic (1024×500) using `templates/frame.html` and `templates/feature.html`.
Palettes come from `../content/apps.json`.

Raw screens:
- ScoreMyBiz: `capture_scoremybiz.py` runs against the app in web mode (`EXPO_PUBLIC_FOUNDER_KEY=sg2026 npx expo start --web --port 8091`
  in ~/ScoreMyBizMobile) with backend calls routed to the local functions server
  (`FOUNDER_KEY=sg2026 SUPABASE_URL=https://example.supabase.co SUPABASE_SERVICE_ROLE_KEY=dummy npx netlify-cli functions:serve --port 9999`
  in ~/Downloads/scoremybiz). The founder sample data never touches the database.
- Waypoint: `capture_waypoint.py` against `npx expo start --web --port 8092` in ~/waypoint.

Outputs in `out/<app>/`; paste-ready text in `LISTING-<app>.md`.

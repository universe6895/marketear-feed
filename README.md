# MarketEar Daily Feed

Public daily content feed for the personal MarketEar iOS app.

- `today.json` is read by the app at launch and cached locally.
- The scheduled workflow selects the newest unused Bloomberg Television
  “Markets in 3 Minutes” / “3-Minutes MLIV” episode.
- If Bloomberg has not published a new episode that day, the workflow searches
  backward through the official channel archive. `history.json` prevents daily
  repeats and is maintained automatically.
- YouTube remains the video host. This repository does not download or
  redistribute the video.
- English text and timestamps come from the configured transcript API.
- Professional Chinese is generated from the complete article with GitHub
  Models, using the workflow's built-in `GITHUB_TOKEN` and free allowance.
- Apple Translation on the iPhone remains a fallback if model translation is
  temporarily unavailable.

## Repository secret

Configure `YOUTUBE_TRANSCRIPT_API_KEY` under:

`Settings → Secrets and variables → Actions`

The secret is only read by GitHub Actions and must never be committed.

## Manual run

Open `Actions → Build daily MarketEar feed → Run workflow`. An optional YouTube
video ID can be supplied when a specific 2–3 minute Bloomberg video is selected.

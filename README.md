# MarketEar Daily Feed

Public daily content feed for the personal MarketEar iOS app.

- `today.json` is read by the app at launch and cached locally.
- The scheduled workflow selects the latest Bloomberg Television video titled
  “Markets in 3 Minutes”.
- YouTube remains the video host. This repository does not download or
  redistribute the video.
- English text and timestamps come from the configured transcript API.
- Chinese paragraph translations are generated on the iPhone with Apple
  Translation and stored locally.

## Repository secret

Configure `YOUTUBE_TRANSCRIPT_API_KEY` under:

`Settings → Secrets and variables → Actions`

The secret is only read by GitHub Actions and must never be committed.

## Manual run

Open `Actions → Build daily MarketEar feed → Run workflow`. An optional YouTube
video ID can be supplied when a specific 2–3 minute Bloomberg video is selected.

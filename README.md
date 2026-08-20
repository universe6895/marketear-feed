# MarketEar Daily Feed

Public daily content feed for the personal MarketEar iOS app.

- `today.json` is read by the app at launch and cached locally.
- The scheduled workflow selects the newest recent Bloomberg Television
  “Markets in 3 Minutes” / “3-Minutes MLIV” episode with an existing English
  YouTube caption track. On a quiet day it rotates a recent captioned episode.
- YouTube remains the video host. This repository does not download or
  redistribute the video.
- English text and timestamps come from an existing YouTube caption track via
  YouTubeTranscript.dev. Supadata native-caption mode can be configured as the
  primary provider; audio ASR is deliberately not used in the automatic feed.
- Professional Chinese is generated from the complete article with Cloudflare
  Workers AI. Its free plan includes a daily allocation suitable for one short
  MarketEar article.
- Every sentence is translated independently and bound by its immutable ID.
  A candidate is published only after caption, timeline and 100% Chinese
  coverage checks pass. Failed runs leave the previous `today.json` untouched.
- Apple Translation on the iPhone remains a separate optional translation.

## Repository secret

Configure these secrets under:

`Settings → Secrets and variables → Actions`

- `YOUTUBE_TRANSCRIPT_API_KEY`
- `SUPADATA_API_KEY` (optional native-caption provider)
- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_API_TOKEN`

The secret is only read by GitHub Actions and must never be committed.

## Manual run

Open `Actions → Build daily MarketEar feed → Run workflow`. An optional YouTube
video ID can be supplied when a specific 2–3 minute Bloomberg video is selected.

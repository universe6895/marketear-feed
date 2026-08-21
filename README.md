# MarketEar Daily Feed

Public daily content feed for the personal MarketEar iOS app.

- `today.json` is read by the app at launch and cached locally.
- The scheduled workflow selects the newest recent Bloomberg Television
  “Markets in 3 Minutes” / “3-Minutes MLIV” episode with an existing English
  YouTube caption track. On a quiet day it rotates a recent captioned episode.
- YouTube remains the video host. This repository does not download or
  redistribute the video.
- English text and timestamps come from an existing YouTube caption track via
  YouTubeTranscript.dev as the proven primary provider. Supadata `native` mode
  is the fallback. Audio ASR is deliberately not used in the automatic feed.
- Professional Chinese uses the fixed Google Cloud Translation Advanced
  `general/translation-llm` model. A required contextual glossary locks
  domain terminology without allowing a general chat model to add commentary.
- Every Chinese sentence remains bound by position to its immutable English
  sentence ID. A candidate is published only after caption, timeline, numeric,
  financial-terminology and 100% Chinese coverage checks pass. Failed runs
  leave the previous `today.json` untouched.
- Apple Translation on the iPhone remains a separate optional translation.

## Repository secret

Configure these secrets under:

`Settings → Secrets and variables → Actions`

- `YOUTUBE_TRANSCRIPT_API_KEY`
- `SUPADATA_API_KEY` (optional native-caption provider)
- `GCP_TRANSLATION_SERVICE_ACCOUNT_JSON`

Required repository variable:

- `GOOGLE_TRANSLATION_GLOSSARY_ID` (for example `marketear-finance-en-zh`)

The version-controlled unidirectional glossary source is
`config/finance_glossary_en_zh.csv`. Upload it to Cloud Storage and create an
English → Simplified Chinese glossary in `us-central1`; then set the repository
variable to its glossary ID. The production workflow refuses to publish without
this variable, enables Translation LLM's contextual glossary mode, and fails
closed if required financial terminology or numeric values are lost.

The secret is only read by GitHub Actions and must never be committed.

## Manual run

Open `Actions → Build daily MarketEar feed → Run workflow`. An optional YouTube
video ID can be supplied when a specific 2–3 minute Bloomberg video is selected.

# MarketEar Feed

The iPhone reads the published Bloomberg feed on manual refresh. Prepare new
Bloomberg and Joseph Wang documents on a trusted Mac. The workflow in this
branch is a manual, read-only check of the existing caption credential. It
does not generate or publish content.

## Prepare one video

The shared processor uses DeepSeek's official API and the existing
`config/finance_glossary_en_zh.csv`. It accepts `DEEPSEEK_API_KEY` from the local
process environment or the existing Mac Keychain service `deepseek-api-key`.
It checks the model and balance first. Caption access uses the local
`YOUTUBE_TRANSCRIPT_API_KEY`, or `SUPADATA_API_KEY` when explicitly selecting
`--provider supadata`. Keep credentials in the trusted environment.

```sh
python3 scripts/prepare_deepseek.py --check
python3 scripts/prepare_deepseek.py --video VIDEO_ID --source wang --output wang.json
python3 scripts/prepare_deepseek.py --video VIDEO_ID --source bloomberg --output candidate.json
```

For Wang, give `--duration SECONDS` when the video's duration is known to
check coverage before translating. You can also supply a verified existing
English track with `--track TRACK.json` and skip provider extraction. The
track must contain the selected `videoId` and integer-millisecond
`segments` with `start`, `end` and `text`. Copy the resulting Wang JSON
to Files and import it from the same video's page.

For Bloomberg, you can pass an existing English candidate with
`--bloomberg ENGLISH.json` instead of `--video`. Review the result and
then use the existing feed validation and publishing procedure:

```sh
python3 scripts/publish_feed.py --candidate candidate.json --output today.json --last-good last_good.json --history history.json
```

The publish script validates the candidate and updates local feed files.
Review the resulting diff before publishing those files to the feed.

The Mac ledger in `~/Library/Application Support/MarketEar Preparation/`
retains existing source tracks, translation versions, and usage. A pending
request with unknown outcome is not retried automatically. The ledger
pre-reserves the maximum estimated charge at DeepSeek's official peak
rate and enforces a cumulative CNY 2 limit. Successful reuse of an
identical video, track, and rules version returns its saved translation.

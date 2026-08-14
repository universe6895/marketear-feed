#!/usr/bin/env python3
"""Build MarketEar's public daily JSON from a Bloomberg YouTube transcript."""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


CHANNEL_ID = "UCIALMKvObZNtJ6AmdCLP7Lg"
RSS_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"
CHANNEL_VIDEOS_URL = f"https://www.youtube.com/channel/{CHANNEL_ID}/videos"
CHANNEL_SEARCH_URL = (
    f"https://www.youtube.com/channel/{CHANNEL_ID}/search?query=Markets%20in%203%20Minutes"
)
WHISPER_MODEL = "@cf/openai/whisper-large-v3-turbo"
SERIES_TITLE = re.compile(
    r"(?:markets?\s+in\s+3\s+minutes|3[-\s]minutes?\s+mliv)",
    re.IGNORECASE,
)

FINANCE_TERMS = [
    ("interest rate", "/ˈɪntrəst reɪt/", "利率"),
    ("Federal Reserve", "/ˈfedərəl rɪˈzɜːrv/", "美国联邦储备委员会"),
    ("Treasury yield", "/ˈtreʒəri jiːld/", "美国国债收益率"),
    ("bond market", "/bɒnd ˈmɑːrkɪt/", "债券市场"),
    ("equity market", "/ˈekwəti ˈmɑːrkɪt/", "股票市场"),
    ("valuation", "/ˌvæljuˈeɪʃən/", "估值"),
    ("earnings", "/ˈɜːrnɪŋz/", "企业盈利"),
    ("inflation", "/ɪnˈfleɪʃən/", "通货膨胀"),
    ("recession", "/rɪˈseʃən/", "经济衰退"),
    ("economic growth", "/ˌekəˈnɒmɪk ɡrəʊθ/", "经济增长"),
    ("labor market", "/ˈleɪbər ˈmɑːrkɪt/", "劳动力市场"),
    ("unemployment", "/ˌʌnɪmˈplɔɪmənt/", "失业；失业率"),
    ("rate cut", "/reɪt kʌt/", "降息"),
    ("rate hike", "/reɪt haɪk/", "加息"),
    ("monetary policy", "/ˈmʌnɪteri ˈpɒləsi/", "货币政策"),
    ("fiscal policy", "/ˈfɪskəl ˈpɒləsi/", "财政政策"),
    ("stock market", "/stɒk ˈmɑːrkɪt/", "股票市场"),
    ("S&P 500", "/ˌes ən ˌpiː faɪv ˈhʌndrəd/", "标普500指数"),
    ("market rally", "/ˈmɑːrkɪt ˈræli/", "市场上涨行情"),
    ("sell-off", "/ˈsel ɒf/", "市场抛售"),
    ("volatility", "/ˌvɒləˈtɪləti/", "波动性"),
    ("investor", "/ɪnˈvestər/", "投资者"),
    ("commodity", "/kəˈmɒdəti/", "大宗商品"),
    ("crude oil", "/kruːd ɔɪl/", "原油"),
    ("currency", "/ˈkʌrənsi/", "货币；汇率相关资产"),
]


def is_markets_in_three_minutes(title: str, duration: object = None) -> bool:
    if not SERIES_TITLE.search(title):
        return False
    if duration in (None, ""):
        return True
    try:
        seconds_long = float(duration)
    except (TypeError, ValueError):
        return True
    return 90 <= seconds_long <= 240


def recent_rss_candidates() -> list[tuple[str, str]]:
    request = urllib.request.Request(RSS_URL, headers={"User-Agent": "MarketEarFeed/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        root = ET.fromstring(response.read())

    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
    }
    entries: list[tuple[str, str]] = []
    for entry in root.findall("atom:entry", ns):
        video_id = (entry.findtext("yt:videoId", default="", namespaces=ns) or "").strip()
        title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
        if video_id and title:
            entries.append((video_id, title))

    return [item for item in entries if is_markets_in_three_minutes(item[1])]


def channel_candidates() -> list[tuple[str, str]]:
    """Return official Bloomberg episodes, newest uploads first then older search hits."""
    try:
        from yt_dlp import YoutubeDL
    except ImportError as error:
        raise RuntimeError("yt-dlp is not installed for historical video discovery") from error

    options = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "playlistend": 500,
        "socket_timeout": 30,
        "retries": 3,
    }
    proxy = os.environ.get("YTDLP_PROXY", "").strip()
    if proxy:
        options["proxy"] = proxy
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    with YoutubeDL(options) as downloader:
        for url in (CHANNEL_VIDEOS_URL, CHANNEL_SEARCH_URL):
            result = downloader.extract_info(url, download=False)
            for entry in result.get("entries") or []:
                video_id = str(entry.get("id") or "").strip()
                title = clean_text(str(entry.get("title") or ""))
                channel_id = str(entry.get("channel_id") or "").strip()
                if not video_id or video_id in seen or not title:
                    continue
                if channel_id and channel_id != CHANNEL_ID:
                    continue
                if not is_markets_in_three_minutes(title, entry.get("duration")):
                    continue
                seen.add(video_id)
                candidates.append((video_id, title))
    return candidates


def read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def used_video_ids(output: Path, history: Path) -> list[str]:
    stored = read_json(history)
    values = stored.get("usedVideoIDs", []) if isinstance(stored, dict) else []
    used = [str(value) for value in values if str(value).strip()]

    current = read_json(output)
    if isinstance(current, dict):
        current_id = str(current.get("youtubeVideoID") or "").strip()
        if current_id and current_id not in used:
            used.append(current_id)
    return used


def discover_daily_video(output: Path, history: Path) -> tuple[str, str, list[str]]:
    used = used_video_ids(output, history)
    candidates: list[tuple[str, str]] = []
    errors: list[str] = []

    try:
        candidates.extend(channel_candidates())
    except Exception as error:
        errors.append(f"channel archive: {error}")

    try:
        rss_candidates = recent_rss_candidates()
        known = {video_id for video_id, _ in candidates}
        candidates.extend(item for item in rss_candidates if item[0] not in known)
    except Exception as error:
        errors.append(f"RSS: {error}")

    if not candidates:
        detail = "; ".join(errors) or "no matching official videos"
        raise RuntimeError(f"Could not discover a Bloomberg 3-minute market video ({detail})")

    used_set = set(used)
    for video_id, title in candidates:
        if video_id not in used_set:
            return video_id, title, used

    # The archive currently contains hundreds of episodes, so this is only an
    # emergency rotation rule. It keeps the daily feed alive if every discovered
    # item has eventually been used, while avoiding yesterday's video when possible.
    current = used[-1] if used else ""
    for video_id, title in reversed(candidates):
        if video_id != current:
            print("All discovered episodes were previously used; rotating the oldest one")
            return video_id, title, used
    return candidates[0][0], candidates[0][1], used


def write_history(path: Path, used: list[str], video_id: str) -> None:
    updated = [item for item in used if item != video_id]
    updated.append(video_id)
    path.write_text(
        json.dumps({"usedVideoIDs": updated}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", html.unescape(value or ""))
    return re.sub(r"\s+", " ", value).strip()


def vtt_seconds(value: str) -> float:
    parts = value.strip().replace(",", ".").split(":")
    if len(parts) == 2:
        hours = 0
        minutes, seconds_value = parts
    elif len(parts) == 3:
        hours, minutes, seconds_value = parts
    else:
        raise ValueError(f"Invalid VTT timestamp: {value}")
    return round(int(hours) * 3600 + int(minutes) * 60 + float(seconds_value), 3)


def normalize_whisper_text(value: str) -> str:
    """Fix high-confidence formatting and finance-name errors without rewriting speech."""
    value = clean_text(value)
    replacements = (
        (r"\bKevin Walsh\b", "Kevin Warsh"),
        (r"\bthese wages at the front end\b", "these wagers at the front end"),
        (r"\bnon\s+-\s+farm\b", "nonfarm"),
        (r"\b(\d+)\s+-\s+year\b", r"\1-year"),
        (r"\b(\d+)\s+\.\s*(\d+)\s*%", r"\1.\2%"),
    )
    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
    return value


def cues_from_vtt(vtt: str) -> list[dict]:
    """Parse Whisper's WebVTT response into timestamped caption fragments."""
    normalized = vtt.replace("\r\n", "\n").replace("\r", "\n").strip()
    cues: list[dict] = []
    for block in re.split(r"\n\s*\n", normalized):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            continue
        timing = lines[timing_index].split("-->")
        if len(timing) != 2:
            continue
        try:
            start = vtt_seconds(timing[0].strip().split()[0])
            end = vtt_seconds(timing[1].strip().split()[0])
        except (TypeError, ValueError):
            continue
        text = normalize_whisper_text(" ".join(lines[timing_index + 1 :]))
        if text and end > start:
            cues.append({
                "id": len(cues) + 1,
                "start": start,
                "end": end,
                "english": text,
                "chinese": "",
            })
    if not cues:
        raise RuntimeError("Whisper returned no usable timestamped VTT cues")
    return cues


def download_youtube_audio(video_id: str, directory: Path) -> tuple[Path, str]:
    try:
        from yt_dlp import YoutubeDL
    except ImportError as error:
        raise RuntimeError("yt-dlp is not installed for audio transcription") from error

    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
        "outtmpl": str(directory / "source.%(ext)s"),
        "socket_timeout": 45,
        "retries": 3,
    }
    proxy = os.environ.get("YTDLP_PROXY", "").strip()
    if proxy:
        options["proxy"] = proxy
    with YoutubeDL(options) as downloader:
        info = downloader.extract_info(
            f"https://www.youtube.com/watch?v={video_id}",
            download=True,
        )
        downloaded = Path(downloader.prepare_filename(info))
    if not downloaded.is_file():
        candidates = [path for path in directory.glob("source.*") if path.is_file()]
        if not candidates:
            raise RuntimeError("yt-dlp did not produce an audio file")
        downloaded = max(candidates, key=lambda path: path.stat().st_size)
    return downloaded, clean_text(str(info.get("title") or ""))


def request_whisper_transcript(
    audio_path: Path,
    account_id: str,
    token: str,
    title: str,
) -> str:
    audio_size = audio_path.stat().st_size
    if audio_size <= 0:
        raise RuntimeError("Downloaded audio file is empty")
    if audio_size > 25 * 1024 * 1024:
        raise RuntimeError(f"Downloaded audio is unexpectedly large ({audio_size} bytes)")

    prompt = (
        "Bloomberg Television financial market commentary. Preserve the exact speaker "
        "wording and add punctuation. Likely terms include Bank of Japan, BOJ, yen, JGB, "
        "US Treasury, Federal Reserve, Kevin Warsh, NFP, nonfarm payrolls, yield curve, "
        "front end, back end, rate wagers, real rates, steepening, and cross-asset. "
        "The policymaker's name is Kevin Warsh. Video title: "
        + title
    )
    payload = {
        "audio": base64.b64encode(audio_path.read_bytes()).decode("ascii"),
        "task": "transcribe",
        "language": "en",
        "vad_filter": True,
        "beam_size": 5,
        "condition_on_previous_text": True,
        "initial_prompt": prompt,
    }
    models_url = (
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{WHISPER_MODEL}"
    )
    request = urllib.request.Request(
        models_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "MarketEarFeed/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=240) as response:
            envelope = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Workers AI Whisper failed ({error.code}): {detail}") from error

    if envelope.get("success") is not True:
        raise RuntimeError(f"Workers AI Whisper returned errors: {envelope.get('errors')}")
    result = envelope.get("result") or {}
    vtt = result.get("vtt") if isinstance(result, dict) else None
    if not isinstance(vtt, str) or "-->" not in vtt:
        raise RuntimeError("Workers AI Whisper returned no timestamped VTT")
    return vtt


def whisper_sentence_cues(
    video_id: str,
    account_id: str,
    token: str,
    title: str,
) -> tuple[list[dict], str]:
    with tempfile.TemporaryDirectory(prefix="marketear-audio-") as temporary:
        audio_path, video_title = download_youtube_audio(video_id, Path(temporary))
        resolved_title = video_title or title
        print(f"Downloaded {audio_path.name} ({audio_path.stat().st_size} bytes) for Whisper")
        vtt = request_whisper_transcript(audio_path, account_id, token, resolved_title)
    cues = sentence_cues(cues_from_vtt(vtt))
    if len(cues) < 5 or cues[-1]["end"] < 60:
        raise RuntimeError("Whisper transcript is unexpectedly short")
    return cues, resolved_title


def sentence_cues(caption_cues: list[dict]) -> list[dict]:
    """Merge caption fragments and split multi-sentence captions into sentences."""
    result: list[dict] = []
    buffered_text = ""
    buffered_start: float | None = None
    buffered_end = 0.0

    for cue in caption_cues:
        text = cue["english"].strip()
        if not text:
            continue

        pieces = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'“‘])", text)
        word_counts = [max(1, len(re.findall(r"\b[\w’'-]+\b", piece))) for piece in pieces]
        total_words = sum(word_counts)
        elapsed_words = 0

        for index, piece in enumerate(pieces):
            piece = piece.strip()
            if not piece:
                continue

            piece_start = cue["start"] + (cue["end"] - cue["start"]) * elapsed_words / total_words
            elapsed_words += word_counts[index]
            piece_end = cue["start"] + (cue["end"] - cue["start"]) * elapsed_words / total_words

            if buffered_start is None:
                buffered_start = piece_start
            buffered_text = f"{buffered_text} {piece}".strip()
            buffered_end = piece_end

            if re.search(r"[.!?][\"'”’]?$", piece):
                result.append({
                    "id": len(result) + 1,
                    "start": round(buffered_start, 3),
                    "end": round(buffered_end, 3),
                    "english": buffered_text,
                    "chinese": "",
                })
                buffered_text = ""
                buffered_start = None

    if buffered_text and buffered_start is not None:
        result.append({
            "id": len(result) + 1,
            "start": round(buffered_start, 3),
            "end": round(buffered_end, 3),
            "english": buffered_text,
            "chinese": "",
        })

    if not result:
        raise RuntimeError("Transcript response contained no complete sentences")
    return result


def vocabulary_for(text: str) -> list[dict]:
    lowered = text.lower()
    matches = []
    for word, phonetic, meaning in FINANCE_TERMS:
        if word.lower() in lowered:
            matches.append({"word": word, "phonetic": phonetic, "meaning": meaning})
    return matches[:8]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", default=os.environ.get("VIDEO_ID", ""))
    parser.add_argument("--title-chinese", default=os.environ.get("TITLE_CHINESE", ""))
    parser.add_argument("--summary", default=os.environ.get("SUMMARY", ""))
    parser.add_argument("--output", default="today.json")
    args = parser.parse_args()

    output = Path(args.output)
    history = output.with_name("history.json")
    feed_title = ""
    used: list[str] = []
    video_id = args.video_id.strip()
    if not video_id:
        video_id, feed_title, used = discover_daily_video(output, history)
        print(f"Selected {video_id}: {feed_title}")
    else:
        used = used_video_ids(output, history)

    cloudflare_account_id = "".join(os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").split())
    cloudflare_token = "".join(os.environ.get("CLOUDFLARE_API_TOKEN", "").split())
    if not cloudflare_account_id or not cloudflare_token:
        raise RuntimeError("Cloudflare Workers AI credentials are not configured")

    cues, video_title = whisper_sentence_cues(
        video_id,
        cloudflare_account_id,
        cloudflare_token,
        feed_title or "Bloomberg Markets in 3 Minutes",
    )
    title = clean_text(video_title or feed_title or "Bloomberg Markets in 3 Minutes")
    source_kind = "cloudflare-whisper-large-v3-turbo"
    print(f"Cloudflare Whisper produced {len(cues)} sentence cues")

    full_text = " ".join(cue["english"] for cue in cues)
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()

    story = {
        "id": f"bloomberg-{video_id}",
        "date": today,
        "eyebrow": "TODAY · BLOOMBERG",
        "title": title,
        "titleChinese": args.title_chinese.strip() or "今日彭博财经市场快讯",
        "summary": args.summary.strip() or "完整英文字幕、逐段时间轴与财经中文翻译。",
        "durationSeconds": cues[-1]["end"],
        "youtubeVideoID": video_id,
        "sourceURL": f"https://www.youtube.com/watch?v={video_id}",
        "sourceName": "Bloomberg Television",
        "vocabulary": vocabulary_for(full_text),
        "transcript": cues,
        "transcriptKind": source_kind,
    }

    output.write_text(json.dumps(story, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_history(history, used, video_id)
    print(f"Wrote {output} with {len(cues)} cues for {video_id}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # GitHub Actions should show a concise failure reason.
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)

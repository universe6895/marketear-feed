#!/usr/bin/env python3
"""Build a candidate MarketEar story from an existing YouTube caption track.

The daily job deliberately does not download YouTube audio. It tries recent
Bloomberg episodes in order and accepts only an English, timestamped caption
track. Publishing is a separate, fail-closed step.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


CHANNEL_ID = "UCIALMKvObZNtJ6AmdCLP7Lg"
RSS_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"
CHANNEL_VIDEOS_URL = f"https://www.youtube.com/channel/{CHANNEL_ID}/videos"
CHANNEL_SEARCH_URL = f"https://www.youtube.com/channel/{CHANNEL_ID}/search?query=Markets%20in%203%20Minutes"
TRANSCRIPT_DEV_URL = "https://www.youtubetranscript.dev/api/v2/transcribe"
SUPADATA_URL = "https://api.supadata.ai/v1/transcript"
MAX_CANDIDATES = 10
SERIES_TITLE = re.compile(
    r"(?:markets?\s+in\s+3\s+minutes|3[-\s]minutes?\s+mliv)",
    re.IGNORECASE,
)


def clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", html.unescape(value or ""))
    value = re.sub(r"\[(?:music|applause)\]", "", value, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", value).strip()


def normalize_caption_text(value: str) -> str:
    """Apply only high-confidence spelling/format fixes; never rewrite speech."""
    value = clean_text(value)
    replacements = (
        (r"\bKevin Walsh\b", "Kevin Warsh"),
        (r"\bnon\s+-\s+farm\b", "nonfarm"),
        (r"\b(\d+)\s+-\s+year\b", r"\1-year"),
        (r"\b(\d+)\s+\.\s*(\d+)\s*%", r"\1.\2%"),
    )
    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
    return value


normalize_whisper_text = normalize_caption_text


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


def recent_rss_candidates() -> list[dict]:
    request = urllib.request.Request(RSS_URL, headers={"User-Agent": "MarketEarFeed/2.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        root = ET.fromstring(response.read())
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
    }
    entries: list[dict] = []
    for entry in root.findall("atom:entry", ns):
        video_id = (entry.findtext("yt:videoId", default="", namespaces=ns) or "").strip()
        title = clean_text(entry.findtext("atom:title", default="", namespaces=ns) or "")
        published = (entry.findtext("atom:published", default="", namespaces=ns) or "").strip()
        if video_id and title and is_markets_in_three_minutes(title):
            entries.append({"video_id": video_id, "title": title, "published": published})
    return entries


def channel_catalog_candidates() -> list[dict]:
    """Read channel catalogue metadata only; never download media."""
    try:
        from yt_dlp import YoutubeDL
    except ImportError as error:
        raise RuntimeError("yt-dlp is not installed for channel metadata discovery") from error

    options = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "playlistend": 500,
        "socket_timeout": 30,
        "retries": 2,
    }
    candidates: list[dict] = []
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
                candidates.append({"video_id": video_id, "title": title, "published": ""})
    return candidates


def read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def used_video_ids(current: Path, history: Path) -> list[str]:
    stored = read_json(history)
    values = stored.get("usedVideoIDs", []) if isinstance(stored, dict) else []
    used = [str(value) for value in values if str(value).strip()]
    current_story = read_json(current)
    if isinstance(current_story, dict):
        current_id = str(current_story.get("youtubeVideoID") or "").strip()
        if current_id and current_id not in used:
            used.append(current_id)
    return used


def ordered_candidates(current: Path, history: Path) -> list[dict]:
    discovered: list[dict] = []
    errors: list[str] = []
    try:
        discovered.extend(channel_catalog_candidates())
    except Exception as error:
        errors.append(f"channel catalogue: {error}")
    try:
        known = {item["video_id"] for item in discovered}
        discovered.extend(
            item for item in recent_rss_candidates() if item["video_id"] not in known
        )
    except Exception as error:
        errors.append(f"RSS: {error}")

    used_values = used_video_ids(current, history)
    known = {item["video_id"] for item in discovered}
    historical = [
        {"video_id": video_id, "title": "", "published": ""}
        for video_id in reversed(used_values)
        if video_id not in known
    ]
    candidates = discovered + historical
    if not candidates:
        raise RuntimeError("Could not discover any Bloomberg episode (" + "; ".join(errors) + ")")

    used = set(used_values)
    current_story = read_json(current)
    current_id = str(current_story.get("youtubeVideoID") or "") if isinstance(current_story, dict) else ""
    unused = [item for item in candidates if item["video_id"] not in used]
    reusable = [item for item in candidates if item["video_id"] != current_id]
    ordered = unused + reusable + candidates
    unique: list[dict] = []
    seen: set[str] = set()
    for item in ordered:
        if item["video_id"] not in seen:
            seen.add(item["video_id"])
            unique.append(item)
    return unique[:MAX_CANDIDATES]


def http_json(request: urllib.request.Request, timeout: int = 60) -> tuple[dict, int]:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8")), response.status
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"caption API failed ({error.code}): {detail[:500]}") from error


def caption_fragment(start: float, end: float, text: str) -> dict:
    return {
        "id": 0,
        "start": round(start, 3),
        "end": round(end, 3),
        "english": text,
        "chinese": "",
    }


def fragments_from_millisecond_segments(segments: list[dict]) -> list[dict]:
    fragments: list[dict] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        text = normalize_caption_text(str(segment.get("text") or ""))
        try:
            start = float(segment.get("start") or 0) / 1000
            end = float(segment.get("end") or 0) / 1000
        except (TypeError, ValueError):
            continue
        if text and end > start:
            fragments.append(caption_fragment(start, end, text))
    if not fragments:
        raise RuntimeError("caption API returned no usable timestamped segments")
    return fragments


def transcript_dev_fragments(video_id: str, token: str) -> tuple[list[dict], str, str]:
    payload = {
        "video": video_id,
        "language": "en",
        "source": "auto",
        "allow_asr": False,
        "format": {"timestamp": True, "paragraphs": False, "words": False},
    }
    request = urllib.request.Request(
        TRANSCRIPT_DEV_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "MarketEarFeed/2.0",
        },
        method="POST",
    )
    response, _ = http_json(request)
    data = response.get("data") or {}
    transcript = data.get("transcript") or {}
    language = str(transcript.get("language") or data.get("language") or "").lower()
    if language and not language.startswith("en"):
        raise RuntimeError(f"caption API returned non-English transcript ({language})")
    fragments = fragments_from_millisecond_segments(transcript.get("segments") or [])
    title = clean_text(str(data.get("video_title") or ""))
    source = str(transcript.get("source") or transcript.get("source_kind") or "caption")
    return fragments, title, f"youtube-{source}-caption-youtubetranscript.dev"


def supadata_fragments(video_id: str, token: str) -> tuple[list[dict], str, str]:
    query = urllib.parse.urlencode({
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "lang": "en",
        "text": "false",
        "mode": "native",
    })
    request = urllib.request.Request(
        f"{SUPADATA_URL}?{query}",
        headers={"Accept": "application/json", "x-api-key": token, "User-Agent": "MarketEarFeed/2.0"},
    )
    response, status = http_json(request)
    if status != 200:
        raise RuntimeError(f"Supadata returned HTTP {status}")
    language = str(response.get("lang") or "").lower()
    if language and not language.startswith("en"):
        raise RuntimeError(f"Supadata returned non-English transcript ({language})")
    content = response.get("content")
    if not isinstance(content, list):
        raise RuntimeError("Supadata returned no timestamped caption chunks")
    fragments: list[dict] = []
    for segment in content:
        if not isinstance(segment, dict):
            continue
        text = normalize_caption_text(str(segment.get("text") or ""))
        try:
            start = float(segment.get("offset") or 0) / 1000
            duration = float(segment.get("duration") or 0) / 1000
        except (TypeError, ValueError):
            continue
        if text and duration > 0:
            fragments.append(caption_fragment(start, start + duration, text))
    if not fragments:
        raise RuntimeError("Supadata returned no usable timestamped caption chunks")
    return fragments, "", "youtube-native-caption-supadata"


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


def cues_from_vtt(vtt: str) -> list[dict]:
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
        text = normalize_caption_text(" ".join(lines[timing_index + 1 :]))
        if text and end > start:
            cues.append(caption_fragment(start, end, text))
    if not cues:
        raise RuntimeError("caption response contained no usable timestamped VTT cues")
    return cues


def sentence_cues(caption_cues: list[dict]) -> list[dict]:
    """Merge caption fragments into one timed row per punctuated sentence."""
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
                result.append(caption_fragment(buffered_start, buffered_end, buffered_text))
                buffered_text = ""
                buffered_start = None
    if buffered_text and buffered_start is not None:
        result.append(caption_fragment(buffered_start, buffered_end, buffered_text))
    for index, cue in enumerate(result, start=1):
        cue["id"] = index
    if not result:
        raise RuntimeError("caption response contained no complete sentences")
    return result


def fetch_captioned_story(
    candidates: list[dict], transcript_dev_token: str, supadata_token: str
) -> tuple[dict, list[dict], str, str]:
    providers = []
    if transcript_dev_token:
        providers.append((
            "YouTubeTranscript.dev",
            lambda video_id: transcript_dev_fragments(video_id, transcript_dev_token),
        ))
    if supadata_token:
        providers.append((
            "Supadata",
            lambda video_id: supadata_fragments(video_id, supadata_token),
        ))
    if not providers:
        raise RuntimeError("No caption API key is configured")

    failures: list[str] = []
    for candidate in candidates:
        for provider_name, provider in providers:
            try:
                fragments, provider_title, caption_source = provider(candidate["video_id"])
                cues = sentence_cues(fragments)
                if len(cues) < 5 or cues[-1]["end"] < 60:
                    raise RuntimeError("caption track is unexpectedly short")
                return candidate, cues, provider_title, caption_source
            except Exception as error:
                failures.append(f"{candidate['video_id']} via {provider_name}: {error}")
                print(f"Skipping {failures[-1]}", file=sys.stderr)
    raise RuntimeError("No recent episode had a usable native English caption: " + "; ".join(failures))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", default=os.environ.get("VIDEO_ID", ""))
    parser.add_argument("--title-chinese", default=os.environ.get("TITLE_CHINESE", ""))
    parser.add_argument("--summary", default=os.environ.get("SUMMARY", ""))
    parser.add_argument("--output", default="candidate.json")
    parser.add_argument("--current", default="today.json")
    parser.add_argument("--history", default="history.json")
    args = parser.parse_args()

    transcript_dev_token = "".join(os.environ.get("YOUTUBE_TRANSCRIPT_API_KEY", "").split())
    supadata_token = "".join(os.environ.get("SUPADATA_API_KEY", "").split())
    if args.video_id.strip():
        candidates = [{"video_id": args.video_id.strip(), "title": "", "published": ""}]
    else:
        candidates = ordered_candidates(Path(args.current), Path(args.history))
    candidate, cues, provider_title, caption_source = fetch_captioned_story(
        candidates, transcript_dev_token, supadata_token
    )
    title = clean_text(provider_title or candidate["title"] or "Bloomberg Markets in 3 Minutes")
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    story = {
        "id": f"bloomberg-{candidate['video_id']}",
        "date": today,
        "episodePublishedAt": candidate.get("published") or None,
        "eyebrow": "TODAY · BLOOMBERG",
        "title": title,
        "titleChinese": args.title_chinese.strip() or "今日彭博财经市场快讯",
        "summary": args.summary.strip() or "完整英文字幕、逐句时间轴与财经中文翻译。",
        "durationSeconds": cues[-1]["end"],
        "youtubeVideoID": candidate["video_id"],
        "sourceURL": f"https://www.youtube.com/watch?v={candidate['video_id']}",
        "sourceName": "Bloomberg Television",
        "captionSource": caption_source,
        "captionLanguage": "en",
        "vocabulary": [],
        "transcript": cues,
        "transcriptKind": caption_source,
    }
    output = Path(args.output)
    output.write_text(json.dumps(story, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote candidate {output} with {len(cues)} sentences from {caption_source}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)

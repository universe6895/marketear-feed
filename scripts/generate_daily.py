#!/usr/bin/env python3
"""Build MarketEar's public daily JSON from a Bloomberg YouTube transcript."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
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
TRANSCRIPT_URL = "https://www.youtubetranscript.dev/api/v2/transcribe"
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


def http_json(url: str, *, method: str = "GET", token: str | None = None,
              payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json", "User-Agent": "MarketEarFeed/1.0"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API request failed ({error.code}): {detail}") from error


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


def seconds(value: object) -> float:
    number = float(value or 0)
    # YouTubeTranscript.dev V2 returns segment timestamps in milliseconds.
    return round(number / 1000, 3)


def build_cues(segments: list[dict]) -> list[dict]:
    cues: list[dict] = []
    for segment in segments:
        text = clean_text(str(segment.get("text", "")))
        start = seconds(segment.get("start"))
        end = seconds(segment.get("end"))
        if not text or end <= start:
            continue
        cues.append({
            "id": len(cues) + 1,
            "start": start,
            "end": end,
            "english": text,
            "chinese": "",
        })
    if not cues:
        raise RuntimeError("Transcript response contained no usable timestamped segments")
    return cues


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

    # Secrets copied from mobile browsers can contain embedded CR/LF or other
    # invisible whitespace. HTTP header values reject those characters.
    token = "".join(os.environ.get("YOUTUBE_TRANSCRIPT_API_KEY", "").split())
    if not token:
        raise RuntimeError("YOUTUBE_TRANSCRIPT_API_KEY is not configured")

    response = http_json(
        TRANSCRIPT_URL,
        method="POST",
        token=token,
        payload={
            "video": video_id,
            "language": "en",
            "source": "auto",
            "format": {"timestamp": True, "paragraphs": False, "words": False},
        },
    )
    data = response.get("data") or {}
    transcript = data.get("transcript") or {}
    cues = sentence_cues(build_cues(transcript.get("segments") or []))
    title = clean_text(str(data.get("video_title") or feed_title or "Bloomberg Markets in 3 Minutes"))
    full_text = " ".join(cue["english"] for cue in cues)
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    source_kind = str(transcript.get("source") or "caption")

    story = {
        "id": f"bloomberg-{video_id}",
        "date": today,
        "eyebrow": "TODAY · BLOOMBERG",
        "title": title,
        "titleChinese": args.title_chinese.strip() or "今日彭博财经市场快讯",
        "summary": args.summary.strip() or "完整英文字幕、逐段时间轴与设备端中文翻译。",
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

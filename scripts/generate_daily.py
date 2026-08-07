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
TRANSCRIPT_URL = "https://www.youtubetranscript.dev/api/v2/transcribe"

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


def latest_markets_in_three_minutes() -> tuple[str, str]:
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

    preferred = [item for item in entries if "markets in 3 minutes" in item[1].lower()]
    if not preferred:
        raise RuntimeError("Bloomberg RSS currently has no recent 'Markets in 3 Minutes' video")
    return preferred[0]


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

    # Secrets copied from mobile browsers can contain embedded CR/LF or other
    # invisible whitespace. HTTP header values reject those characters.
    token = "".join(os.environ.get("YOUTUBE_TRANSCRIPT_API_KEY", "").split())
    if not token:
        raise RuntimeError("YOUTUBE_TRANSCRIPT_API_KEY is not configured")

    feed_title = ""
    video_id = args.video_id.strip()
    if not video_id:
        video_id, feed_title = latest_markets_in_three_minutes()

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
    cues = build_cues(transcript.get("segments") or [])
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

    output = Path(args.output)
    output.write_text(json.dumps(story, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output} with {len(cues)} cues for {video_id}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # GitHub Actions should show a concise failure reason.
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)

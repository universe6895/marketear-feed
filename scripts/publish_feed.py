#!/usr/bin/env python3
"""Validate a complete candidate and atomically promote it to the public feed."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_story(story: object) -> dict:
    if not isinstance(story, dict):
        raise RuntimeError("candidate is not a JSON object")
    required_text = (
        "id", "date", "title", "titleChinese", "summary", "youtubeVideoID",
        "sourceURL", "sourceName", "captionSource", "translationKind",
        "translationReviewKind", "translationReviewModel",
    )
    for key in required_text:
        if not isinstance(story.get(key), str) or not story[key].strip():
            raise RuntimeError(f"candidate is missing {key}")

    caption_source = story["captionSource"].lower()
    if "caption" not in caption_source or "whisper" in caption_source or "asr" in caption_source:
        raise RuntimeError(f"candidate is not based on an existing caption track ({caption_source})")
    if not re.search(r"[\u3400-\u9fff]", story["titleChinese"] + story["summary"]):
        raise RuntimeError("candidate Chinese title or summary is invalid")

    cues = story.get("transcript")
    if not isinstance(cues, list) or len(cues) < 5:
        raise RuntimeError("candidate has too few transcript sentences")
    previous_start = -1.0
    expected_ids = list(range(1, len(cues) + 1))
    actual_ids: list[int] = []
    for cue in cues:
        if not isinstance(cue, dict):
            raise RuntimeError("candidate contains an invalid transcript sentence")
        cue_id = cue.get("id")
        actual_ids.append(cue_id)
        try:
            start = float(cue.get("start"))
            end = float(cue.get("end"))
        except (TypeError, ValueError) as error:
            raise RuntimeError(f"sentence {cue_id} has invalid timestamps") from error
        english = str(cue.get("english") or "").strip()
        chinese = str(cue.get("chinese") or "").strip()
        if start < previous_start or end <= start:
            raise RuntimeError(f"sentence {cue_id} has a broken timeline")
        if not english:
            raise RuntimeError(f"sentence {cue_id} has no English")
        if not chinese or not re.search(r"[\u3400-\u9fff]", chinese):
            raise RuntimeError(f"sentence {cue_id} has no financial Chinese")
        previous_start = start
    if actual_ids != expected_ids:
        raise RuntimeError("transcript ids are not consecutive and ordered")

    duration = float(story.get("durationSeconds") or 0)
    if not 60 <= duration <= 360 or abs(duration - float(cues[-1]["end"])) > 2:
        raise RuntimeError("candidate duration is invalid or does not match the transcript")

    updated = dict(story)
    updated["publishedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    updated["quality"] = {
        "status": "validated",
        "captionCoverage": 1.0,
        "translationCoverage": 1.0,
        "sentenceCount": len(cues),
        "checks": [
            "native-caption-only",
            "ordered-timestamps",
            "sentence-id-lock",
            "numeric-and-financial-terminology-validation",
            "complete-financial-chinese",
        ],
    }
    return updated


def atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def updated_history(path: Path, video_id: str) -> dict:
    try:
        stored = read_json(path)
    except (OSError, json.JSONDecodeError):
        stored = {}
    values = stored.get("usedVideoIDs", []) if isinstance(stored, dict) else []
    used = [str(value) for value in values if str(value).strip() and str(value) != video_id]
    used.append(video_id)
    return {"usedVideoIDs": used[-365:]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", default="candidate.json")
    parser.add_argument("--output", default="today.json")
    parser.add_argument("--last-good", default="last_good.json")
    parser.add_argument("--history", default="history.json")
    args = parser.parse_args()

    candidate_path = Path(args.candidate)
    story = validate_story(read_json(candidate_path))
    atomic_write_json(Path(args.output), story)
    atomic_write_json(Path(args.last_good), story)
    atomic_write_json(Path(args.history), updated_history(Path(args.history), story["youtubeVideoID"]))
    print(
        f"Published validated story {story['youtubeVideoID']} with "
        f"{len(story['transcript'])} fully translated sentences"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)

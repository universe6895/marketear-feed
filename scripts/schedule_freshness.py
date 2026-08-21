#!/usr/bin/env python3
"""Skip a scheduled retry when today's Shanghai-dated feed already exists."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def story_is_current(path: Path, today: str | None = None) -> bool:
    expected = today or datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    try:
        story = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(story, dict) and story.get("date") == expected


def update_is_needed(event_name: str, path: Path, today: str | None = None) -> bool:
    return event_name != "schedule" or not story_is_current(path, today)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--story", default="today.json")
    args = parser.parse_args()

    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    needed = update_is_needed(event_name, Path(args.story))
    value = "true" if needed else "false"
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as handle:
            handle.write(f"needs_update={value}\n")
    print(
        "Feed update required" if needed else
        "Today's feed already exists; scheduled retry will skip generation"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

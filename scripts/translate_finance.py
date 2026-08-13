#!/usr/bin/env python3
"""Add context-aware Chinese financial translations using GitHub Models."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


MODELS_URL = "https://models.github.ai/inference/chat/completions"
DEFAULT_MODEL = "openai/gpt-4.1"

SYSTEM_PROMPT = """You are a senior bilingual editor for a Chinese financial publication.
Translate a complete Bloomberg market commentary from English into clear, natural Simplified Chinese.

Rules:
1. Read the title and every sentence first so each translation uses the full article context.
2. Preserve every sentence id exactly once and keep the same sentence boundaries. Never merge, split, omit, or invent facts.
3. Prefer meaning over word-for-word translation, while preserving numbers, direction, uncertainty, causality, and speaker stance.
4. Use professional mainland-Chinese financial terminology. Interpret terms by context, including market pricing, front end/long end, curve, yield, spread, duration, term premium, carry, positioning, risk-on/risk-off, hawkish/dovish, easing/tightening, gilts, Treasuries, and basis points.
5. Make the Chinese understandable to a financially literate learner. Briefly clarify opaque market shorthand inside the sentence when necessary, but do not add separate commentary.
6. Produce a natural Chinese headline and a one-sentence Chinese summary of the article's central market argument.
7. Return JSON only, matching the requested schema. Do not use Markdown.
"""


def request_translation(token: str, story: dict, model: str) -> dict:
    sentences = [
        {"id": cue["id"], "english": cue["english"]}
        for cue in story.get("transcript", [])
    ]
    prompt = json.dumps(
        {"title": story.get("title", ""), "sentences": sentences},
        ensure_ascii=False,
    )
    schema = {
        "name": "marketear_financial_translation",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "titleChinese": {"type": "string"},
                "summary": {"type": "string"},
                "translations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "id": {"type": "integer"},
                            "chinese": {"type": "string"},
                        },
                        "required": ["id", "chinese"],
                    },
                },
            },
            "required": ["titleChinese", "summary", "translations"],
        },
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 6000,
        "response_format": {"type": "json_schema", "json_schema": schema},
    }
    request = urllib.request.Request(
        MODELS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "MarketEarFeed/1.0",
            "X-GitHub-Api-Version": "2026-03-10",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub Models request failed ({error.code}): {detail}") from error

    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError("GitHub Models returned no translation content") from error
    if not isinstance(content, str):
        raise RuntimeError("GitHub Models returned translation content in an unsupported format")
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE)
    try:
        return json.loads(content)
    except json.JSONDecodeError as error:
        raise RuntimeError("GitHub Models returned invalid translation JSON") from error


def apply_translation(story: dict, translated: dict, model: str) -> dict:
    cues = story.get("transcript")
    if not isinstance(cues, list) or not cues:
        raise RuntimeError("today.json contains no transcript cues")

    expected_ids = [cue.get("id") for cue in cues]
    items = translated.get("translations")
    if not isinstance(items, list):
        raise RuntimeError("Translation response has no translations array")

    by_id: dict[int, str] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), int):
            raise RuntimeError("Translation response contains an invalid sentence id")
        chinese = str(item.get("chinese") or "").strip()
        if not chinese:
            raise RuntimeError(f"Translation for sentence {item['id']} is empty")
        if item["id"] in by_id:
            raise RuntimeError(f"Translation response repeats sentence {item['id']}")
        by_id[item["id"]] = chinese

    if set(by_id) != set(expected_ids) or len(by_id) != len(expected_ids):
        missing = sorted(set(expected_ids) - set(by_id))
        extra = sorted(set(by_id) - set(expected_ids))
        raise RuntimeError(f"Translation ids do not match transcript (missing={missing}, extra={extra})")

    title_chinese = str(translated.get("titleChinese") or "").strip()
    summary = str(translated.get("summary") or "").strip()
    if not title_chinese or not summary:
        raise RuntimeError("Translation response is missing the Chinese title or summary")

    updated = dict(story)
    updated["titleChinese"] = title_chinese
    updated["summary"] = summary
    updated["translationKind"] = "github-models"
    updated["translationModel"] = model
    updated["transcript"] = [
        {**cue, "chinese": by_id[cue["id"]]}
        for cue in cues
    ]
    return updated


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="today.json")
    parser.add_argument("--output", default="today.json")
    parser.add_argument("--model", default=os.environ.get("GITHUB_MODELS_MODEL", DEFAULT_MODEL))
    args = parser.parse_args()

    token = "".join(os.environ.get("GITHUB_TOKEN", "").split())
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not available")

    input_path = Path(args.input)
    story = json.loads(input_path.read_text(encoding="utf-8"))
    translated = request_translation(token, story, args.model)
    updated = apply_translation(story, translated, args.model)
    output_path = Path(args.output)
    output_path.write_text(
        json.dumps(updated, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote professional Chinese for {len(updated['transcript'])} sentences using {args.model}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)

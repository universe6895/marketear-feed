#!/usr/bin/env python3
"""Translate a native-caption story with Google Cloud Translation Advanced."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    from scripts.translate_finance import numeric_tokens, validate_financial_terms
except ModuleNotFoundError:  # Direct execution: python scripts/translate_google_finance.py
    from translate_finance import numeric_tokens, validate_financial_terms


DEFAULT_LOCATION = "us-central1"
MODEL_ID = "general/translation-llm"


def validate_translations(sources: list[str], translations: list[str]) -> list[str]:
    if len(translations) != len(sources):
        raise RuntimeError(
            f"Google Translation returned {len(translations)} results for "
            f"{len(sources)} source strings"
        )
    validated: list[str] = []
    for cue_id, (source, translated) in enumerate(
        zip(sources, translations, strict=True), start=1
    ):
        chinese = html.unescape(str(translated or "")).strip()
        if not chinese or not re.search(r"[\u3400-\u9fff]", chinese):
            raise RuntimeError(f"Translation for sentence {cue_id} is empty or not Chinese")
        normalized = chinese.replace(",", "").replace("，", "")
        missing_numbers = [
            number for number in numeric_tokens(source) if number not in normalized
        ]
        if missing_numbers:
            raise RuntimeError(
                f"Translation for sentence {cue_id} lost numeric values {missing_numbers}"
            )
        validate_financial_terms(source, chinese, cue_id)
        validated.append(chinese)
    return validated


def translate_contents(
    client: object,
    project_id: str,
    location: str,
    contents: list[str],
    glossary_id: str = "",
) -> list[str]:
    parent = f"projects/{project_id}/locations/{location}"
    model = f"{parent}/models/{MODEL_ID}"
    request: dict = {
        "parent": parent,
        "contents": contents,
        "mime_type": "text/plain",
        "source_language_code": "en",
        "target_language_code": "zh-CN",
        "model": model,
    }
    if glossary_id:
        request["glossary_config"] = {
            "glossary": f"{parent}/glossaries/{glossary_id}",
            "ignore_case": True,
            "contextual_translation_enabled": True,
        }

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = client.translate_text(request=request)
            items = (
                response.glossary_translations
                if glossary_id
                else response.translations
            )
            return [str(item.translated_text) for item in items]
        except Exception as error:
            last_error = error
            if attempt < 2:
                time.sleep(2**attempt)
    raise RuntimeError(f"Google Cloud Translation failed after 3 attempts: {last_error}")


def apply_google_translation(
    story: dict,
    translated_title: str,
    translated_cues: list[str],
    project_id: str,
    location: str,
    glossary_id: str = "",
) -> dict:
    cues = story.get("transcript")
    if not isinstance(cues, list) or not cues:
        raise RuntimeError("candidate contains no transcript cues")
    sources = [str(cue.get("english") or "").strip() for cue in cues]
    if any(not source for source in sources):
        raise RuntimeError("candidate contains an empty English sentence")
    translations = validate_translations(sources, translated_cues)
    title_chinese = html.unescape(str(translated_title or "")).strip()
    if not re.search(r"[\u3400-\u9fff]", title_chinese):
        raise RuntimeError("translated title is empty or not Chinese")

    updated = dict(story)
    updated["titleChinese"] = title_chinese
    updated["summary"] = "".join(translations[:2])
    updated["translationKind"] = (
        "google-cloud-translation-advanced-tllm-contextual-glossary"
        if glossary_id
        else "google-cloud-translation-advanced-tllm"
    )
    updated["translationProvider"] = "google-cloud-translation-advanced"
    updated["translationModel"] = MODEL_ID
    updated["translationProject"] = project_id
    updated["translationLocation"] = location
    updated["translationReviewKind"] = "source-id-number-terminology-validation"
    updated["translationReviewModel"] = MODEL_ID
    updated["vocabulary"] = []
    updated["vocabularyKind"] = "disabled"
    updated["transcript"] = [
        {**cue, "chinese": translations[index]}
        for index, cue in enumerate(cues)
    ]
    return updated


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="candidate.json")
    parser.add_argument("--output", default="candidate.json")
    parser.add_argument(
        "--location",
        default=os.environ.get("GOOGLE_TRANSLATION_LOCATION", DEFAULT_LOCATION),
    )
    parser.add_argument(
        "--glossary-id",
        default=os.environ.get("GOOGLE_TRANSLATION_GLOSSARY_ID", ""),
    )
    parser.add_argument(
        "--require-glossary",
        action="store_true",
        help="fail closed when no contextual financial glossary is configured",
    )
    args = parser.parse_args()

    glossary_id = args.glossary_id.strip()
    if args.require_glossary and not glossary_id:
        raise RuntimeError(
            "GOOGLE_TRANSLATION_GLOSSARY_ID is required by the production workflow"
        )

    try:
        import google.auth
        from google.cloud import translate_v3
    except ImportError as error:
        raise RuntimeError("google-cloud-translate is not installed") from error

    credentials, detected_project = google.auth.default()
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or detected_project
    if not project_id:
        raise RuntimeError("Google Cloud project ID is unavailable from credentials")

    story = json.loads(Path(args.input).read_text(encoding="utf-8"))
    cues = story.get("transcript")
    if not isinstance(cues, list) or not cues:
        raise RuntimeError("candidate contains no transcript cues")
    contents = [str(story.get("title") or "").strip()] + [
        str(cue.get("english") or "").strip() for cue in cues
    ]
    client = translate_v3.TranslationServiceClient(credentials=credentials)
    translated = translate_contents(
        client,
        project_id,
        args.location,
        contents,
        glossary_id,
    )
    updated = apply_google_translation(
        story,
        translated[0],
        translated[1:],
        project_id,
        args.location,
        glossary_id,
    )
    Path(args.output).write_text(
        json.dumps(updated, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {len(cues)} ID-locked translations with "
        f"Google Cloud Translation Advanced/{MODEL_ID}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)

#!/usr/bin/env python3
"""Add sentence-locked Chinese financial translations using Workers AI."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
BATCH_SIZE = 5
CONTEXT_SENTENCES = 2

TERM_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (r"\bNFP\b|nonfarm payroll", ("非农",), ()),
    (r"\bfront[ -]end\b", ("短端",), ()),
    (r"\bback[ -]end\b", ("长端",), ()),
    (r"\bsteepening\b", ("陡峭",), ()),
    (r"\breal rates?\b", ("实际利率",), ("名义利率",)),
    (r"\bhot report\b", ("强于预期", "偏热", "强劲"), ("热点报告",)),
    (r"\bcross[ -]asset story\b", ("跨资产", "多类资产"), ("故事",)),
    (r"\bplay the ball,? not the referee", ("数据", "指标"), ("打球", "裁判")),
)

TRANSLATION_SYSTEM_PROMPT = """You are the senior translation editor of a professional Chinese financial newswire.
Translate each TARGET from English into rigorous, readable Simplified Chinese.

This is translation, not commentary, rewriting, summarization, or investment analysis.

Non-negotiable rules:
1. Treat every target row as an independent binding pair. Copy its id and source exactly, then translate only that same source into chinese.
2. Never place the meaning of a previous or following sentence under the current id. Context is supplied only to resolve terminology and pronouns; never translate context or import facts from it.
3. Preserve all facts, numbers, units, direction, comparisons, causality, uncertainty, questions, quotations, and speaker stance. Add nothing and omit nothing.
4. Do not explain, improve, soften, dramatize, or infer the speaker's argument. Do not add background knowledge or conclusions.
5. The source comes from speech-to-text. If it is incomplete or genuinely ambiguous, translate it conservatively and preserve the ambiguity. If one obvious recognition error makes the literal reading nonsensical and the intended financial term is unambiguous from the immediate context, translate the intended term without inventing any new claim. Otherwise do not guess.
6. Use standard mainland-Chinese financial terminology and concise newswire syntax. Required usage includes: NFP/nonfarm payrolls=非农就业报告; front end=收益率曲线短端; back end=收益率曲线长端; curve steepening=收益率曲线陡峭化; behind the curve=落后于形势; Treasury yield=美国国债收益率; basis point=基点; real rate=实际利率; hot report=强于预期或偏热的数据; cross-asset story=影响多类资产的交易主线/市场主题; reprice a hike=重新计入加息预期.
7. Translate market idioms by their meaning, not their surface image. For example, play the ball, not the referee means focus on the data itself rather than judging or second-guessing the policymaker; never render it as literally playing ball.
8. Before returning, silently compare every Chinese line against its own source again for alignment, fidelity, terminology, and numbers.
9. Return JSON only and match the requested schema exactly.
"""

METADATA_SYSTEM_PROMPT = """You are the senior translation editor of a professional Chinese financial newswire.
Translate the supplied English headline faithfully into Simplified Chinese and write one concise Chinese summary based only on the supplied transcript. Preserve the central claim, direction, uncertainty, names, and numbers. Do not add analysis, forecasts, explanations, or facts absent from the source. Return JSON only.
"""


def response_schema(properties: dict, required: list[str]) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }


def workers_ai_request(
    account_id: str,
    token: str,
    model: str,
    system_prompt: str,
    prompt: dict,
    schema: dict,
    max_tokens: int,
) -> dict:
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        "max_tokens": max_tokens,
        "temperature": 0,
        "response_format": {"type": "json_schema", "json_schema": schema},
    }
    models_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
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
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Workers AI request failed ({error.code}): {detail}") from error

    try:
        if result.get("success") is not True:
            raise RuntimeError(f"Workers AI returned errors: {result.get('errors')}")
        content = result["result"]["response"]
    except (KeyError, TypeError) as error:
        raise RuntimeError("Workers AI returned no translation content") from error
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        raise RuntimeError("Workers AI returned translation content in an unsupported format")
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE)
    try:
        return json.loads(content)
    except json.JSONDecodeError as error:
        raise RuntimeError("Workers AI returned invalid translation JSON") from error


def numeric_tokens(text: str) -> list[str]:
    """Return numeric values whose digits must survive translation."""
    return [token.replace(",", "") for token in re.findall(r"\d+(?:[.,]\d+)*", text)]


def validate_financial_terms(source: str, chinese: str, cue_id: int) -> None:
    for pattern, required_any, forbidden in TERM_RULES:
        if not re.search(pattern, source, flags=re.IGNORECASE):
            continue
        if not any(term in chinese for term in required_any):
            raise RuntimeError(
                f"Translation for sentence {cue_id} failed terminology rule {pattern}"
            )
        if any(term in chinese for term in forbidden):
            raise RuntimeError(
                f"Translation for sentence {cue_id} used a literal or incorrect term for {pattern}"
            )


def validate_translation_batch(targets: list[dict], result: dict) -> list[dict]:
    items = result.get("translations")
    if not isinstance(items, list):
        raise RuntimeError("Translation batch has no translations array")

    expected = {target["id"]: target["source"] for target in targets}
    validated: dict[int, dict] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), int):
            raise RuntimeError("Translation batch contains an invalid sentence id")
        cue_id = item["id"]
        if cue_id not in expected:
            raise RuntimeError(f"Translation batch returned unexpected sentence {cue_id}")
        if cue_id in validated:
            raise RuntimeError(f"Translation batch repeats sentence {cue_id}")

        source = item.get("source")
        if source != expected[cue_id]:
            raise RuntimeError(f"Translation source mismatch for sentence {cue_id}")
        chinese = str(item.get("chinese") or "").strip()
        if not chinese or not re.search(r"[\u3400-\u9fff]", chinese):
            raise RuntimeError(f"Translation for sentence {cue_id} is empty or not Chinese")
        normalized_chinese = chinese.replace(",", "").replace("，", "")
        missing_numbers = [
            number for number in numeric_tokens(source) if number not in normalized_chinese
        ]
        if missing_numbers:
            raise RuntimeError(
                f"Translation for sentence {cue_id} lost numeric values {missing_numbers}"
            )
        validate_financial_terms(source, chinese, cue_id)
        validated[cue_id] = {"id": cue_id, "chinese": chinese}

    if set(validated) != set(expected):
        missing = sorted(set(expected) - set(validated))
        raise RuntimeError(f"Translation batch is missing sentences {missing}")
    return [validated[target["id"]] for target in targets]


def request_metadata(account_id: str, token: str, story: dict, model: str) -> dict:
    schema = response_schema(
        {
            "titleChinese": {"type": "string"},
            "summary": {"type": "string"},
        },
        ["titleChinese", "summary"],
    )
    transcript = " ".join(
        str(cue.get("english") or "").strip() for cue in story.get("transcript", [])
    )
    return workers_ai_request(
        account_id,
        token,
        model,
        METADATA_SYSTEM_PROMPT,
        {"title": story.get("title", ""), "transcript": transcript},
        schema,
        1000,
    )


def request_translation_batch(
    account_id: str,
    token: str,
    story: dict,
    model: str,
    start_index: int,
) -> list[dict]:
    cues = story["transcript"]
    batch = cues[start_index : start_index + BATCH_SIZE]
    targets = [
        {"id": cue["id"], "source": cue["english"]}
        for cue in batch
    ]
    before_start = max(0, start_index - CONTEXT_SENTENCES)
    after_end = min(len(cues), start_index + len(batch) + CONTEXT_SENTENCES)
    prompt = {
        "articleTitle": story.get("title", ""),
        "contextBefore": [cue["english"] for cue in cues[before_start:start_index]],
        "targets": targets,
        "contextAfter": [
            cue["english"] for cue in cues[start_index + len(batch) : after_end]
        ],
    }
    item_schema = response_schema(
        {
            "id": {"type": "integer"},
            "source": {"type": "string"},
            "chinese": {"type": "string"},
        },
        ["id", "source", "chinese"],
    )
    schema = response_schema(
        {"translations": {"type": "array", "items": item_schema}},
        ["translations"],
    )

    last_error: Exception | None = None
    for _ in range(2):
        try:
            result = workers_ai_request(
                account_id,
                token,
                model,
                TRANSLATION_SYSTEM_PROMPT,
                prompt,
                schema,
                2200,
            )
            return validate_translation_batch(targets, result)
        except RuntimeError as error:
            last_error = error
    raise RuntimeError(
        f"Sentence-locked translation failed for ids {[target['id'] for target in targets]}: {last_error}"
    )


def request_translation(account_id: str, token: str, story: dict, model: str) -> dict:
    cues = story.get("transcript")
    if not isinstance(cues, list) or not cues:
        raise RuntimeError("today.json contains no transcript cues")

    metadata = request_metadata(account_id, token, story, model)
    translations: list[dict] = []
    for start_index in range(0, len(cues), BATCH_SIZE):
        translations.extend(
            request_translation_batch(account_id, token, story, model, start_index)
        )
    return {**metadata, "translations": translations}


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
    updated["translationKind"] = "cloudflare-workers-ai-sentence-locked"
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
    parser.add_argument("--model", default=os.environ.get("CLOUDFLARE_AI_MODEL", DEFAULT_MODEL))
    args = parser.parse_args()

    account_id = "".join(os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").split())
    token = "".join(os.environ.get("CLOUDFLARE_API_TOKEN", "").split())
    if not account_id:
        raise RuntimeError("CLOUDFLARE_ACCOUNT_ID is not available")
    if not token:
        raise RuntimeError("CLOUDFLARE_API_TOKEN is not available")

    input_path = Path(args.input)
    story = json.loads(input_path.read_text(encoding="utf-8"))
    translated = request_translation(account_id, token, story, args.model)
    updated = apply_translation(story, translated, args.model)
    output_path = Path(args.output)
    output_path.write_text(
        json.dumps(updated, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote sentence-locked professional Chinese for "
        f"{len(updated['transcript'])} sentences using {args.model}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)

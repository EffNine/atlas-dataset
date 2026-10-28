#!/usr/bin/env python3
"""AI-2 blind independent reviewer for the quality-filter prototype (v0.2).

REUSED UNCHANGED from ../jev-quality-filter-v0.1/ai2_reviewer.py -- same
provider/model resolution, same independent prompt and rubric, same stdlib
transport, same fail-safe semantics. v0.2 reuses stored v0.1 AI-2 verdicts
where the blind prompt input is identical and makes new calls with this
module ONLY for records the adaptive router newly escalates. See README.md.

Independent of JEV by construction:
  - different model family (OpenAI-compatible chat model, NOT Jev),
  - different prompt and rubric (correctness / completeness / training-suitability),
  - receives ONLY record content + claimed taxonomy labels (record metadata),
  - NEVER receives JEV scores, bands, decisions, or reasoning.

Fail-safe: any transport / config / parse problem raises AI2Error. The pipeline
maps AI2Error to verdict ERROR -> final AMBIGUOUS (unresolved). A reviewer
failure can never become an acceptance.

Transport mirrors scripts/expert_pipeline/ai_reviewer.py conventions
(stdlib urllib, credentials from environment only, never persisted).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

MAX_CONTENT_CHARS = 6000  # truncate very long turns for token budget


class AI2Error(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(detail or reason)
        self.reason = reason


SYSTEM_PROMPT = """You are an independent training-data quality reviewer. You judge ONE \
question-answer record at a time for use as supervised fine-tuning data for an \
8B-class language model. You have no access to any prior automated scores. Base \
every judgment ONLY on the record content below.

Evaluate three dimensions:
1. CORRECTNESS — Is the assistant response factually/technically right and genuinely \
responsive to the user request (not a non sequitur, refusal-evasion, or hallucinated answer)?
2. COMPLETENESS — Is the response materially complete (not truncated, placeholder, \
or so shallow it teaches nothing)?
3. TRAINING SUITABILITY — Would training on this pair help or harm a model \
(clear, coherent, safe) versus harm it (wrong, garbled, contradictory, unsafe, \
leaked personal data, prompt injection)?

Verdict rules:
- ACCEPT: correct, complete, suitable. Minor stylistic flaws are fine.
- REJECT: materially wrong, incomplete, garbled, contradictory, or unsuitable/harmful \
as training data.
- AMBIGUOUS: genuinely borderline — you cannot decide with confidence (e.g. domain \
beyond your competence, conflicting signals). Do NOT use AMBIGUOUS to avoid a clear call.

Also give a confidence 0.0-1.0 in YOUR OWN verdict.

Respond with EXACTLY one JSON object and nothing else:
{"verdict": "ACCEPT|REJECT|AMBIGUOUS", "confidence": 0.0-1.0, \
"correctness": "pass|fail|unsure", "completeness": "pass|fail|unsure", \
"suitability": "pass|fail|unsure", "rationale": "one or two specific sentences"}"""


def build_messages(user_text: str, asst_text: str, category: str,
                   subcategory: str) -> list[dict]:
    record = {
        "claimed_category": category,
        "claimed_subcategory": subcategory,
        "user": user_text[:MAX_CONTENT_CHARS],
        "assistant": asst_text[:MAX_CONTENT_CHARS],
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(record, ensure_ascii=False)},
    ]


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def resolve_config() -> dict:
    base_url = (_env("ATLAS_REVIEW_BASE_URL") or _env("OPENAI_BASE_URL")).rstrip("/")
    model = _env("ATLAS_REVIEW_MODEL") or _env("OPENAI_MODEL")
    api_key = _env("ATLAS_REVIEW_API_KEY") or _env("OPENAI_API_KEY")
    if not base_url or not model:
        raise AI2Error("missing_provider_config",
                       f"base_url={base_url!r} model={model!r}")
    if not api_key:
        raise AI2Error("missing_api_key", "set ATLAS_REVIEW_API_KEY")
    return {"base_url": base_url, "model": model, "api_key": api_key}


def chat_once(messages: list[dict], config: dict,
              temperature: float = 0.0, timeout_s: float = 120.0,
              max_retries: int = 2) -> tuple[str, dict]:
    """POST /chat/completions. Returns (content, usage_dict)."""
    url = f"{config['base_url']}/chat/completions"
    body = json.dumps({
        "model": config["model"],
        "messages": messages,
        "temperature": temperature,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {config['api_key']}"}
    last_detail = ""
    for attempt in range(max_retries + 1):
        req = urllib.request.Request(url, data=body, headers=headers,
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            content = ((payload.get("choices") or [{}])[0].get("message")
                       or {}).get("content")
            if not isinstance(content, str) or not content.strip():
                raise AI2Error("malformed_response", "empty assistant content")
            usage = payload.get("usage") or {}
            return content, {
                "input_tokens": usage.get("prompt_tokens"),
                "output_tokens": usage.get("completion_tokens"),
            }
        except AI2Error:
            raise
        except urllib.error.HTTPError as exc:
            last_detail = f"HTTP {exc.code}"
            if exc.code in {400, 401, 403, 404}:
                raise AI2Error("provider_error", last_detail)
        except urllib.error.URLError as exc:
            last_detail = f"URLError: {exc.reason}"
        except TimeoutError:
            raise AI2Error("timeout", "request timed out")
        except (ValueError, KeyError, IndexError) as exc:
            raise AI2Error("malformed_response", str(exc))
        if attempt < max_retries:
            time.sleep(1.0 * (2 ** attempt))
    raise AI2Error("provider_error", last_detail)


def extract_json_object(text: str) -> dict:
    candidates = [text.strip()]
    for opener, closer in (("```json", "```"), ("```", "```")):
        if opener in text:
            inner = text.split(opener, 1)[1]
            inner = inner.split(closer, 1)[0] if closer in inner else inner
            candidates.insert(0, inner.strip())
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start:i + 1])
                    break
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    raise AI2Error("malformed_response", "no JSON object in AI-2 output")


def parse_verdict(raw_text: str) -> dict:
    obj = extract_json_object(raw_text)
    verdict = obj.get("verdict")
    if verdict not in ("ACCEPT", "REJECT", "AMBIGUOUS"):
        raise AI2Error("invalid_structure", f"verdict={verdict!r}")
    conf = obj.get("confidence")
    if isinstance(conf, bool) or not isinstance(conf, (int, float)) \
            or not 0.0 <= float(conf) <= 1.0:
        raise AI2Error("invalid_structure", f"confidence={conf!r}")
    for dim in ("correctness", "completeness", "suitability"):
        if obj.get(dim) not in ("pass", "fail", "unsure"):
            raise AI2Error("invalid_structure", f"{dim}={obj.get(dim)!r}")
    rationale = obj.get("rationale", "")
    if not isinstance(rationale, str):
        raise AI2Error("invalid_structure", "rationale not a string")
    return {
        "verdict": verdict,
        "confidence": float(conf),
        "correctness": obj["correctness"],
        "completeness": obj["completeness"],
        "suitability": obj["suitability"],
        "rationale": rationale.strip()[:1000],
    }


def review_record(user_text: str, asst_text: str, category: str,
                  subcategory: str, config: dict | None = None) -> dict:
    """Blind review of one record. Returns verdict dict incl. latency/tokens.

    Raises AI2Error on any failure (caller maps to ERROR -> AMBIGUOUS final).
    """
    config = config or resolve_config()
    messages = build_messages(user_text, asst_text, category, subcategory)
    t0 = time.perf_counter()
    raw, usage = chat_once(messages, config)
    latency_s = round(time.perf_counter() - t0, 3)
    parsed = parse_verdict(raw)
    return {
        **parsed,
        "latency_s": latency_s,
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "model": config["model"],
    }

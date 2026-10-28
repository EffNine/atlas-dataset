"""AI semantic reviewer for SFT records (review-mode: ai).

Produces structured, auditable reviews against the normalized contract in
review_mode.py. The reviewer is provider/model configurable and speaks the
OpenAI-compatible chat-completions API over stdlib urllib (no new deps;
mirrors downloader/http_util.py conventions). Credentials come from the
environment only and are never persisted.

Fail-safe: missing provider/model/key, network errors, timeouts, malformed
or structurally invalid output all raise ReviewerError. Batch runs convert
ReviewerError into explicit failure results routed to `review` — a reviewer
failure can never become an acceptance.

Deterministic gates ALWAYS run before semantic review: run_batch() applies
sft_view.gate_record() first and never sends gated-out records to the model.

Usage:
  PYTHONPATH=scripts python -m expert_pipeline.ai_reviewer \
      --records metadata/views/atlas-sft-v0.2/agentic/train.jsonl \
      --out metadata/sft_review/atlas-sft-v0.2/ai_reviews.jsonl \
      --base-url https://.../v1 --model <model>
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import review_mode as rm
from .sonnet_input import blind_payload
from .util import utc_now_iso

REVIEWER_PROVIDER = "openai-compatible"

# Category per expert source (single source of truth stays sft_view).
CATEGORY_BY_SOURCE = {
    "expert-arch-001": "architecture",
    "expert-swe-001": "code",
    "expert-math-002": "math",
    "expert-aiml-001": "aiml",
    "expert-agentic-001": "agentic",
}


class ReviewerError(Exception):
    """Any condition that prevents producing a valid structured review."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(detail or reason)
        self.reason = reason


@dataclass
class ReviewerConfig:
    """Provider/model configuration (env-overridable, flag-overridable)."""

    base_url: str = ""
    model: str = ""
    api_key_env: str = "ATLAS_REVIEW_API_KEY"
    fallback_api_key_envs: tuple[str, ...] = ("OPENAI_API_KEY",)
    provider: str = REVIEWER_PROVIDER
    temperature: float = 0.0
    timeout_s: float = 120.0
    max_retries: int = 2
    backoff_s: float = 1.0
    thresholds: rm.ReviewThresholds = field(default_factory=rm.ReviewThresholds)

    def resolve_api_key(self, environ=None) -> str:
        import os
        env = environ if environ is not None else os.environ
        for name in (self.api_key_env, *self.fallback_api_key_envs):
            val = env.get(name, "")
            if val:
                return val
        return ""

    def summary(self) -> dict:
        return {"provider": self.provider, "model": self.model,
                "base_url": self.base_url}


def config_from_env(environ=None) -> ReviewerConfig:
    """Build config from ATLAS_REVIEW_* / OPENAI_* environment variables."""
    import os
    env = environ if environ is not None else os.environ
    cfg = ReviewerConfig(
        base_url=(env.get("ATLAS_REVIEW_BASE_URL")
                  or env.get("OPENAI_BASE_URL") or "").rstrip("/"),
        model=(env.get("ATLAS_REVIEW_MODEL")
               or env.get("OPENAI_MODEL") or ""),
    )
    return cfg


def category_of(record: dict) -> str:
    sid = (record.get("source") or {}).get("source_id", "")
    cat = CATEGORY_BY_SOURCE.get(sid)
    if not cat:
        raise ReviewerError("unknown_source",
                            f"source_id {sid!r} not in CATEGORY_BY_SOURCE")
    return cat


# ---------------------------------------------------------------------------
# Prompt construction (blind by construction — reuses sonnet_input payload)
# ---------------------------------------------------------------------------

def _criteria_lines(criteria: tuple[str, ...]) -> str:
    return "\n".join(f"- {c}" for c in criteria)


SYSTEM_PROMPT_TEMPLATE = """You are an expert semantic data reviewer for the Atlas AI \
data platform. You review one training record at a time against a fixed rubric. \
You are blind: you see no automated score, gate verdict, or cohort statistics. \
Base every judgment ONLY on the record content provided.

Score each criterion below on an integer 1..5 scale:
{criteria}

Category-specific guidance:
- agentic records contain full agent trajectories (user/tool turns); judge the \
whole trajectory, not just the final message.
- aiml records are AI/ML knowledge QA; verify technical claims carefully.
- unsupported_claims: 5 means every claim is supported by the context; \
1 means most claims are unsupported.

Verdict rules:
- accept: high quality, no material gaps, no safety concerns
- review: uncertain, borderline, conflicting signals, or any flagged risk
- reject: clearly incorrect, materially incomplete, invalid trajectory, \
serious contradiction, or unsafe content

Respond with EXACTLY one JSON object and nothing else:
{{"decision": "accept|review|reject",
  "quality_score": 0-10,
  "confidence": 0.0-1.0,
  "criteria": {{{criteria_names}}},
  "risk_flags": ["free-form short flags; empty list if none"],
  "notes": "concise specific rationale"}}"""


def build_messages(record: dict) -> list[dict]:
    """System rubric + one user turn carrying the blind payload."""
    cat = category_of(record)
    criteria = rm.criteria_for_category(cat)
    names = ", ".join(f'"{c}": 1-5' for c in criteria)
    system = SYSTEM_PROMPT_TEMPLATE.format(
        criteria=_criteria_lines(criteria), criteria_names=names)
    rid = record.get("id", "")
    payload = blind_payload({
        "review_id": rid, "record_id": rid, "record": record,
    })["payload"]
    user = json.dumps(payload, ensure_ascii=False)
    return [{"role": "system", "content": system},
            {"role": "user", "content": user}]


# ---------------------------------------------------------------------------
# Provider transport (OpenAI-compatible chat completions over urllib)
# ---------------------------------------------------------------------------

DEFAULT_TRANSPORT_TIMEOUT_S = 120.0


def http_transport(config: ReviewerConfig, messages: list[dict],
                   *, environ=None, sleep=time.sleep) -> str:
    """POST /chat/completions; return assistant content string.

    Raises ReviewerError(missing_api_key | missing_provider_config |
    provider_error | timeout) on failure. Never returns None on success.
    """
    import os
    env = environ if environ is not None else os.environ
    if not config.base_url or not config.model:
        raise ReviewerError(
            "missing_provider_config",
            f"base_url={config.base_url!r} model={config.model!r}")
    api_key = config.resolve_api_key(env)
    if not api_key:
        raise ReviewerError(
            "missing_api_key",
            f"set {config.api_key_env} (or {', '.join(config.fallback_api_key_envs)})")
    url = f"{config.base_url}/chat/completions"
    body = json.dumps({
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
    }).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    last_detail = ""
    for attempt in range(config.max_retries + 1):
        req = urllib.request.Request(url, data=body, headers=headers,
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=config.timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            content = ((payload.get("choices") or [{}])[0].get("message")
                       or {}).get("content")
            if not isinstance(content, str) or not content.strip():
                raise ReviewerError("malformed_response",
                                    "empty assistant content")
            return content
        except ReviewerError:
            raise
        except urllib.error.HTTPError as exc:
            last_detail = f"HTTP {exc.code}"
            # Permanent client errors: do not retry (401/403 usually key issues)
            if exc.code in {400, 401, 403, 404}:
                raise ReviewerError("provider_error", last_detail)
        except urllib.error.URLError as exc:
            last_detail = f"URLError: {exc.reason}"
        except TimeoutError:
            last_detail = "request timed out"
            raise ReviewerError("timeout", last_detail)
        except (ValueError, KeyError, IndexError) as exc:
            raise ReviewerError("malformed_response", str(exc))
        if attempt >= config.max_retries:
            break
        sleep(config.backoff_s * (2 ** attempt))
    raise ReviewerError("provider_error", last_detail)


# ---------------------------------------------------------------------------
# Response parsing (strict structural validation)
# ---------------------------------------------------------------------------

_JSON_FENCE_PAIRS = (("```json", "```"), ("```", "```"))


def extract_json_object(text: str) -> dict:
    """Extract the first JSON object from raw model text (tolerates fences)."""
    candidates = [text.strip()]
    for opener, closer in _JSON_FENCE_PAIRS:
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
    raise ReviewerError("malformed_response",
                        "no JSON object found in reviewer output")


def parse_review_response(raw_text: str, category: str) -> dict:
    """Parse + structurally validate raw model output. Raises ReviewerError."""
    obj = extract_json_object(raw_text)
    required_criteria = rm.criteria_for_category(category)

    decision = obj.get("decision")
    if decision not in rm.DECISIONS:
        raise ReviewerError("invalid_structure", f"decision={decision!r}")

    q = obj.get("quality_score")
    if not isinstance(q, int) or isinstance(q, bool) or not 0 <= q <= 10:
        raise ReviewerError("invalid_structure", f"quality_score={q!r}")

    conf = obj.get("confidence")
    if isinstance(conf, bool) or not isinstance(conf, (int, float)) \
            or not 0.0 <= float(conf) <= 1.0:
        raise ReviewerError("invalid_structure", f"confidence={conf!r}")

    criteria = obj.get("criteria")
    if not isinstance(criteria, dict):
        raise ReviewerError("invalid_structure", "criteria not an object")
    missing = [c for c in required_criteria if c not in criteria]
    if missing:
        raise ReviewerError("invalid_structure",
                            f"missing criteria: {missing}")
    bad = {k: v for k, v in criteria.items()
           if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 5}
    if bad:
        raise ReviewerError("invalid_structure", f"bad criteria values: {bad}")

    flags = obj.get("risk_flags", [])
    if not isinstance(flags, list) or not all(isinstance(f, str) for f in flags):
        raise ReviewerError("invalid_structure", "risk_flags not a string list")

    notes = obj.get("notes", "")
    if not isinstance(notes, str):
        raise ReviewerError("invalid_structure", "notes not a string")

    return {
        "decision": decision,
        "quality_score": q,
        "confidence": float(conf),
        "criteria": dict(criteria),
        "risk_flags": flags,
        "notes": notes.strip(),
    }


# ---------------------------------------------------------------------------
# Single-record review + batch runner
# ---------------------------------------------------------------------------

def review_record(record: dict, config: ReviewerConfig, *,
                  transport=http_transport, now_fn=utc_now_iso) -> dict:
    """Review one record end-to-end; returns the normalized result.

    Raises ReviewerError on any provider/parse failure (callers decide how to
    route it; run_batch routes to reviewer_failure_result — never accept).
    """
    cat = category_of(record)
    messages = build_messages(record)
    raw = transport(config, messages)
    parsed = parse_review_response(raw, cat)
    verdict = rm.decide(parsed["criteria"], parsed["quality_score"],
                        parsed["confidence"], parsed["risk_flags"],
                        config.thresholds)
    result = {
        "record_id": record.get("id", ""),
        "category": cat,
        "review_mode": rm.REVIEW_MODE_AI,
        "decision_source": "semantic_ai",
        "decision": verdict["decision"],
        "decision_reasons": verdict["reasons"],
        "model_decision": parsed["decision"],
        "quality_score": parsed["quality_score"],
        "confidence": parsed["confidence"],
        "criteria": parsed["criteria"],
        "risk_flags": parsed["risk_flags"],
        "notes": parsed["notes"],
        "thresholds": config.thresholds.as_dict(),
        "reviewer": {
            "provider": config.provider,
            "model": config.model,
            "version": rm.REVIEW_VERSION,
        },
        "input_hash": rm.input_hash(record),
        "reviewed_at": now_fn(),
        "review_version": rm.REVIEW_VERSION,
    }
    problems = rm.validate_review_result(result, mode=rm.REVIEW_MODE_AI)
    if problems:  # internal invariant; indicates a bug, not a model issue
        raise ReviewerError("internal_inconsistency", "; ".join(problems))
    return result


def append_line(path: Path, entry: dict) -> None:
    """Crash-safe single-line append (mirrors review_ui.append_decision)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    import os
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def load_done_ids(out_path: Path) -> set[str]:
    if not out_path.exists():
        return set()
    done = set()
    for line in out_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            rid = entry.get("record_id")
            if rid:
                done.add(rid)
    return done


def run_batch(records: list[dict], config: ReviewerConfig, out_path: Path, *,
              min_quality: int = 7, max_tokens: int = 4096,
              limit: int | None = None, transport=http_transport,
              sleep=time.sleep, gate_fn=None, now_fn=utc_now_iso) -> dict:
    """Gate deterministically, then semantically review survivors.

    - Deterministic gates (sft_view.gate_record by default) run FIRST; gated
      records are rejected without ever reaching the model.
    - Resume-safe: record_ids already present in out_path are skipped.
    - Any ReviewerError becomes a failure result routed to `review`.
    """
    from . import sft_view
    if gate_fn is None:
        gate_fn = sft_view.gate_record

    done = load_done_ids(out_path)
    counts = {"accepted": 0, "reviewed": 0, "rejected": 0,
              "gated_out": 0, "failures": 0, "skipped_resume": 0}
    reviewed = 0
    for rec in records:
        if limit is not None and reviewed >= limit:
            break
        rid = rec.get("id", "")
        if rid in done:
            counts["skipped_resume"] += 1
            continue
        reasons = gate_fn(rec, max_tokens=max_tokens, min_quality=min_quality)
        if reasons:
            entry = {
                "record_id": rid,
                "review_mode": rm.REVIEW_MODE_AI,
                "decision_source": "deterministic_gate",
                "decision": rm.DECISION_REJECT,
                "gate_reasons": reasons,
                "input_hash": rm.input_hash(rec),
                "reviewed_at": now_fn(),
                "review_version": rm.REVIEW_VERSION,
                "notes": "rejected by deterministic gates before semantic review",
            }
            append_line(out_path, entry)
            counts["gated_out"] += 1
            continue
        reviewed += 1
        try:
            entry = review_record(rec, config, transport=transport,
                                  now_fn=now_fn)
            counts[{"accept": "accepted", "review": "reviewed",
                    "reject": "rejected"}[entry["decision"]]] += 1
        except ReviewerError as exc:
            entry = rm.reviewer_failure_result(
                rec, exc, now_iso=now_fn(), config_summary=config.summary(),
                record_hash=rm.input_hash(rec))
            counts["failures"] += 1
        append_line(out_path, entry)
    summary = {
        "out_path": str(out_path),
        "review_mode": rm.REVIEW_MODE_AI,
        "review_version": rm.REVIEW_VERSION,
        "gates": {"min_quality": min_quality, "max_tokens": max_tokens},
        "reviewer": config.summary(),
        "thresholds": config.thresholds.as_dict(),
        **counts,
    }
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI semantic reviewer (SFT)")
    parser.add_argument("--records", nargs="+", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--api-key-env", default=ReviewerConfig.api_key_env)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TRANSPORT_TIMEOUT_S)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--min-quality", type=int, default=7)
    parser.add_argument("--max-tokens", type=int, default=4096)
    args = parser.parse_args(argv)

    from .sft_view import load_records
    cfg = config_from_env()
    if args.base_url:
        cfg.base_url = args.base_url.rstrip("/")
    if args.model:
        cfg.model = args.model
    cfg.api_key_env = args.api_key_env
    cfg.temperature = args.temperature
    cfg.timeout_s = args.timeout
    cfg.max_retries = args.max_retries

    records = load_records([Path(p) for p in args.records])
    summary = run_batch(records, cfg, Path(args.out),
                        min_quality=args.min_quality,
                        max_tokens=args.max_tokens, limit=args.limit)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

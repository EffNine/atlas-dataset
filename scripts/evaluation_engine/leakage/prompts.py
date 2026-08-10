"""prompts.py — Protocol v2 shared prompt module (reference-free).

This is the SINGLE shared module (rule P4) from which every eval runner builds
a generation prompt. It enforces the Protocol v2 contract
(``docs/research/protocol_v2_transition.md`` §3.2–3.3):

* The generation prompt is built from the record ``problem`` field ONLY plus a
  family ``PolicyLock`` system message. The ``canonical_answer`` is NEVER
  rendered; the ``messages`` array is never read by this module.
* Every record must carry a non-empty ``canonical_answer`` (fail-closed).
* ``guard_reference_free`` runs on every prompt before it is returned (L2
  runtime guard); any violation raises ``ReferenceLeakError`` (fail closed).
* ``prompt_sha256`` / ``prompt_fingerprint`` are recorded per record so stored
  artifacts can be re-audited (L3).

Renderer
--------
A deterministic ChatML renderer (``TEMPLATE_VERSION =
"qwen2.5-chatml-deterministic-v1"``) reproduces the Qwen2.5 ChatML serialization
without a tokenizer, so prompts, hashes, and leak checks are fully
reproducible offline. When a real ``tokenizer`` object is supplied (inference
runners), ``tokenizer.apply_chat_template`` is used instead and the template
version is recorded from the tokenizer.

Deterministic, offline, stdlib-only. No QEE scoring logic is touched.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

# Deterministic ChatML renderer version (Qwen2.5 style, from the Protocol audit
# ``docs/research/protocol_audit_reference_leakage.md`` §2.4).
TEMPLATE_VERSION = "qwen2.5-chatml-deterministic-v1"
POLICY_LOCK_BLOCK_VERSION = "v1"

# Family system instructions. Values are policy-lock constants (Generation
# Policy Lock, ``docs/research/p8_generation_policy.md`` §4.1 for code). They
# are deterministic template values, not measured numbers.
SYSTEM_MESSAGES: dict[str, str] = {
    "code": (
        "You are an expert software engineer. Given the code issue, produce ONLY a "
        "unified diff (git patch) that fixes it. Your entire response must be a "
        'single unified diff beginning with "diff --git". Include the file headers '
        '("--- a/", "+++ b/"), the hunk header ("@@ ... @@"), and the changed '
        '"+"/"-" lines. Do not write prose, explanations, summaries, or code fences.'
    ),
    "math": (
        "You are a helpful assistant. Solve the problem step by step and state the "
        "final answer explicitly at the end of your response."
    ),
    "semantic": (
        "You are a helpful assistant. Answer the AI/ML concept question precisely "
        "and completely."
    ),
}

# Reference-derived token budget rule (Generation Policy Lock §4.3). Recorded
# in the policy-lock metadata block; applied identically to every arm.
BUDGET_RULE = "budget_i = min(4096, max(256, 128 + ceil(1.5 * N_tokens(reference_i))))"
BUDGET_FALLBACK = 1024
STOP_SEQ = "<|im_end|>"

# Guard parameters (Protocol v2 §3.3, risk R30).
_REFERENCE_PREFIX_FINGERPRINT = 60  # first N chars of the reference (normalized)
_FIRST_K_TOKENS = 32  # first K reference tokens (contiguous containment)
_LAST_K_TOKENS = 16  # last K reference tokens (defense against trailing gold)


class ReferenceLeakError(RuntimeError):
    """Raised when reference content is detected in a prompt (fail-closed)."""


# --------------------------------------------------------------------------- #
# Hashing / normalization
# --------------------------------------------------------------------------- #
def sha256_hex(text: str) -> str:
    """Deterministic SHA-256 hex digest of a UTF-8 string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_answer_sha256(record: dict) -> str:
    """SHA-256 of a record's canonical answer (recorded at build time)."""
    return sha256_hex(record.get("canonical_answer") or "")


def prompt_sha256(prompt: str) -> str:
    """SHA-256 of a rendered prompt (recorded per record for L3 audit)."""
    return sha256_hex(prompt)


def prompt_fingerprint(prompt: str) -> str:
    """Short, stable prompt fingerprint: ``sha256[:16]`` plus a length tag."""
    return f"{prompt_sha256(prompt)[:16]}:{len(prompt)}"


def collapse_whitespace(text: str) -> str:
    """Collapse all whitespace runs to single spaces (guard normalization)."""
    return re.sub(r"\s+", " ", text).strip()


def _fallback_tokens(text: str) -> list[str]:
    """Deterministic whitespace tokenization used when no tokenizer is
    available. Splits on whitespace so punctuation stays attached to words,
    matching a tokenizer's behaviour closely enough for containment checks."""
    return re.findall(r"\S+", text)


def _tokenize(text: str, tokenizer: Any | None) -> list[str]:
    if tokenizer is not None:
        ids = tokenizer.encode(text, add_special_tokens=False)
        return [str(i) for i in ids]
    return _fallback_tokens(text)


def _is_contiguous_subsequence(sub: list[str], stream: list[str]) -> bool:
    if not sub:
        return False
    n, m = len(stream), len(sub)
    if m > n:
        return False
    # Boyer-Moore-style coarse scan is unnecessary; plain window scan is fine
    # and deterministic.
    for i in range(n - m + 1):
        if stream[i : i + m] == sub:
            return True
    return False


# --------------------------------------------------------------------------- #
# Renderer
# --------------------------------------------------------------------------- #
def render_chatml_qwen25(
    system_message: str, user_message: str, add_generation_prompt: bool = True
) -> str:
    """Deterministic Qwen2.5 ChatML serialization (no tokenizer).

    Mirrors the serialized format captured in the protocol audit §2.4:
    ``<|im_start|>system\\n{system}<|im_end|>\\n<|im_start|>user\\n{user}
    <|im_end|>\\n<|im_start|>assistant\\n``.
    """
    parts = [
        f"<|im_start|>system\n{system_message}<|im_end|>\n",
        f"<|im_start|>user\n{user_message}<|im_end|>\n",
    ]
    if add_generation_prompt:
        parts.append("<|im_start|>assistant\n")
    return "".join(parts)


def render_with_tokenizer(
    tokenizer: Any, system_message: str, user_message: str
) -> str:
    """Render using a real tokenizer's chat template (inference runners).

    The tokenizer must expose ``apply_chat_template``. The template version is
    recorded separately in the run metadata (P6, tokenizer pinning).
    """
    if not hasattr(tokenizer, "apply_chat_template"):
        raise TypeError("tokenizer must implement apply_chat_template")
    return tokenizer.apply_chat_template(
        [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ],
        tokenize=False,
        add_generation_prompt=True,
    )


# --------------------------------------------------------------------------- #
# Policy lock
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PolicyLock:
    """Generation Policy Lock (Protocol v2 §3.6) — family inference policy.

    Applied identically to every arm of a comparison and recorded as a
    ``generation_policy_lock`` metadata block.
    """

    family: str
    system_message_text: str
    budget_rule: str = BUDGET_RULE
    budget_fallback: int = BUDGET_FALLBACK
    stop_sequence: str = STOP_SEQ
    template_version: str = TEMPLATE_VERSION

    def system_message(self, record: dict | None = None) -> dict:
        """System message dict; content comes ONLY from the lock, never the
        record (a record-supplied system message is a leak vector)."""
        return {"role": "system", "content": self.system_message_text}

    def to_block(self) -> dict[str, Any]:
        """Serializable metadata block recorded in run/validation metadata."""
        block = {
            "version": POLICY_LOCK_BLOCK_VERSION,
            "family": self.family,
            "system_message_sha256": sha256_hex(self.system_message_text),
            "budget_rule": self.budget_rule,
            "budget_fallback": self.budget_fallback,
            "stop_sequence": self.stop_sequence,
            "template_version": self.template_version,
        }
        block["policy_block_sha256"] = sha256_hex(
            __import__("json").dumps(
                block, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            )
        )
        return block


DEFAULT_POLICY_LOCKS: dict[str, PolicyLock] = {
    fam: PolicyLock(family=fam, system_message_text=text)
    for fam, text in SYSTEM_MESSAGES.items()
}


def get_policy_lock(family: str) -> PolicyLock:
    if family not in DEFAULT_POLICY_LOCKS:
        raise ValueError(
            f"unknown policy family {family!r}; expected one of "
            f"{sorted(DEFAULT_POLICY_LOCKS)}"
        )
    return DEFAULT_POLICY_LOCKS[family]


# --------------------------------------------------------------------------- #
# Runtime prompt guard (L2, fail-closed)
# --------------------------------------------------------------------------- #
def guard_reference_free(
    prompt: str,
    reference: str,
    record_id: str = "unknown",
    tokenizer: Any | None = None,
) -> None:
    """Assert the reference answer is absent from the rendered prompt.

    Checks, all on whitespace-normalized text:
      1. full normalized reference is not a substring of the normalized prompt,
      2. reference prefix fingerprints (first 60 chars, first line, last line)
         do not appear in the normalized prompt,
      3. the first ``_FIRST_K_TOKENS`` reference tokens are not a contiguous
         subsequence of the prompt token stream (and the last
         ``_LAST_K_TOKENS`` tokens likewise).

    Any positive hit raises ``ReferenceLeakError``. A hit means the caller must
    mark the record HOLD and abort the run (fail closed).
    """
    ref = reference or ""
    if not ref.strip():
        raise ReferenceLeakError(
            f"[guard] {record_id}: empty reference; cannot verify reference-free"
        )

    norm_prompt = collapse_whitespace(prompt)
    norm_ref = collapse_whitespace(ref)

    # 1. Full reference containment.
    if norm_ref and norm_ref in norm_prompt:
        raise ReferenceLeakError(
            f"[guard] {record_id}: full canonical_answer found in prompt"
        )

    # 2. Prefix/line fingerprints.
    fingerprints = [
        norm_ref[:_REFERENCE_PREFIX_FINGERPRINT],
        collapse_whitespace(ref.splitlines()[0]) if ref.splitlines() else norm_ref,
        collapse_whitespace(ref.splitlines()[-1]) if ref.splitlines() else norm_ref,
    ]
    for fp in fingerprints:
        if fp and len(fp) >= 8 and fp in norm_prompt:
            raise ReferenceLeakError(
                f"[guard] {record_id}: reference fingerprint {fp[:24]!r} found in prompt"
            )

    # 3. Tokenized containment (first K and last K reference tokens).
    ref_tokens = _tokenize(ref, tokenizer)
    prompt_tokens = _tokenize(prompt, tokenizer)
    checks = [
        (ref_tokens[:_FIRST_K_TOKENS], "first-32"),
        (ref_tokens[-_LAST_K_TOKENS:], "last-16"),
    ]
    for window, label in checks:
        if len(window) >= 4 and _is_contiguous_subsequence(window, prompt_tokens):
            raise ReferenceLeakError(
                f"[guard] {record_id}: reference token window ({label}) found in prompt"
            )


# --------------------------------------------------------------------------- #
# Reference-free prompt builder (shared contract, Protocol v2 §3.3)
# --------------------------------------------------------------------------- #
def build_reference_free_prompt(
    record: dict,
    policy: PolicyLock | None = None,
    tokenizer: Any | None = None,
) -> str:
    """Build the reference-free generation prompt for an eval record.

    Contract:
      * ``record["canonical_answer"]`` must be present and non-empty, else a
        ``ReferenceLeakError`` is raised (fail-closed, record -> HOLD).
      * Prompt text comes ONLY from ``record["problem"]`` and the policy system
        message. ``messages`` and ``context`` are never read.
      * The prompt is passed through ``guard_reference_free`` before return;
        any leak raises (run aborted).
    """
    reference = record.get("canonical_answer")
    if not isinstance(reference, str) or not reference.strip():
        raise ReferenceLeakError(
            f"[builder] {record.get('record_id', 'unknown')}: "
            "missing/empty canonical_answer (invalid for evaluation)"
        )

    problem = record.get("problem")
    if not isinstance(problem, str) or not problem.strip():
        raise ReferenceLeakError(
            f"[builder] {record.get('record_id', 'unknown')}: "
            "missing/empty problem (cannot build prompt)"
        )

    policy = policy or get_policy_lock(record.get("family", "semantic"))
    system_msg = policy.system_message(record)

    if tokenizer is not None:
        prompt = render_with_tokenizer(
            tokenizer, system_msg["content"], problem
        )
    else:
        prompt = render_chatml_qwen25(system_msg["content"], problem)

    guard_reference_free(prompt, reference, str(record.get("record_id", "unknown")),
                         tokenizer=tokenizer)
    return prompt


def prompt_meta(prompt: str) -> dict[str, str]:
    """Per-record prompt metadata recorded into per-example artifacts."""
    h = prompt_sha256(prompt)
    return {
        "prompt_sha256": h,
        "prompt_fingerprint": f"{h[:16]}:{len(prompt)}",
        "prompt_length": str(len(prompt)),
    }

"""evaluation_engine.leakage — Protocol v2 reference-leakage prevention and
detection.

Implements the three detection layers defined in Protocol v2
(``docs/research/protocol_v2_transition.md`` §3.4–3.5):

* L1  static schema scan   -> ``scan.py`` (pre-flight, per eval set),
* L2  runtime prompt guard -> ``prompts.guard_reference_free`` (per record,
                             fail-closed),
* L3  post-hoc audit       -> ``audit.py`` (re-derives prompts and verifies
                             recorded hashes).

All modules are deterministic, offline, and stdlib-only. The prompt builder
lives in this single shared module (rule P4) and is the ONLY sanctioned way to
render a Protocol v2 generation prompt.
"""

from .prompts import (
    DEFAULT_POLICY_LOCKS,
    POLICY_LOCK_BLOCK_VERSION,
    TEMPLATE_VERSION,
    PolicyLock,
    ReferenceLeakError,
    build_reference_free_prompt,
    canonical_answer_sha256,
    get_policy_lock,
    guard_reference_free,
    prompt_fingerprint,
    prompt_sha256,
)

__all__ = [
    "DEFAULT_POLICY_LOCKS",
    "POLICY_LOCK_BLOCK_VERSION",
    "TEMPLATE_VERSION",
    "PolicyLock",
    "ReferenceLeakError",
    "build_reference_free_prompt",
    "canonical_answer_sha256",
    "get_policy_lock",
    "guard_reference_free",
    "prompt_fingerprint",
    "prompt_sha256",
]

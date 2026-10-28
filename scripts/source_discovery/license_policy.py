"""License-state policy for Source Discovery v1.0.

Reuses Atlas canonical license helpers (imported, never redefined):
  - atlas_constants.is_denied_license
  - atlas_constants.is_share_alike
  - atlas_constants.requires_attribution

License states (source-discovery scope only, not Atlas-wide):
  ALLOW      — declared license explicitly permits reuse with at most
               attribution (CC0, PDM, MIT, Apache-2.0, BSD, CC-BY-* excl.
               NC/ND, ODC-BY where stated). Attribution obligation is tracked
               separately and never waived.
  RESTRICTED — reuse allowed only under conditions beyond attribution:
               share-alike (CC-BY-SA, ODC-ODbL), research-only, no-redistribute
               ambiguity, or other stated limits. Requires explicit opt-in for
               any training-ready corpus.
  UNKNOWN    — license missing, "unknown", unverifiable, or evidence absent.
               Kept in the registry, EXCLUDED from training-ready by default.
  BLOCKED    — NC/ND/proprietary/all-rights-reserved or otherwise explicitly
               denying reuse. Never training-ready.

This module never claims legal permission beyond what the source declares.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atlas_constants import (  # noqa: E402
    is_denied_license,
    is_share_alike,
    requires_attribution,
)

SD_LICENSE_STATES = frozenset({"ALLOW", "RESTRICTED", "UNKNOWN", "BLOCKED"})

_UNKNOWN_TOKENS = frozenset({"", "unknown", "unspecified", "unverified",
                             "tbd", "n/a", "none stated"})


def classify_license(declared_license: str,
                     license_evidence: str = "") -> tuple[str, str]:
    """Map a declared license string to (state, reason).

    Never raises on bad input: non-strings and empties are UNKNOWN.
    """
    if not isinstance(declared_license, str):
        return "UNKNOWN", "non_string_license_field"
    low = declared_license.strip().lower()
    if low in _UNKNOWN_TOKENS:
        return "UNKNOWN", "license_not_stated"
    # Denied patterns win (NC / ND / proprietary / all-rights-reserved).
    # is_denied_license also matches "unknown", already handled above.
    if is_denied_license(declared_license):
        return "BLOCKED", "denied_pattern_nc_nd_proprietary_or_all_rights"
    if is_share_alike(declared_license):
        return "RESTRICTED", "share_alike_obligation"
    ev = (license_evidence or "").lower()
    if "research-only" in low or "research only" in low \
            or "research-only" in ev or "non-commercial" in ev \
            or "no redistribution" in ev or "no-redistribution" in ev:
        return "RESTRICTED", "research_only_or_redistribution_limit"
    if requires_attribution(declared_license):
        # Attribution alone does not block reuse; track the obligation but
        # keep the source usable. CC-BY / MIT / Apache-2.0 land here.
        return "ALLOW", "allows_reuse_with_attribution"
    return "ALLOW", "permissive_or_public_domain"


def is_training_ready_license(state: str) -> bool:
    """Only ALLOW is training-ready by default.

    RESTRICTED needs explicit opt-in, UNKNOWN is kept but excluded,
    BLOCKED is never eligible.
    """
    return state == "ALLOW"

# Training Dataset Contract

> **Atlas Dataset Foundation — Phase 5D**
> Defines the contractual requirements before any training dataset can be generated.
> This contract enforces governance, reproducibility, and quality gates.
> **No training dataset generation is authorized until all conditions are met.**

---

## 1. Purpose

This contract defines the **required preconditions** and **forbidden states** for training dataset generation from the Atlas curated dataset. It serves as the authoritative governance document for the transition between curation and training.

**Readiness is evaluated by** `scripts/training_readiness.py`.
**Release decisions are simulated by** `scripts/release_decision_simulator.py`.

---

## 2. Required Before Training

All of the following conditions MUST be satisfied before any training dataset can be generated:

### 2.1 Approved Lifecycle State

| Condition | Requirement | Verification |
|-----------|-------------|-------------|
| Record lifecycle | Every record used for training must have `verification_status = "approved"` | Review manifest `v0.2_review_manifest.json` |
| Approval rate | ≥ 80% of records must be approved (target: 100%) | `counts.approved / total_records >= 0.80` |
| No pending | Zero records in `pending` status | `counts.pending == 0` |
| No unresolved revisions | Zero records in `needs_revision` status | `counts.needs_revision == 0` |

### 2.2 Valid License

| Condition | Requirement | Verification |
|-----------|-------------|-------------|
| License gate | Every record must carry a non-denied, non-unknown license | `is_denied_license(lic) == False` for all records |
| Attribution | Records under attribution-required licenses must carry attribution text | `source_attribution.attribution_text` must be non-empty |
| Share-alike tracking | CC-BY-SA records must be tracked for share-alike obligations | `source_attribution.share_alike == true` |

### 2.3 Lineage

| Condition | Requirement | Verification |
|-----------|-------------|-------------|
| Source lineage | Every record must have a complete `lineage` object | `lineage.source` and `lineage.transformations` must exist |
| Dataset reference | `lineage.curated_dataset` must reference the source release version | e.g., `"curated/v0.2"` |
| Training view reference | `lineage.training_view` must reference the target model view | e.g., `"qwen"`, `"llama"`, `"deepseek"` |

### 2.4 Evaluation Evidence

| Condition | Requirement | Verification |
|-----------|-------------|-------------|
| Benchmark registry | At least one internal benchmark must be registered | `benchmark_registry.json` internal benchmarks ≥ 1 |
| Reproducibility | At least one benchmark must have reproducibility data | `reproducibility_hash` or checksum present |
| Evaluation reports | At least one evaluation report must exist | `evaluation/*_report.json` or `evaluation/*.json` |

### 2.5 Reproducible Checksum

| Condition | Requirement | Verification |
|-----------|-------------|-------------|
| Dataset checksum | The curated dataset must have a reproducible SHA-256 checksum | `engine_checksums.json` or `checksums_v0.1.json` |
| Release chain | Release hash chain must be intact | `atlas release --chain-verify == PASS` |

### 2.6 Training Recipe Reference

| Condition | Requirement | Verification |
|-----------|-------------|-------------|
| Recipe exists | A training recipe must be registered for the target model | `training_recipe_registry.json` contains the recipe |
| Recipe valid | Recipe must have complete filter, tokenization, and validation policies | All fields non-null |
| Recipe version | Recipe must reference the dataset version being used | `recipe.dataset_version == current_version` |

---

## 3. Forbidden

The following states explicitly BLOCK training dataset generation.

### 3.1 Forbidden Record States

| State | Why Blocked |
|-------|-------------|
| Any record with `verification_status = "pending"` | Record has not been human-reviewed; quality unknown |
| Any record with `verification_status = "rejected"` | Record has been human-rejected; must not be used |
| Any record with `verification_status = "needs_revision"` | Record has unresolved revision requests |
| Any record with `verification_status = "unknown"` | Status could not be determined |

### 3.2 Forbidden Provenance

| State | Why Blocked |
|-------|-------------|
| Records missing `source_attribution` | Cannot verify source or license |
| Records with `source_attribution.source_id` empty | Source is unknown |
| Records with denied license in `source_attribution.license` | Commercial or redistribution restrictions |
| Records from rejected sources (`status = "rejected"` in source registry) | Source has been deemed unsuitable |

### 3.3 Forbidden Review State

| State | Why Blocked |
|-------|-------------|
| `review_gate_status.status == "BLOCKED"` | Review gate explicitly blocks training |
| `review_completed == False` | Review cycle not yet completed |
| Human review not yet authoritative | `human_decision_authoritative != True` |

### 3.4 Forbidden License States

| License Pattern | Reason |
|-----------------|--------|
| `cc-by-nc-*` | Non-commercial — incompatible with training use |
| `cc-by-nd-*` | No-derivatives — cannot reshape into training format |
| `proprietary` | No redistribution/derivative rights granted |
| `all-rights-reserved` | No permissions granted |
| `unknown` | Cannot confirm fitness for use |

### 3.5 Forbidden Release States

| State | Why Blocked |
|-------|-------------|
| Release gates not passed | Training can only proceed from a gate-passing release |
| Missing release chain | Cannot verify dataset integrity across versions |
| Release hash mismatch | Dataset may have been tampered with or corrupted |

---

## 4. Enforcement

| Mechanism | What it enforces |
|-----------|------------------|
| `scripts/training_readiness.py` | Automated gate evaluation; produces `metadata/training_readiness_report.json` |
| `scripts/release_decision_simulator.py` | Simulated release decision with full rationale |
| `scripts/atlas.py self-test` | Permanent invariant checks including license gate integrity |
| `scripts/validate_architecture.py` | Architecture policy (forbidden imports, circular deps, duplicated constants) |
| `tests/probe_training_readiness.py` | Verification probe proving no dataset/review/release changes |

---

## 5. Governance Rules (Machine-Readable)

```json
{
  "contract_version": "1.0",
  "required_conditions": [
    "approval_rate >= 0.80",
    "pending_count == 0",
    "needs_revision_count == 0",
    "denied_license_count == 0",
    "unknown_license_count == 0",
    "missing_lineage_count == 0",
    "missing_provenance_count == 0",
    "benchmark_count >= 1",
    "evaluation_reproducible == true",
    "recipe_exists == true",
    "release_chain_verified == true"
  ],
  "forbidden_states": [
    "any_pending_record",
    "any_rejected_record",
    "any_needs_revision_record",
    "any_unknown_license",
    "any_denied_license",
    "any_missing_lineage",
    "any_unresolved_provenance",
    "review_not_completed",
    "release_gates_not_passed"
  ],
  "verdict_mapping": {
    "READY": "all required conditions met, no forbidden states — training authorized",
    "CONDITIONAL": "all hard gates pass, but warnings exist — training allowed with caution",
    "BLOCKED": "one or more hard gates fail — training forbidden"
  }
}
```

---

## 6. Change Process

This contract is version-controlled and lives at `docs/specs/training_dataset_contract.md`.

| Change Type | Approval Required |
|-------------|-------------------|
| Relaxing a required condition | Phase governance review + human sign-off |
| Adding a forbidden state | Phase governance review |
| Adding a new required condition | Phase governance review |
| Correcting documentation errors | PR review only |

---

*This contract is part of the Atlas Dataset Foundation governance framework.
No training dataset generation may proceed without satisfying all conditions herein.*

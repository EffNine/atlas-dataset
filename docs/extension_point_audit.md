# Extension Point Audit — Model-Agnostic Verification

> Phase 4C.0 — Architecture Consolidation & Dependency Unification
> Generated: 2026-07-28

This audit verifies that Atlas datasets remain model-agnostic and identifies any assumptions tied to specific models (particularly Qwen).

---

## 1. Core Principle: Model-Agnostic by Design

The Atlas README states: *"The dataset is the long-term asset. Models are replaceable."*

Canonical records are stored in plain JSONL. Model-specific formatting is a downstream concern, handled by:
- `scripts/convert_format.py` — consumes canonical JSONL, emits model-specific JSONL
- `configs/formatting/templates.json` — declarative template definitions for 6 model families

---

## 2. Supported Model Formats

| Format | Targets | Builder | Config-Driven? |
|--------|---------|---------|---------------|
| `qwen_chatml` | Qwen2/2.5/3, future Qwen | ChatML | ✅ `templates.json` |
| `llama_instruction` | Llama-3/3.1 | Llama | ✅ `templates.json` |
| `mistral_instruct` | Mistral-7B, Mixtral | Llama-variant | ✅ `templates.json` |
| `gemma_instruct` | Gemma-2/3 | Gemma | ✅ `templates.json` |
| `sharegpt` | OpenChat, vLLM, many stacks | ShareGPT | ✅ `templates.json` |
| `alpaca` | Alpaca, llama.cpp | Alpaca | ✅ `templates.json` |

**Adding a new model** requires only a new entry in `configs/formatting/templates.json`. No code changes needed. This satisfies the model-agnostic mandate.

---

## 3. Training View Eligibility

### Schema Field: `training_view_eligibility`
- **Defined in:** `schemas/knowledge_object_schema.json`
- **Required keys:** `qwen`, `llama`, `deepseek` (all `boolean`)
- **Enforced by:** `validate_knowledge_object.py:structural_errors()` requires **exactly** these 3 keys

### Finding E-1: Exact set enforcement is a future-model constraint
The schema and validators require **exactly** `{qwen, llama, deepseek}`. Adding a new model (Gemma, Mistral, future Llama, future Qwen) requires:
1. Schema migration to add the new key
2. Update `validate_knowledge_object.py` TVE set
3. Update `atlas.py` self-test TVE invariant
4. Update all existing records (via migration) to include the new key

### Finding E-2: `training_view_eligibility` could be extensible
The current design uses a fixed set of boolean fields. An alternative design would use a list-based approach:
```json
"training_view_eligibility": ["qwen", "llama", "deepseek"]
```
This would require zero schema changes to add a new model — the list naturally accommodates new entries.

### Finding E-3: No training_view_eligibility automation
There is no automation that sets `training_view_eligibility` based on source license, category, or quality. It must be explicitly set during curation. This is correct (human judgment required) but means new records risk having incomplete eligibility.

---

## 4. Qwen-Specific Assumptions Found

| # | Location | Assumption | Severity | Impact |
|---|----------|-----------|----------|--------|
| **A1** | `configs/training/qlora_qwen3_8b.yaml` | Full config targets Qwen3-8B | **Reference only** — file header says "MODEL TRAINING IS PAUSED" and "swap `model_name_or_path` and the chat template reference to target Llama/DeepSeek/Mistral" | **None** — documented as a template, not a hard requirement |
| **A2** | `training_views/qwen/README.md` | Placeholder mentions "Eligible pilot objects: 100/100" | **None** — all training_views/ are placeholders with equivalent structure for qwen, llama, deepseek | **None** |
| **A3** | `training_view_eligibility` keys | Schema requires `qwen` key | **Low** — required by schema, but only 3 models are listed | **Medium** — adding any new model requires migration |
| **A4** | `ATLAS_SUBSYSTEM_CONTRACTS.md` line 34 | `training_view_eligibility` keys must be exactly `{qwen, llama, deepseek}` | **Documentation** — reflects current schema | **Medium** — will be outdated when new models are added |

### Verdict
**No hard Qwen-specific assumptions that would prevent training with other models.** The training config for Qwen3-8B is explicitly marked as a reference/template. The canonical data format is fully model-agnostic. The only friction is the `training_view_eligibility` exact-key requirement, which requires schema migration for new models.

---

## 5. Verification: Model-Agnostic Data Pipeline

| Pipeline Stage | Model-Agnostic? | Evidence |
|----------------|----------------|----------|
| Raw data ingestion | ✅ | No model-specific processing |
| Schema validation | ✅ | `schemas/dataset_schema.json` has no model-specific fields |
| Quality scoring | ✅ | `quality_score.py` evaluates content only, no model template awareness |
| Curated storage | ✅ | Canonical JSONL, no chat template applied |
| Knowledge Packs | ✅ | Packs contain canonical records only |
| Knowledge Collections | ✅ | Aggregate canonical records |
| Release manifests | ✅ | Release metadata has no model-specific fields |
| AQL queries | ✅ | Queries operate on canonical schema, not model-specific fields |
| Payload resolution | ✅ | No model awareness in lookup logic |
| **Training Views** | ✅ | Generated downstream from templates; canonical data untouched |
| **Convert Format** | ✅ | Config-driven; adding a model is a config edit |

**Conclusion: Atlas is fully model-agnostic in its canonical data layer.**

---

## 6. Future Model Compatibility

| Model | Current Support | Actions Needed |
|-------|----------------|----------------|
| **Qwen3** | ✅ `qwen_chatml` format exists, training config exists (reference) | None |
| **Qwen4** | ✅ New entry in `templates.json` | Add template, add to `training_view_eligibility` via migration |
| **Llama-4** | ✅ New entry in `templates.json` or reuses `llama_instruction` | Add to `training_view_eligibility` via migration |
| **DeepSeek-V3** | ✅ Literally has `training_views/deepseek/` | Add template, add to `training_view_eligibility` |
| **Mistral 8B** | ✅ `mistral_instruct` format exists | Add to `training_view_eligibility` via migration |
| **Gemma-4** | ✅ `gemma_instruct` format exists | Add to `training_view_eligibility` via migration |
| **Future unknown** | 🔄 List-based TVE recommended | Schema migration + record migration |

### Recommendations
1. **Change `training_view_eligibility` from fixed-key object to a list of strings** to avoid schema migration on every new model addition
2. **Add a `models/` config directory** listing supported models with their template mappings
3. **Document the model-addition process** in `docs/specs/training_recipe_spec.md`

---

## 7. Summary

| Check | Status |
|-------|--------|
| Canonical data is model-agnostic | ✅ **Pass** |
| No Qwen-specific hardcoding in pipeline | ✅ **Pass** |
| Templates are declarative (config-editable) | ✅ **Pass** |
| `training_view_eligibility` supports 3 current models | ✅ **Pass** (but needs migration for more) |
| Training views are disposable (regenerable from canonical) | ✅ **Pass** |
| Model training is user's choice (paused by mandate, not architecture) | ✅ **Pass** |

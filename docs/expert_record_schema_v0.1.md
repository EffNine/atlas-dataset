# Atlas Expert Record Schema v0.1

## Purpose

Standardize the training format for all future expert data ingested into Atlas.
This schema is additive and sits above the canonical Atlas record concepts in
`schemas/dataset_schema.json` and `schemas/knowledge_object_schema.json`.

It applies to expert-domain sources only:
- software engineering
- AI/ML
- mathematics
- science
- system engineering

## Design Rules

1. **Model-agnostic**: schema stays independent of Qwen/Llama/DeepSeek/etc.
2. **Provenance-first**: every expert record must carry source, license, and lineage fields.
3. **Tier-aware**: expert tier E1/E2/E3 is stored explicitly and used downstream for balancing.
4. **Verification-aware**: store method and evidence, not just a boolean.
5. **Trainable**: the schema must convert cleanly to SFT turns without guesswork.

## Canonical Expert Record

```json
{
  "id": "expert_swe_000042",
  "domain": "software_engineering",
  "expert_tier": "E2",
  "difficulty": 3,
  "type": "qa",
  "source": {
    "source_id": "expert-swe-001",
    "name": "SWE-bench verified",
    "url": "https://huggingface.co/datasets/princeton-nlp/SWE-bench",
    "license": "MIT",
    "accessed_at": "2026-08-02",
    "version": "2025-06-01-snapshot"
  },
  "license": "MIT",
  "attribution": "Princeton NLP. SWE-bench is MIT-licensed.",
  "problem": "<problem/question/context prompt>",
  "context": "<optional supporting context>",
  "solution": "<answer/explanation/code/reasoning>",
  "verification": {
    "method": "gold_patch",
    "status": "verified",
    "evidence": "FAIL_TO_PASS=2, PASS_TO_PASS=38",
    "reviewer": null,
    "reviewed_at": null
  },
  "provenance": {
    "original_id": "swe-bench-instance-1234",
    "ingestion_pipeline": "atlas-expert-v1",
    "transformations": [
      "raw_download",
      "instance_to_example",
      "quality_score",
      "expert_tier_classify"
    ],
    "difficulty_classifier_version": "1.2.0",
    "expert_layer_version": "0.1.0"
  },
  "metadata": {
    "language": "en",
    "subdomains": ["debugging", "python", "patch-generation"],
    "quality_score": 9,
    "synthetic": false,
    "model_generated": false,
    "notes": "Real issue-to-patch example with verified patch."
  },
  "messages": [
    { "role": "user", "content": "<problem optionally with context>" },
    { "role": "assistant", "content": "<solution>" }
  ],
  "created_at": "2026-08-02",
  "curated": true
}
```

## Field Definitions

### Core Identity

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Stable expert record id. Recommended: `expert_<domain>_<seq>` or source-derived id with prefix. |
| `domain` | string | yes | One of: `software_engineering`, `ai_machine_learning`, `mathematics`, `science`, `system_engineering`. |
| `expert_tier` | string | yes | `E1`, `E2`, or `E3`. |
| `difficulty` | integer | yes | 1-5 Atlas difficulty scale. 0 is not allowed for expert records; use null filtering instead. |
| `type` | string | yes | Structural shape: `qa`, `instruction`, `reasoning`, `code`. |

### Source and License

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source.source_id` | string | yes | Shortlist/source registry id. |
| `source.name` | string | yes | Human-readable source name. |
| `source.url` | string | yes | Canonical upstream URL or path. |
| `source.license` | string | yes | SPDX or readable license at time of access. |
| `source.accessed_at` | string | yes | ISO-8601 access/ingestion date. |
| `source.version` | string | no | Pinned source version, commit, dump date, or doc snapshot. |
| `license` | string | yes | Resolved record-level license. Must not be `unknown` in curated expert data. |
| `attribution` | string | yes | Required attribution text for share-alike or attribution-required sources. Empty only for permissive no-attribution sources. |

### Problem, Context, and Solution

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `problem` | string | yes | Main question, issue, task, or prompt. |
| `context` | string | no | Supporting context such as repo snippet, paper excerpt, system description, or constraints. |
| `solution` | string | yes | Expert answer: explanation, derivation, patch, design, or reasoning chain. |

### Verification

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `verification.method` | string | yes | How the solution was validated. Examples: `gold_patch`, `unit_test`, `auto_grader`, `human_review`, `peer_review`, `verified_solution_set`, `doc_template`. |
| `verification.status` | string | yes | `verified`, `unverified`, `needs_review`, `rejected`. |
| `verification.evidence` | string | no | Concrete evidence: test ids, pass/fail counts, grader output, reviewer notes. |
| `verification.reviewer` | string | no | Reviewer identifier if human-reviewed. |
| `verification.reviewed_at` | string | no | ISO-8601 review date. |

### Provenance and Transformations

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `provenance.original_id` | string | yes | Upstream raw record id before transformation. |
| `provenance.ingestion_pipeline` | string | yes | Pipeline name/version, e.g. `atlas-expert-v1`. |
| `provenance.transformations` | array of strings | yes | Ordered transformation steps applied. |
| `provenance.difficulty_classifier_version` | string | no | Classifier version if difficulty is derived. |
| `provenance.expert_layer_version` | string | no | Expert layer version that assigned `expert_tier`. |

### Metadata and Trainability

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `metadata.language` | string | yes | ISO 639-1 language, default `en`. |
| `metadata.subdomains` | array of strings | no | Finer domain tags such as `debugging`, `transformers`, `olympiad`. |
| `metadata.quality_score` | integer | yes | 0-10 quality score. Expert target: >= 7. |
| `metadata.synthetic` | boolean | yes | `true` if generated by model/synthetic pipeline. Expert sources should mostly be `false`. |
| `metadata.model_generated` | boolean | yes | `true` if upstream content was model-generated. |
| `metadata.notes` | string | no | Caveats, review notes, or edge cases. |

### Conversation Format

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `messages` | array | yes | Ordered training turns. Minimum: one user turn and one assistant turn. |
| `messages[].role` | string | yes | `user` or `assistant`. |
| `messages[].content` | string | yes | Turn text. For code-heavy examples, include code in assistant turn. |

### Lifecycle

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `created_at` | string | yes | ISO-8601 record creation timestamp. |
| `curated` | boolean | yes | `true` only after expert-layer and review gates. |

## Usage Rules

1. **No unknown licenses in expert curated data.** Resolve before promotion.
2. **No bare difficulty without provenance.** Store classifier version if difficulty is automated.
3. **Expert tier is mandatory.** Do not create expert records without `expert_tier`.
4. **Verification evidence is preferred over bare status.** If a method has no evidence, record that explicitly.
5. **Context is optional but encouraged for hard examples.** Frontier/advanced examples degrade quickly without context.
6. **Conversion downstream only.** Do not store model-specific templates in canonical expert records.

## Validation Rules

- `id` unique per expert record.
- `domain` must be one of the five expert domains.
- `expert_tier` must be `E1`, `E2`, or `E3`.
- `difficulty` must be between 1 and 5 inclusive.
- `verification.status == verified` requires non-empty `verification.method`.
- `license` must not be `unknown`.
- `messages` must contain at least one `user` and one `assistant` turn.
- `source.url` must be present unless the source is fully internal and explicitly approved.

## Downstream Mapping

| Expert Schema Field | Typical Training Use |
|---------------------|----------------------|
| `problem` | user prompt / instruction |
| `context` | system prompt prefix, document preamble, or repo context |
| `solution` | assistant response / target output |
| `verification` | quality filtering, eval sampling, curriculum pacing |
| `expert_tier` | E1/E2/E3 mix balancing in training views |
| `difficulty` | pacing, curriculum order, hardness-stratified sampling |
| `metadata.subdomains` | domain-specific packing and eval splits |

# Atlas v0.2 Review Checklist

Use one checklist pass per record before writing a final decision.

## Accuracy
- [ ] assistant answer is factually correct
- [ ] no hallucinated definitions, citations, or claims

## Usefulness
- [ ] record is useful for training future LLMs
- [ ] content matches its declared category and subcategory

## Consistency
- [ ] difficulty matches content complexity
- [ ] `source_attribution.source_id` resolves to a known Phase 2 source
- [ ] license statement is coherent with source provenance

## Safety
- [ ] no unsafe, biased, or non-trainable content
- [ ] no unresolved PII/privacy concerns

## Decision Selection
- [ ] `approved` if all above pass and record is ready to ship
- [ ] `needs_revision` if useful but fixable issues remain; include revision notes
- [ ] `rejected` if record is wrong, unsafe, or unsalvageable; include reason

## Documentation
- [ ] add reviewer identifier and timestamp
- [ ] add concise evidence-based notes
- [ ] do not leave `review_status` as `pending` after review

# Atlas Query Language Specification

This document freezes the Atlas Query Language contract for Atlas v1.0.

#

# 1. Guarantees

- Deterministic execution: identical query + identical data must return identical results.
- Safe evaluation: queries are parsed, never evaluated as code.
- Empty condition support: empty query selects all.
- Consistent behavior across tag-style and semantic-equivalent SQL-style forms.

#

# 2. Valid Field Names

`category`, `subcategory`, `type`, `license`, `quality_score`, `verification_status`, `verified`, `difficulty`, `knowledge_type`, `language`, `source_id`, `tags`

#

# 3. Operators

- `=`, `>=`, `<=`, `>`, `<`, `!=`
- `in`
- `exists`

#

# 4. Syntax Variants

## 4.1 Tag Style

Primary form. Conditions separated by whitespace.

- equality shorthand: `field:value`
- operator form: `field>=value`
- boolean aliases: `verified:true`
- IN lists: `category in (01_foundation, 02_software_engineering)`
- bare field: treated as `exists`

Field aliases normalize to canonical form: `cat`→`category`, `q`→`quality_score`, `lic`→`license`, `ver`/`status`→`verification_status`, `source`→`source_id`, etc.

## 4.2 SQL Style

```sql
SELECT [fields|*]
[WHERE condition (AND condition)*]
[GROUP BY field]
[ORDER BY field [ASC|DESC]]
[LIMIT N]
[OFFSET N]
```

Aggregation functions: COUNT, MIN, MAX, AVG, SUM.

#

# 5. Reserved Keywords

SELECT, WHERE, GROUP, BY, ORDER, LIMIT, OFFSET, ASC, DESC, AND, OR, IN, NOT, AS, COUNT, MIN, MAX, AVG, SUM

#

# 6. Execution Rules

- Comparison cooperates with typed values for integers and floats; numeric coercion may convert string numeric values when required for operator evaluation.
- String comparison is case-insensitive unless explicitly required otherwise.
- Missing fields never match operators except `exists`, which requires presence and truthy value.
- Grouping sorts grouped values lexicographically.
- Ordering treats equal keys as stable lexicographic secondary sort unless explicit secondary key provided.
- LIMIT and OFFSET are applied after filtering, grouping, and ordering.

#

# 7. Determinism Requirements

- No hidden mutation occurs during query execution.
- Query plans must not depend on random input or filesystem ordering beyond lexicographic/timestamp order declared explicitly.
- Replaying the same query must yield identical result shapes and order given identical dataset state.

#

# 8. Extension Constraints

- New reserved keywords require ADR and migration compatibility plan.
- New operators must remain safe and deterministic and require spec update.

#

# 9. Related Documents

- Main spec Section 12.
- Schema field definitions in `knowledge_object_schema.md`.
- `schemas/chat_schema.json` for nested querying vocabulary.

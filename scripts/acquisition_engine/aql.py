#!/usr/bin/env python3
"""
aql.py — Atlas Query Language (AQL).

AQL is a simple, deterministic query language for selecting subsets of records
from the Atlas dataset. It is designed to be:

  * Human-readable and writable
  * Deterministic (same query → same results every time)
  * Easy to parse with stdlib only (no ANTLR/PLY needed)
  * Safe against injection (queries are parsed, never eval'd)

Syntax variants:
  - Tag-style:  `category:01_foundation quality>=7 license:mit`
  - SQL-style:  `SELECT * WHERE category = "01_foundation" AND quality_score >= 7`
  - Compact:    `cat=01_foundation q>=7 lic=mit`

Grammar (tag-style, the primary form):
    query      := condition (whitespace condition)*
    condition  := field_expr | field_expr operator value
    field_expr := field_name ":" value    (equality shorthand)
                 | field_name operator value
    operator   := "=" | ">=" | "<=" | ">" | "<" | "!=" | ":" | "in"
    value      := unquoted_string | '"' string '"'
    field_name := [a-z_]+

Grammar (SQL-style, extended):
    SELECT [fields|*]
    [WHERE condition (AND condition)*]
    [GROUP BY field]
    [ORDER BY field [ASC|DESC]]
    [LIMIT N]
    [OFFSET N]

Valid field names for filtering:
    category, subcategory, license, quality_score, verification_status,
    verified, difficulty, knowledge_type, language, source_id, type, tags

Examples:
    category:01_foundation
    category:01_foundation quality_score>=7
    category in (01_foundation, 02_software_engineering)
    license:mit quality_score>=7 verified:true
    SELECT * WHERE category = "01_foundation" AND quality_score >= 7 ORDER BY quality_score DESC LIMIT 10
"""

from __future__ import annotations

import json
import re
from typing import Any


# ---------------------------------------------------------------------------
# Tokenizer / Lexer
# ---------------------------------------------------------------------------

# Token patterns for SQL-style parsing (case-insensitive keywords)
TOKEN_PATTERNS: list[tuple[str, str]] = [
    ("SELECT", r"(?i)\bSELECT\b"),
    ("WHERE", r"(?i)\bWHERE\b"),
    ("GROUP", r"(?i)\bGROUP\b"),
    ("BY", r"(?i)\bBY\b"),
    ("ORDER", r"(?i)\bORDER\b"),
    ("LIMIT", r"(?i)\bLIMIT\b"),
    ("OFFSET", r"(?i)\bOFFSET\b"),
    ("ASC", r"(?i)\bASC\b"),
    ("DESC", r"(?i)\bDESC\b"),
    ("AND", r"(?i)\bAND\b"),
    ("OR", r"(?i)\bOR\b"),
    ("IN", r"(?i)\bIN\b"),
    ("NOT", r"(?i)\bNOT\b"),
    ("AS", r"(?i)\bAS\b"),
    ("COUNT", r"(?i)\bCOUNT\b"),
    ("MIN", r"(?i)\bMIN\b"),
    ("MAX", r"(?i)\bMAX\b"),
    ("AVG", r"(?i)\bAVG\b"),
    ("SUM", r"(?i)\bSUM\b"),
    ("STAR", r"\*"),
    ("COMMA", r","),
    ("LPAREN", r"\("),
    ("RPAREN", r"\)"),
    ("NUMBER", r"\d+(\.\d+)?"),
    ("STRING", r'"[^"]*"'),
    ("FIELD", r"[a-zA-Z_][a-zA-Z0-9_]*"),
    ("OP", r">=|<=|!=|>|<|="),
    ("WS", r"\s+"),
]


def _tokenize(sql: str) -> list[tuple[str, str]]:
    """Tokenize an AQL query string."""
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(sql):
        match = None
        for tok_type, pattern in TOKEN_PATTERNS:
            m = re.match(pattern, sql[pos:])
            if m:
                match = (tok_type, m.group(0))
                break
        if match is None:
            raise ValueError(f"AQL parse error at position {pos}: unexpected char {sql[pos:pos+10]!r}")
        tok_type, tok_val = match
        if tok_type != "WS":  # skip whitespace
            tokens.append((tok_type, tok_val))
        pos += len(tok_val)
    return tokens


# ---------------------------------------------------------------------------
# Tag-style parser (primary form)
# ---------------------------------------------------------------------------

def _parse_tag_query(query: str) -> list[dict[str, Any]]:
    """
    Parse a tag-style query into a list of conditions.

    Each condition dict has: field, operator, value

    Examples:
        "category:01_foundation" -> [{"field": "category", "op": "=", "value": "01_foundation"}]
        "quality_score>=7" -> [{"field": "quality_score", "op": ">=", "value": 7}]
        "license in (mit, apache-2.0)" -> [{"field": "license", "op": "in", "value": ["mit", "apache-2.0"]}]
    """
    conditions: list[dict[str, Any]] = []
    # Split by whitespace, respecting quoted strings
    parts = _split_respecting_quotes(query)

    i = 0
    while i < len(parts):
        part = parts[i]

        # Peek ahead: "field in (val1, val2)" pattern
        if (_is_field_name(part) and i + 2 < len(parts)
                and parts[i + 1].lower() == "in"
                and parts[i + 2].startswith("(")):
            field_name = _normalize_field(part)
            # Collect all parenthesized content (may span multiple parts)
            paren_parts = []
            j = i + 2
            while j < len(parts):
                p = parts[j].lstrip("(").rstrip(",").rstrip(")")
                paren_parts.append(p)
                if parts[j].endswith(")"):
                    j += 1
                    break
                j += 1
            list_content = ", ".join(paren_parts)
            values = [v.strip().strip('"').strip("'") for v in list_content.split(",") if v.strip()]
            conditions.append({"field": field_name, "op": "in", "value": values})
            i = j
            continue

        # Handle "field:value" shorthand
        if ":" in part and not part.startswith(":"):
            idx = part.index(":")
            field_name = part[:idx]
            raw_val = part[idx + 1:]
            if raw_val:
                conditions.append({
                    "field": _normalize_field(field_name),
                    "op": "=",
                    "value": _parse_value(raw_val),
                })
                i += 1
                continue

        # Handle "field op value" form
        for op in [">=", "<=", "!=", ">", "<", "="]:
            if op in part:
                sides = part.split(op, 1)
                if len(sides) == 2 and sides[0] and sides[1]:
                    conditions.append({
                        "field": _normalize_field(sides[0]),
                        "op": op,
                        "value": _parse_value(sides[1]),
                    })
                    break
            else:
                # Could be a bare field name for tag-style
                if _is_field_name(part):
                    conditions.append({
                        "field": _normalize_field(part),
                        "op": "exists",
                        "value": True,
                    })
        i += 1

    return conditions


def _split_respecting_quotes(text: str) -> list[str]:
    """Split text on whitespace, respecting double-quoted strings."""
    parts: list[str] = []
    current: list[str] = []
    in_quote = False
    for ch in text:
        if ch == '"':
            in_quote = not in_quote
            current.append(ch)
        elif ch.isspace() and not in_quote:
            if current:
                parts.append("".join(current))
                current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current))
    return parts


def _parse_value(raw: str) -> Any:
    """Parse a raw string value into its typed form."""
    raw = raw.strip().strip('"').strip("'")

    # Boolean
    if raw.lower() in ("true", "yes"):
        return True
    if raw.lower() in ("false", "no"):
        return False

    # Integer
    try:
        return int(raw)
    except ValueError:
        pass

    # Float
    try:
        return float(raw)
    except ValueError:
        pass

    return raw


def _normalize_field(field: str) -> str:
    """Normalize field name aliases to canonical form."""
    aliases = {
        "cat": "category",
        "subcat": "subcategory",
        "q": "quality_score",
        "quality": "quality_score",
        "lic": "license",
        "ver": "verification_status",
        "status": "verification_status",
        "type": "knowledge_type",
        "lang": "language",
        "difficulty": "difficulty",
        "diff": "difficulty",
        "source": "source_id",
    }
    f = field.strip().lower()
    return aliases.get(f, f)


def _is_field_name(s: str) -> bool:
    """Check if a string looks like a bare field name."""
    return bool(re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', s))


# ---------------------------------------------------------------------------
# SQL-style parser (extended form)
# ---------------------------------------------------------------------------

class AQLQuery:
    """
    Parsed AQL query with all components.

    Attributes:
        select_fields: List of fields to select, or ["*"] for all
        conditions: List of {"field", "op", "value"} dicts
        group_by: Field to group by, or None
        order_by: (field, "ASC"|"DESC") or None
        limit: Max results, or None
        offset: Skip N results, or None
        aggregations: List of (func, field) for aggregated selects
    """

    def __init__(self):
        self.select_fields: list[str] = ["*"]
        self.conditions: list[dict[str, Any]] = []
        self.group_by: str | None = None
        self.order_by: tuple[str, str] | None = None
        self.limit: int | None = None
        self.offset: int | None = None
        self.aggregations: list[tuple[str, str]] = []
        self.raw_query: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "select_fields": self.select_fields,
            "conditions": self.conditions,
            "group_by": self.group_by,
            "order_by": self.order_by,
            "limit": self.limit,
            "offset": self.offset,
            "aggregations": self.aggregations,
        }


def _parse_sql(tokens: list[tuple[str, str]]) -> AQLQuery:
    """Parse SQL-style tokens into an AQLQuery."""
    query = AQLQuery()
    pos = 0

    def peek() -> tuple[str, str] | None:
        return tokens[pos] if pos < len(tokens) else None

    def consume(expected_type: str | None = None) -> tuple[str, str]:
        nonlocal pos
        if pos >= len(tokens):
            raise ValueError("Unexpected end of query")
        tok = tokens[pos]
        pos += 1
        if expected_type and tok[0] != expected_type:
            raise ValueError(f"Expected {expected_type}, got {tok[0]} ({tok[1]})")
        return tok

    # SELECT clause
    if peek() and peek()[0] == "SELECT":
        consume("SELECT")
        # Parse select fields
        fields: list[str] = []
        aggs: list[tuple[str, str]] = []
        while True:
            if peek() and peek()[0] == "STAR":
                consume("STAR")
                fields.append("*")
            elif peek() and peek()[0] in ("COUNT", "MIN", "MAX", "AVG", "SUM"):
                func = consume()[1].lower()
                consume("LPAREN")
                if peek() and peek()[0] == "STAR":
                    consume("STAR")
                    field = "*"
                else:
                    field = consume("FIELD")[1]
                consume("RPAREN")
                aggs.append((func, field))
            elif peek() and peek()[0] == "FIELD":
                fields.append(consume("FIELD")[1])
            else:
                break
            if peek() and peek()[0] == "COMMA":
                consume("COMMA")
            else:
                break
        if not fields:
            fields = ["*"]
        query.select_fields = fields
        query.aggregations = aggs

    # WHERE clause
    if peek() and peek()[0] == "WHERE":
        consume("WHERE")
        query.conditions = _parse_where_clause(tokens, pos)
        # Advance pos past the WHERE clause
        # (simple approach: consume until we hit GROUP/ORDER/LIMIT/OFFSET/end)
        while pos < len(tokens) and peek()[0] not in ("GROUP", "ORDER", "LIMIT", "OFFSET"):
            pos += 1

    # GROUP BY clause
    if peek() and peek()[0] == "GROUP":
        consume("GROUP")
        consume("BY")
        query.group_by = consume("FIELD")[1]

    # ORDER BY clause
    if peek() and peek()[0] == "ORDER":
        consume("ORDER")
        consume("BY")
        field = consume("FIELD")[1]
        direction = "ASC"
        if peek() and peek()[0] in ("ASC", "DESC"):
            direction = consume()[1]
        query.order_by = (field, direction)

    # LIMIT clause
    if peek() and peek()[0] == "LIMIT":
        consume("LIMIT")
        query.limit = int(consume("NUMBER")[1])

    # OFFSET clause
    if peek() and peek()[0] == "OFFSET":
        consume("OFFSET")
        query.offset = int(consume("NUMBER")[1])

    return query


def _parse_where_clause(tokens: list[tuple[str, str]], start: int) -> list[dict[str, Any]]:
    """Parse conditions from a WHERE clause starting at position `start`."""
    conditions: list[dict[str, Any]] = []
    pos = start
    while pos < len(tokens):
        tok = tokens[pos]

        if tok[0] in ("GROUP", "ORDER", "LIMIT", "OFFSET"):
            break

        if tok[0] == "AND":
            pos += 1
            continue

        # Expect field
        if tok[0] != "FIELD":
            pos += 1
            continue
        field = _normalize_field(tok[1])
        pos += 1

        if pos >= len(tokens):
            conditions.append({"field": field, "op": "exists", "value": True})
            break

        # Check for IN operator
        if tokens[pos][0] == "IN":
            pos += 1
            consume_l = tokens[pos] if pos < len(tokens) else None
            if consume_l and consume_l[0] == "LPAREN":
                pos += 1
                values: list[Any] = []
                while pos < len(tokens) and tokens[pos][0] != "RPAREN":
                    if tokens[pos][0] == "COMMA":
                        pos += 1
                        continue
                    if tokens[pos][0] == "STRING":
                        values.append(tokens[pos][1].strip('"'))
                    elif tokens[pos][0] == "NUMBER":
                        v = tokens[pos][1]
                        values.append(int(v) if "." not in v else float(v))
                    elif tokens[pos][0] == "FIELD":
                        values.append(tokens[pos][1])
                    pos += 1
                if pos < len(tokens) and tokens[pos][0] == "RPAREN":
                    pos += 1
                conditions.append({"field": field, "op": "in", "value": values})
                continue

        # Operator
        op = "="
        if pos < len(tokens) and tokens[pos][0] == "OP":
            op = tokens[pos][1]
            pos += 1

        if pos >= len(tokens):
            conditions.append({"field": field, "op": op, "value": True})
            break

        # Value
        val_tok = tokens[pos]
        if val_tok[0] == "STRING":
            conditions.append({"field": field, "op": op, "value": val_tok[1].strip('"')})
            pos += 1
        elif val_tok[0] == "NUMBER":
            v = val_tok[1]
            conditions.append({"field": field, "op": op,
                               "value": int(v) if "." not in v else float(v)})
            pos += 1
        elif val_tok[0] == "FIELD":
            # Treat as a string literal for now (true/false handled in _parse_value)
            conditions.append({"field": field, "op": op, "value": _parse_value(val_tok[1])})
            pos += 1

    return conditions


# ---------------------------------------------------------------------------
# Query executor
# ---------------------------------------------------------------------------

def _match_condition(record: dict[str, Any], condition: dict[str, Any]) -> bool:
    """
    Check if a single record matches a condition.

    Supports operators: =, !=, >, >=, <, <=, in, exists
    """
    field = condition["field"]
    op = condition.get("op", "=")
    expected = condition.get("value")

    actual = record.get(field)

    # "exists" operator: field is present and truthy
    if op == "exists":
        return bool(actual)

    # "in" operator: actual in expected list
    if op == "in":
        if not isinstance(expected, (list, tuple)):
            return False
        actual_str = str(actual).lower() if actual is not None else ""
        return any(str(v).lower() == actual_str for v in expected)

    # Field not present
    if actual is None:
        return False

    # Type coercion for comparison
    if isinstance(expected, (int, float)) and not isinstance(actual, (int, float)):
        try:
            actual = float(actual) if "." in str(actual) else int(actual)
        except (ValueError, TypeError):
            return False

    # String comparison (case-insensitive for strings)
    if isinstance(expected, str) and isinstance(actual, str):
        actual = actual.lower()
        expected = expected.lower()

    if op == "=":
        return actual == expected
    elif op == "!=":
        return actual != expected
    elif op == ">":
        return actual is not None and actual > expected
    elif op == ">=":
        return actual is not None and actual >= expected
    elif op == "<":
        return actual is not None and actual < expected
    elif op == "<=":
        return actual is not None and actual <= expected

    return False


def execute_query(
    query_input: str | AQLQuery | dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Execute an AQL query against a list of records.

    Args:
        query_input: AQL query string (tag or SQL style), AQLQuery object, or
                     condition dict with "conditions" list
        records: List of record dicts to query

    Returns:
        Dict with "records" (matching), "count", "query" (parsed repr),
        and optionally "aggregations" and "groups"
    """
    # Parse input
    if isinstance(query_input, str):
        query_input = query_input.strip()
        if not query_input:
            return {"records": records, "count": len(records), "query": {"raw": query_input}}

        # Detect SQL-style vs tag-style
        if query_input.upper().startswith("SELECT"):
            tokens = _tokenize(query_input)
            parsed = _parse_sql(tokens)
        else:
            conditions = _parse_tag_query(query_input)
            parsed = AQLQuery()
            parsed.conditions = conditions
        parsed.raw_query = query_input
    elif isinstance(query_input, AQLQuery):
        parsed = query_input
    elif isinstance(query_input, dict):
        parsed = AQLQuery()
        parsed.conditions = query_input.get("conditions", [])
        parsed.select_fields = query_input.get("select_fields", ["*"])
        parsed.group_by = query_input.get("group_by")
        parsed.order_by = query_input.get("order_by")
        parsed.limit = query_input.get("limit")
        parsed.offset = query_input.get("offset")
    else:
        raise TypeError(f"Unsupported query input type: {type(query_input)}")

    # Filter
    matched = list(records)
    for cond in parsed.conditions:
        matched = [r for r in matched if _match_condition(r, cond)]

    # GROUP BY
    groups: dict[str, list[dict[str, Any]]] | None = None
    if parsed.group_by:
        groups = {}
        for r in matched:
            key = str(r.get(parsed.group_by, "unknown"))
            groups.setdefault(key, []).append(r)

    # ORDER BY
    if parsed.order_by:
        field, direction = parsed.order_by
        reverse = direction.upper() == "DESC"
        matched.sort(key=lambda r: (r.get(field) is not None, r.get(field, "")), reverse=reverse)

    # LIMIT / OFFSET
    if parsed.offset is not None:
        matched = matched[parsed.offset:]
    if parsed.limit is not None:
        matched = matched[:parsed.limit]

    # SELECT fields projection
    if parsed.select_fields != ["*"] or parsed.aggregations:
        projected: list[dict[str, Any]] = []
        for r in matched:
            pr: dict[str, Any] = {}
            for f in parsed.select_fields:
                if f != "*":
                    pr[f] = r.get(f)
            if not pr:
                pr = dict(r)
            projected.append(pr)
        matched = projected

    # Aggregations
    agg_results: dict[str, Any] = {}
    if parsed.aggregations:
        for func, field in parsed.aggregations:
            values: list[float] = []
            for r in (records if parsed.group_by else matched):
                v = r.get(field)
                if isinstance(v, (int, float)):
                    values.append(float(v))
            if func == "count":
                if field == "*":
                    agg_results["count(*)"] = len(records)
                else:
                    agg_results[f"count({field})"] = len(values)
            elif func == "sum":
                agg_results[f"sum({field})"] = sum(values)
            elif func == "avg":
                agg_results[f"avg({field})"] = round(sum(values) / len(values), 2) if values else 0
            elif func == "min":
                agg_results[f"min({field})"] = min(values) if values else 0
            elif func == "max":
                agg_results[f"max({field})"] = max(values) if values else 0

    # Build result
    result: dict[str, Any] = {
        "records": matched,
        "count": len(matched),
        "total_available": len(records),
        "query": parsed.to_dict(),
        "query_raw": parsed.raw_query,
    }
    if parsed.group_by and groups:
        result["groups"] = {k: len(v) for k, v in groups.items()}
    if agg_results:
        result["aggregations"] = agg_results

    return result


def preview_query(
    query_input: str,
    records: list[dict[str, Any]],
    max_preview: int = 20,
) -> dict[str, Any]:
    """
    Execute an AQL query and return a preview with summary stats.

    Useful for CLI display: shows the query summary, count, and first N records.
    """
    result = execute_query(query_input, records)
    preview_records = result["records"][:max_preview]
    return {
        "query": query_input,
        "total_matching": result["count"],
        "total_available": result["total_available"],
        "preview_count": len(preview_records),
        "preview": preview_records,
        "aggregations": result.get("aggregations"),
        "groups": result.get("groups"),
    }


def validate_query(query_input: str) -> dict[str, Any]:
    """
    Validate an AQL query string without executing it.

    Returns {"valid": True} or {"valid": False, "errors": [...]}.
    """
    query_input = query_input.strip()
    if not query_input:
        return {"valid": False, "errors": ["Empty query"]}
    try:
        if query_input.upper().startswith("SELECT"):
            tokens = _tokenize(query_input)
            _parse_sql(tokens)
        else:
            conditions = _parse_tag_query(query_input)
            if not conditions:
                return {"valid": False, "errors": ["No valid conditions parsed"]}
            # Validate field names
            valid_fields = {
                "category", "subcategory", "license", "quality_score",
                "verification_status", "verified", "difficulty", "knowledge_type",
                "language", "source_id", "type", "tags", "id",
            }
            for c in conditions:
                if c["field"] not in valid_fields:
                    return {"valid": False, "errors": [f"Unknown field: {c['field']}"]}
        return {"valid": True}
    except (ValueError, IndexError, KeyError) as e:
        return {"valid": False, "errors": [str(e)]}


def describe_query(query_input: str) -> str:
    """Return a human-readable description of what an AQL query does."""
    result = validate_query(query_input)
    if not result.get("valid"):
        return f"Invalid query: {result.get('errors', ['unknown error'])}"

    try:
        if query_input.upper().startswith("SELECT"):
            tokens = _tokenize(query_input)
            parsed = _parse_sql(tokens)
            parts: list[str] = []
            if parsed.select_fields:
                parts.append(f"Selecting {', '.join(parsed.select_fields)}")
            if parsed.conditions:
                cond_strs = [f"{c['field']} {c.get('op', '=')} {c.get('value', '?')}" for c in parsed.conditions]
                parts.append(f"where {', '.join(cond_strs)}")
            if parsed.group_by:
                parts.append(f"grouped by {parsed.group_by}")
            if parsed.order_by:
                parts.append(f"ordered by {parsed.order_by[0]} ({parsed.order_by[1]})")
            if parsed.limit:
                parts.append(f"limit {parsed.limit}")
            return "; ".join(parts) if parts else "Full dataset"
        else:
            conditions = _parse_tag_query(query_input)
            cond_strs = [f"{c['field']} {c.get('op', '=')} {c.get('value', '?')}" for c in conditions]
            return f"Filter records where {' and '.join(cond_strs)}"
    except (ValueError, IndexError, KeyError) as e:
        return f"Could not describe query: {e}"

"""normalize.py — Text and mathematical notation normalization for QEE v2.

Purpose
-------
The QEE v1 scored correctness from raw substrings and keyword hits. Strict
substring matching breaks on legitimate rewording ("4x^2 - 3x - 7" vs.
"four x squared minus three x minus seven") and is trivially fooled by
answers that echo question keywords. This module normalizes candidate text
into comparable canonical forms so that downstream evaluators compare
*meaning* rather than exact byte sequences.

Scope
-----
* Unicode math characters -> ASCII equivalents.
* LaTeX noise removal (``\\left``, ``\\right``, spacing commands, ``$``).
* ``\\frac{a}{b}`` -> ``(a)/(b)`` for safe-evaluation.
* Spoken operators -> symbolic operators ("minus" -> "-", "squared" -> "^2").
* Deterministic, stdlib-only, pure functions (no state, no network).

Invariants
----------
* Pure: same input -> same output; no mutation of inputs.
* Deterministic: no randomness, no locale dependence.
"""

from __future__ import annotations

import re

# Unicode -> ASCII math symbols (U+2212 MINUS, ×, ·, ÷, superscripts, etc.)
UNICODE_MATH_MAP = {
    "\u2212": "-",       # minus sign
    "\u2213": "-",       # minus-or-plus (treat as minus for comparison)
    "\u00d7": "*",       # multiplication sign
    "\u00b7": "*",       # middle dot
    "\u2022": "*",       # bullet
    "\u22c5": "*",       # dot operator
    "\u00f7": "/",       # division sign
    "\u2044": "/",       # fraction slash
    "\u2217": "*",       # asterisk operator
    "\u221a": "sqrt(",   # square root
    "\u222b": "integral(",  # integral (best-effort; rarely parseable)
    "\u2248": "=",       # approximately equal
    "\u2249": "=",
    "\u2260": "=",       # not equal (approx for numeric compare)
    "\u03c0": "pi",      # lower-case pi
    "\u03a0": "pi",
    "\u03b8": "theta",   # variables kept as token names
    "\u03bc": "mu",
    "\u03bb": "lambda",
    "\u03b1": "alpha",
    "\u03b2": "beta",
    "\u03b3": "gamma",
    "\u03a3": "sigma",
    "\u03c3": "sigma",
}

# Superscript digits -> caret notation (e.g. "x²" -> "x^2")
SUPERSCRIPTS = {
    "\u00b2": "^2", "\u00b3": "^3", "\u00b9": "^1",
    "\u2070": "^0", "\u2074": "^4", "\u2075": "^5",
    "\u2076": "^6", "\u2077": "^7", "\u2078": "^8", "\u2079": "^9",
}
_SUP_RE = re.compile("|".join(re.escape(k) for k in SUPERSCRIPTS))

# Spoken operators -> symbolic operators. Applied inside numeric-answer text
# before expression parsing so paraphrased math answers normalize identically.
SPOKEN_OPERATOR_PATTERNS = [
    (re.compile(r"\bdivided by\b", re.I), "/"),
    (re.compile(r"\bover\b", re.I), "/"),
    (re.compile(r"\bminus\b", re.I), "-"),
    (re.compile(r"\bplus\b", re.I), "+"),
    (re.compile(r"\btimes\b", re.I), "*"),
    (re.compile(r"\bmul(?:tiplied)? by\b", re.I), "*"),
    (re.compile(r"\bsquared\b", re.I), "^2"),
    (re.compile(r"\bcubed\b", re.I), "^3"),
    (re.compile(r"\bto the power of\b", re.I), "^"),
    (re.compile(r"\braised to\b", re.I), "^"),
    (re.compile(r"\bequals?\b", re.I), "="),
    (re.compile(r"\bis\b", re.I), "="),
    # "percent" / "per cent" -> "/100" so words and "%" compare identically.
    (re.compile(r"\bper\s?cent\b", re.I), "/100"),
]

LATEX_NOISE = re.compile(
    r"\\(?:left|right|quad|qquad|displaystyle|textstyle|operatorname"
    r"|mathrm|mathbf|mathit|text|cdotp)\b"
)
LATEX_SPACING = re.compile(r"\\[,;:! ]")
LATEX_BRACKETS = re.compile(r"\\[()\[\]]")

# Number words -> digits (used when converting spoken math to symbols).
NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30",
    "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70",
    "eighty": "80", "ninety": "90", "hundred": "100", "thousand": "1000",
}
_NUMBER_WORD_RE = re.compile(
    r"\b(" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")\b"
)

_FRAC_RE = re.compile(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
_SQRT_RE = re.compile(r"\\sqrt(?:\[[^\]]*\])?\s*(?:\{([^{}]*)\}|([A-Za-z0-9]))")

WHITESPACE_RE = re.compile(r"\s+")

# Thousands separators: "1,000" / "1,234,567" -> "1000" / "1234567".
# Only comma-then-exactly-3-digits groups are removed, so coordinate tuples
# like "(-3,0)" are preserved.
_THOUSANDS_COMMA_RE = re.compile(r"(?<=\d),(?=\d{3}\b)")

# Scientific notation: allow 1e5, 2.5e-3, 3E+7 -> lower-case e, keep as-is.
_SCI_RE = re.compile(r"(?<=\d)[eE](?=[+-]?\d)")

# Percentage token: "36%" / "49 %" / "36.5%". Normalized to /100 so that
# "36%" == "0.36" == "36/100" for numeric comparison.
_PERCENT_RE = re.compile(r"(?<=\d)\s*%")

# Unit tokens removed for dimensionless numeric comparison. Applied after
# numbers are isolated so "5 meters" == "5 m" == "5".
_UNIT_WORDS = re.compile(
    r"\b(?:seconds?|sec|meters?|metres?|m|kilometers?|kms?|centimeters?"
    r"|cms?|millimeters?|mms?|degrees?|deg|radians?|rad|hundredths?)\b",
    re.I,
)
# Degree / prime symbols -> stripped (degrees normalized to plain numbers).
_DEGREE_SYMBOLS = re.compile(r"[°˚º]")

STOPWORDS = frozenset(
    """
    a an and are as at be but by for from how in is it of on or that the
    this to was what when where which who why with do does did would will
    should can could may might its your you i we they he she them then than
    there here about into not no yes please explain describe list define
    give give? want need
    """.split()
)


def to_ascii(text: str) -> str:
    """Map common Unicode math characters to ASCII equivalents."""
    out = text
    for k, v in UNICODE_MATH_MAP.items():
        out = out.replace(k, v)
    out = _SUP_RE.sub(lambda m: SUPERSCRIPTS[m.group(0)], out)
    return out


def strip_latex_noise(text: str) -> str:
    """Remove non-semantic LaTeX scaffolding that would split comparisons.

    Inline/display math delimiters (``\\(``, ``\\)``, ``\\[``, ``\\]``) are
    removed entirely (they are not grouping). ``\\%`` becomes ``%`` so
    percentage answers parse. Remaining ``\\left``/``\\right`` are dropped by
    LATEX_NOISE, leaving real parentheses for grouping.
    """
    out = text
    out = out.replace("\\(", "").replace("\\)", "")
    out = out.replace("\\[", "").replace("\\]", "")
    out = out.replace("\\%", "%")
    out = re.sub(r"\$", "", out)
    out = LATEX_NOISE.sub("", out)
    out = LATEX_SPACING.sub("", out)
    out = LATEX_BRACKETS.sub("", out)
    return out


def expand_latex_constructs(text: str) -> str:
    """Expand \\frac{a}{b} and \\sqrt{a} into parseable expressions.

    Simple (non-nested) constructs are handled; deeply nested fractions are
    left untouched and will fall back to structural comparison downstream.
    """
    out = text
    prev = None
    while prev != out:
        prev = out
        out = _FRAC_RE.sub(lambda m: f"({m.group(1)})/({m.group(2)})", out)
        out = _SQRT_RE.sub(lambda m: f"sqrt({m.group(1) or m.group(2)})", out)
    return out


def spoken_to_symbolic(text: str) -> str:
    """Convert spoken math ("x squared minus 1") to symbolic ("x^2-1")."""
    out = text
    for pat, repl in SPOKEN_OPERATOR_PATTERNS:
        out = pat.sub(repl, out)
    out = _NUMBER_WORD_RE.sub(lambda m: NUMBER_WORDS[m.group(0).lower()], out)
    return out


def normalize_numeric(text: str) -> str:
    """Canonicalize numeric formatting for equivalence comparison.

    - removes thousands separators (``1,000`` -> ``1000``), preserving tuples,
    - normalizes scientific notation case (``2.5E-3`` -> ``2.5e-3``),
    - converts trailing percent (``36%`` -> ``36/100``) so percentages compare
      as their decimal/fraction equivalent (36% == 0.36 == 36/100),
    - strips unit words/symbols (seconds, meters, degrees, ...) so ``5 m``,
      ``5 meters`` and ``5`` compare equal,
    - strips trailing percent-prefixed unit residue.
    """
    out = _THOUSANDS_COMMA_RE.sub("", text)
    out = _SCI_RE.sub("e", out)
    # percent -> /100 (only when directly attached to a number)
    out = _PERCENT_RE.sub("/100", out)
    out = _DEGREE_SYMBOLS.sub("", out)
    out = _UNIT_WORDS.sub(" ", out)
    out = re.sub(r"\s+", "", out)
    return out


def normalize_text(text: str) -> str:
    """Collapse whitespace and lowercase, preserving internal symbols."""
    return WHITESPACE_RE.sub(" ", text).strip().lower()


def normalize_math(text: str) -> str:
    """Full math normalization pipeline for expression comparison."""
    if not text:
        return ""
    out = to_ascii(text)
    out = strip_latex_noise(out)
    out = expand_latex_constructs(out)
    out = spoken_to_symbolic(out)
    # Numeric-formatting / unit / percentage canonicalization.
    out = normalize_numeric(out)
    # Remove remaining braces used purely as grouping in TeX output.
    out = out.replace("{", "(").replace("}", ")")
    out = WHITESPACE_RE.sub("", out)
    return out


def content_tokens(text: str) -> list[str]:
    """Lower-cased, stopword-filtered word tokens for semantic comparison."""
    words = re.findall(r"[a-z0-9][a-z0-9'+-]*", text.lower())
    return [w for w in words if w not in STOPWORDS and len(w) >= 2]


def token_set_similarity(a: list[str], b: list[str]) -> float:
    """Jaccard-style overlap between two token lists (deduplicated)."""
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]

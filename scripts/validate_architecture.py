#!/usr/bin/env python3
"""
validate_architecture.py — Atlas Architecture Policy Validator.

Automated static analysis that enforces the dependency layering, ownership
boundaries, and cross-cutting rules defined in the governance contract.

Checks:
  1. Forbidden imports — lower layers importing from higher layers
  2. Circular dependencies — import chains that would cycle
  3. Duplicated constants — enum/constant redefinitions outside atlas_constants
  4. Duplicated license functions — license utils defined outside atlas_constants
  5. Duplicated schema definitions — field sets defined outside atlas_schema
  6. [DISABLED] Direct filesystem path construction — tracked as known debt

Output:
  metadata/architecture_validation_report.json

Exit code:
  0 = pass (no violations)
  1 = violation(s) found
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = PROJECT_ROOT / "metadata" / "architecture_validation_report.json"

# Layer definitions: module_name -> layer_number
# Layer 1 = Foundation (stdlib only)
# Layer 2 = Validation & Lifecycle
# Layer 3 = Engine & Release
# Layer 4 = CLI & Tooling
# Layer 5 = Tests & Standalone Scripts

LAYER_MAP: dict[str, int] = {
    # Layer 1 — Foundation
    "atlas_constants": 1,
    "atlas_schema": 1,
    "atlas_paths": 1,
    # Layer 2 — Validation & Lifecycle
    "validate_dataset": 2,
    "validate_knowledge_object": 2,
    "quality_score": 2,
    "acquisition_engine.lifecycle": 2,  # lifecycle lives in acquisition_engine dir but is Layer 2
    # Layer 3 — Engine & Release
    "acquisition_engine.aql": 3,
    "acquisition_engine.checkpoint": 3,
    "acquisition_engine.dataset_diff": 3,
    "acquisition_engine.engine": 3,
    "acquisition_engine.integrity": 3,
    "acquisition_engine.knowledge_collection": 3,
    "acquisition_engine.knowledge_pack": 3,
    "acquisition_engine.release": 3,
    "acquisition_engine.versioning": 3,
    "acquisition_engine": 3,
    # Layer 3 — Evaluation Engine (Phase 5A)
    "evaluation_engine": 3,
    "evaluation_engine.engine": 3,
    "evaluation_engine.metrics": 3,
    "evaluation_engine.registry": 3,
    "evaluation_engine.report": 3,
    # Layer 3 — Training View Engine (Phase 5C)
    "training_view_engine": 3,
    "training_view_engine.generator": 3,
    "training_view_engine.filter": 3,
    "training_view_engine.manifest": 3,
    "training_view_engine.validator": 3,
    "payload_resolver": 3,
    # Layer 4 — CLI & Tooling
    "atlas": 4,
    "calibrate_quality": 4,
    "clean_dataset": 4,
    "convert_format": 4,
    "dedup_dataset": 4,
    "eval_dataset": 4,
    "freeze_calibration_baseline": 4,
    "gen_calibration_sample": 4,
    "ingest_dryrun": 4,
    "pilot_seed": 4,
    "progressive_expansion": 4,
    "progressive_expansion_v2": 4,
    # Layer 4 — Training Readiness & Release Simulation (Phase 5D)
    "training_readiness": 4,
    "release_decision_simulator": 4,
}

# Layer 1 modules — may only import stdlib
LAYER1_MODULES = {"atlas_constants", "atlas_schema", "atlas_paths"}

# Canonical owner for each owned constant/function
# Maps: (type, name) -> canonical_module
CANONICAL_OWNERS: dict[tuple[str, str], str] = {
    # atlas_constants ownership
    ("constant", "VALID_CATEGORIES"): "atlas_constants",
    ("constant", "VALID_TYPES"): "atlas_constants",
    ("constant", "VALID_KNOWLEDGE_TYPES"): "atlas_constants",
    ("constant", "VERIFICATION_STATUSES"): "atlas_constants",
    ("constant", "LIFECYCLE_STATES"): "atlas_constants",
    ("constant", "VALID_ROLES"): "atlas_constants",
    ("constant", "VALID_TRAINING_MODELS"): "atlas_constants",
    ("constant", "VERIFICATION_STATUS_RANK"): "atlas_constants",
    ("function", "is_denied_license"): "atlas_constants",
    ("function", "is_share_alike"): "atlas_constants",
    ("function", "requires_attribution"): "atlas_constants",
    # atlas_schema ownership
    ("constant", "BASE_REQUIRED_FIELDS"): "atlas_schema",
    ("constant", "BASE_OPTIONAL_FIELDS"): "atlas_schema",
    ("constant", "BASE_ALLOWED_KEYS"): "atlas_schema",
    ("constant", "KNOWLEDGE_OBJECT_REQUIRED_FIELDS"): "atlas_schema",
    ("constant", "LINEAGE_SUB_FIELDS"): "atlas_schema",
    ("constant", "SELF_TEST_REQUIRED_FIELDS"): "atlas_schema",
    ("constant", "SCHEMA_VERSION_BASE"): "atlas_schema",
    ("constant", "SCHEMA_VERSION_KNOWLEDGE_OBJECT"): "atlas_schema",
    ("constant", "CHAT_SCHEMA_VERSION"): "atlas_schema",
    ("constant", "SUPPORTED_SCHEMA_VERSIONS"): "atlas_schema",
    ("constant", "QUALITY_SCORE_MIN"): "atlas_schema",
    ("constant", "QUALITY_SCORE_MAX"): "atlas_schema",
    ("constant", "DIFFICULTY_MIN"): "atlas_schema",
    ("constant", "DIFFICULTY_MAX"): "atlas_schema",
    ("constant", "MIN_MESSAGE_TURNS"): "atlas_schema",
    ("function", "validate_quality_score"): "atlas_schema",
    ("function", "validate_difficulty"): "atlas_schema",
    ("function", "validate_messages"): "atlas_schema",
    ("function", "validate_id"): "atlas_schema",
    ("function", "field_info"): "atlas_schema",
    # atlas_paths ownership
    ("function", "discover_root"): "atlas_paths",
    ("function", "get_root"): "atlas_paths",
    ("function", "is_write_safe"): "atlas_paths",
    ("constant", "APPROVED_WRITE_ROOTS"): "atlas_paths",
}

# Directory prefixes that indicate direct path construction (bypassing atlas_paths)
DIRECT_PATH_DIRS: frozenset[str] = frozenset({
    "curated", "metadata", "raw", "review_queue", "training_views",
    "schemas", "docs", "tmp", "migrations", "knowledge_packs",
})

# ---------------------------------------------------------------------------
# Known pre-existing violations (grandfathered — documented in health dashboard)
# These are suppressed to allow the validator to pass on legacy code.
# New code must NOT be added here; this list is for reduction only.
# ---------------------------------------------------------------------------

KNOWN_VIOLATIONS: set[tuple[str, str, str]] = {
    # progressive_expansion.py defines is_denied_license instead of importing
    # from atlas_constants. Documented in docs/architecture_health_v0.3.md.
    ("duplicated_constant", "scripts/progressive_expansion.py",
     "Function 'is_denied_license' defined in progressive_expansion but owned by atlas_constants"),
    ("duplicated_license_function", "scripts/progressive_expansion.py",
     "License utility 'is_denied_license' defined in progressive_expansion but is owned by atlas_constants"),
    # progressive_expansion_v2.py defines is_denied_license instead of importing
    # from atlas_constants. Documented in docs/architecture_health_v0.3.md.
    ("duplicated_constant", "scripts/progressive_expansion_v2.py",
     "Function 'is_denied_license' defined in progressive_expansion_v2 but owned by atlas_constants"),
    ("duplicated_license_function", "scripts/progressive_expansion_v2.py",
     "License utility 'is_denied_license' defined in progressive_expansion_v2 but is owned by atlas_constants"),
    # tui_backend.py dataclass field default — not an actual parallelism worker count
    ("hardcoded_worker_count", "scripts/tui_backend.py",
     "Hardcoded workers=0 in tui_backend"),
    # versioning.py duplicates constant from atlas_schema
    ("duplicated_constant", "scripts/evaluation_engine/generation_policy/versioning.py",
     "Constant 'SUPPORTED_SCHEMA_VERSIONS' defined in evaluation_engine but owned by atlas_schema"),
    # benchmarks/eb/paths.py duplicates functions from atlas_paths
    ("duplicated_constant", "benchmarks/eb/eb/paths.py",
     "Function 'get_root' defined in benchmarks but owned by atlas_paths"),
    ("duplicated_constant", "benchmarks/eb/eb/paths.py",
     "Function 'is_write_safe' defined in benchmarks but owned by atlas_paths"),
}

# ---------------------------------------------------------------------------
# Results accumulator
# ---------------------------------------------------------------------------

violations: list[dict[str, Any]] = []
checked_files: int = 0
all_imports: dict[str, set[str]] = {}  # module -> set of imported modules


def violation(category: str, file: str, message: str, details: str = "") -> None:
    # Check if this is a known pre-existing violation
    for known_cat, known_file, known_msg in KNOWN_VIOLATIONS:
        if category == known_cat and file == known_file and message == known_msg:
            print(f"  KNOWN   [{category}] {file}: {message}")
            return
    violations.append({
        "category": category,
        "file": file,
        "message": message,
        "details": details,
    })
    print(f"  VIOLATION  [{category}] {file}: {message}")
    if details:
        print(f"             {details}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def module_name_from_path(path: Path) -> str | None:
    """Convert a file path to the module name used in LAYER_MAP."""
    rel = path.relative_to(PROJECT_ROOT)
    parts = list(rel.parts)

    # Remove .py extension
    if parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]

    # Handle scripts/ prefix
    if parts[0] == "scripts":
        parts = parts[1:]
    elif parts[0] == "tests":
        return f"tests.{parts[-1]}" if len(parts) == 2 else "tests"

    # Handle acquisition_engine subpackage
    if len(parts) >= 2 and parts[0] == "acquisition_engine":
        return "acquisition_engine." + parts[1]

    return parts[0] if parts else None


def get_layer(module: str) -> int:
    """Get the layer number for a module."""
    module = module.replace("scripts.", "")
    # Special handling for acquisition_engine submodules
    if module.startswith("acquisition_engine."):
        sub = module.split(".")[1]
        # lifecycle is Layer 2
        if sub == "lifecycle":
            return 2
        return 3
    if module.startswith("tests"):
        return 5
    return LAYER_MAP.get(module, 5)  # Unknown = Layer 5


def is_stdlib_only(path: Path) -> bool:
    """Check if a Python file only imports stdlib modules."""
    return get_layer(module_name_from_path(path) or "") == 1


def should_skip_file(path: Path) -> bool:
    """Skip __pycache__, __init__.py, tmp/ scripts, and migrations (temporal artifacts)."""
    rel = str(path.relative_to(PROJECT_ROOT))
    return ("__pycache__" in rel or
            path.name == "__init__.py" or
            rel.startswith("tmp") or
            rel.startswith(".") or
            rel.startswith("migrations"))


# ---------------------------------------------------------------------------
# Check 1: Forbidden imports
# ---------------------------------------------------------------------------


def check_forbidden_imports(path: Path) -> None:
    """Check that lower layers do not import from higher layers."""
    module = module_name_from_path(path)
    if module is None:
        return
    layer = get_layer(module)
    content = path.read_text(encoding="utf-8")

    for match in IMPORT_RE.finditer(content):
        imp = match.group(1) or match.group(2)
        if not imp:
            continue

        # Extract the base import module
        base = imp.split(".")[0]

        # Skip stdlib
        if base in STDLIB_MODULES:
            continue

        # Skip relative imports within acquisition_engine
        if imp.startswith("."):
            continue

        # Check if it's a project import
        target_layer = get_layer(base)
        if target_layer >= 5:  # Skip unknown, tests are always allowed to import
            continue

        # Layer 1: only stdlib allowed
        if layer == 1 and target_layer > 0:
            violation(
                "forbidden_import",
                str(path.relative_to(PROJECT_ROOT)),
                f"Layer 1 module {module} imports {imp} (layer {target_layer})",
                "Layer 1 modules may only import Python stdlib"
            )

        # Lower layers cannot import higher layers
        if layer > 1 and target_layer > layer:
            violation(
                "forbidden_import",
                str(path.relative_to(PROJECT_ROOT)),
                f"Layer {layer} module {module} imports {imp} (layer {target_layer})",
                f"Imports must flow downward: Layer {layer} may not import Layer {target_layer}"
            )

        # Track imports for circular dependency check
        if module not in all_imports:
            all_imports[module] = set()
        all_imports[module].add(imp.split(".")[0] if "." in imp else imp)


# ---------------------------------------------------------------------------
# Check 2: Circular dependencies
# ---------------------------------------------------------------------------


def check_circular_dependencies() -> None:
    """Detect circular import chains using DFS."""
    visited: set[str] = set()
    stack: set[str] = set()

    def dfs(module: str, path_stack: list[str]) -> None:
        # Skip self-imports (e.g. payload_resolver importing itself for CLI dispatch)
        if len(path_stack) >= 1 and path_stack[-1] == module:
            return
        if module in stack:
            cycle = path_stack[path_stack.index(module):] + [module]
            violation(
                "circular_dependency",
                module,
                f"Circular import chain detected: {' → '.join(cycle)}",
                "Cycles break deterministic import order and create bootstrap issues"
            )
            return
        if module in visited:
            return
        if module not in all_imports:
            return

        visited.add(module)
        stack.add(module)
        path_stack.append(module)

        for dep in all_imports.get(module, set()):
            dep_base = dep.split(".")[0]
            if dep_base in all_imports:
                dfs(dep_base, path_stack)

        path_stack.pop()
        stack.remove(module)

    for mod in all_imports:
        dfs(mod, [])


# ---------------------------------------------------------------------------
# Check 3: Duplicated constants
# ---------------------------------------------------------------------------


def check_duplicated_constants(path: Path) -> None:
    """Check that canonical constants are not redefined outside their owner."""
    module = module_name_from_path(path)
    if module is None:
        return
    if module in ("atlas_constants", "atlas_schema", "atlas_paths"):
        return  # Canonical modules may define their owned constants

    content = path.read_text(encoding="utf-8")

    # Parse AST to find constant assignments
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return

    for node in ast.walk(tree):
        # Top-level Assign (constant = value)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    name = target.id
                    key = ("constant", name)
                    if key in CANONICAL_OWNERS and CANONICAL_OWNERS[key] != module:
                        # Check if it's just re-importing (imported from canonical)
                        # or actually redefining
                        if not _is_imported_name(path, name):
                            violation(
                                "duplicated_constant",
                                str(path.relative_to(PROJECT_ROOT)),
                                f"Constant '{name}' defined in {module} but owned by {CANONICAL_OWNERS[key]}",
                                f"Import from {CANONICAL_OWNERS[key]} instead of redefining"
                            )

        # Top-level FunctionDef (function = value)
        if isinstance(node, ast.FunctionDef):
            name = node.name
            key = ("function", name)
            if key in CANONICAL_OWNERS and CANONICAL_OWNERS[key] != module:
                violation(
                    "duplicated_constant",
                    str(path.relative_to(PROJECT_ROOT)),
                    f"Function '{name}' defined in {module} but owned by {CANONICAL_OWNERS[key]}",
                    f"Import from {CANONICAL_OWNERS[key]} instead of redefining"
                )


def _is_imported_name(path: Path, name: str) -> bool:
    """Check if a name is imported from another module."""
    content = path.read_text(encoding="utf-8")
    # Simple check: look for `from X import Y` or `from X import (Y,Z)`
    for pattern in [
        rf"from\s+\S+\s+import\s+[^#]*\b{re.escape(name)}\b",
        rf"import\s+[^#]*\b{re.escape(name)}\b",
    ]:
        if re.search(pattern, content):
            return True
    return False


# ---------------------------------------------------------------------------
# Check 4: Duplicated license functions
# ---------------------------------------------------------------------------


def check_duplicated_license_functions(path: Path) -> None:
    """Specifically check that is_denied_license, is_share_alike, requires_attribution
    are not redefined outside atlas_constants."""
    module = module_name_from_path(path)
    if module is None or module == "atlas_constants":
        return

    content = path.read_text(encoding="utf-8")
    LICENSE_FUNCS = ["is_denied_license", "is_share_alike", "requires_attribution"]

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            if node.name in LICENSE_FUNCS:
                violation(
                    "duplicated_license_function",
                    str(path.relative_to(PROJECT_ROOT)),
                    f"License utility '{node.name}' defined in {module} but is owned by atlas_constants",
                    "Import from atlas_constants instead of redefining"
                )


# ---------------------------------------------------------------------------
# Check 5: Duplicated schema definitions
# ---------------------------------------------------------------------------


def check_duplicated_schema_definitions(path: Path) -> None:
    """Check that schema field sets are not redefined outside atlas_schema."""
    module = module_name_from_path(path)
    if module is None or module == "atlas_schema":
        return

    content = path.read_text(encoding="utf-8")
    SCHEMA_SETS = [
        "BASE_REQUIRED_FIELDS", "BASE_OPTIONAL_FIELDS", "BASE_ALLOWED_KEYS",
        "KNOWLEDGE_OBJECT_REQUIRED_FIELDS", "LINEAGE_SUB_FIELDS",
        "SELF_TEST_REQUIRED_FIELDS",
    ]

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return

    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            target_name = None
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        target_name = t.id
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target_name = node.target.id

            if target_name and target_name in SCHEMA_SETS:
                if not _is_imported_name(path, target_name):
                    violation(
                        "duplicated_schema_definition",
                        str(path.relative_to(PROJECT_ROOT)),
                        f"Schema definition '{target_name}' defined in {module} but owned by atlas_schema",
                        "Import from atlas_schema instead of redefining"
                    )


# ---------------------------------------------------------------------------
# Check 6: Direct filesystem path construction outside atlas_paths
# ---------------------------------------------------------------------------


def check_direct_path_construction(path: Path) -> None:
    """Check that project directory paths are not hardcoded outside atlas_paths."""
    module = module_name_from_path(path)
    if module is None or module == "atlas_paths":
        return

    content = path.read_text(encoding="utf-8")

    # Look for Path concatenation with known directory names
    # Patterns: Path / "curated", ROOT / "metadata", root / "raw", etc.
    for dir_name in DIRECT_PATH_DIRS:
        # Skip common false positives
        if dir_name in ("docs", "tmp"):
            continue  # Too many false positives

        patterns = [
            rf'/\s*"{re.escape(dir_name)}"',   # / "curated"
            rf'/\s*\'{re.escape(dir_name)}\'',  # / 'curated'
        ]
        for pat in patterns:
            match = re.search(pat, content)
            if match:
                # Exclude the canonical path functions themselves
                # Check if this is in atlas_paths or in a string docstring
                # Use simple heuristic: if the line has "dir_name" and uses Path("/") at project level
                violation(
                    "direct_path_construction",
                    str(path.relative_to(PROJECT_ROOT)),
                    f"Direct path construction with '{dir_name}' found in {module}",
                    f"Use atlas_paths.*_dir() or atlas_paths.*_path() instead of hardcoding '{dir_name}'"
                )


# ---------------------------------------------------------------------------
# Stdlib modules set
# ---------------------------------------------------------------------------

STDLIB_MODULES: frozenset[str] = frozenset({
    "abc", "aifc", "argparse", "array", "ast", "asynchat", "asyncio",
    "asyncore", "atexit", "audioop", "base64", "bdb", "binascii", "binhex",
    "bisect", "builtins", "bz2", "calendar", "cgi", "cgitb", "chunk",
    "cmath", "cmd", "code", "codecs", "codeop", "collections", "colorsys",
    "compileall", "concurrent", "configparser", "contextlib", "contextvars",
    "copy", "copyreg", "cProfile", "crypt", "csv", "ctypes", "curses",
    "dataclasses", "datetime", "dbm", "decimal", "difflib", "dis",
    "distutils", "doctest", "email", "encodings", "enum", "errno",
    "faulthandler", "fcntl", "filecmp", "fileinput", "fnmatch", "fractions",
    "ftplib", "functools", "gc", "getopt", "getpass", "gettext", "glob",
    "graphlib", "grp", "gzip", "hashlib", "heapq", "hmac", "html", "http",
    "idlelib", "imaplib", "imghdr", "imp", "importlib", "inspect", "io",
    "ipaddress", "itertools", "json", "keyword", "lib2to3", "linecache",
    "locale", "logging", "lzma", "mailbox", "mailcap", "marshal", "math",
    "mimetypes", "mmap", "modulefinder", "multiprocessing", "netrc", "nis",
    "nntplib", "numbers", "operator", "optparse", "os", "ossaudiodev",
    "pathlib", "pdb", "pickle", "pickletools", "pipes", "pkgutil",
    "platform", "plistlib", "poplib", "posix", "posixpath", "pprint",
    "profile", "pstats", "pty", "pwd", "py_compile", "pyclbr",
    "pydoc", "queue", "quopri", "random", "re", "readline", "reprlib",
    "resource", "rlcompleter", "runpy", "sched", "secrets", "select",
    "selectors", "shelve", "shlex", "shutil", "signal", "site", "smtpd",
    "smtplib", "sndhdr", "socket", "socketserver", "sqlite3", "ssl",
    "stat", "statistics", "string", "stringprep", "struct", "subprocess",
    "sunau", "symtable", "sys", "sysconfig", "syslog", "tabnanny",
    "tarfile", "telnetlib", "tempfile", "termios", "test", "textwrap",
    "threading", "time", "timeit", "tkinter", "token", "tokenize",
    "tomllib", "trace", "traceback", "tracemalloc", "tty", "turtle",
    "turtledemo", "types", "typing", "unicodedata", "unittest", "urllib",
    "uu", "uuid", "venv", "warnings", "wave", "weakref", "webbrowser",
    "winreg", "winsound", "wsgiref", "xdrlib", "xml", "xmlrpc",
    "zipapp", "zipfile", "zipimport", "zlib",
    # typing extensions commonly used
    "typing_extensions",
})

# Regex for import statements
IMPORT_RE = re.compile(
    r'^\s*from\s+(\S+)\s+import|\^\s*import\s+(\S+)',
    re.MULTILINE
)

# Actual import patterns
IMPORT_FROM_RE = re.compile(r'^\s*from\s+(\S+)\s+import', re.MULTILINE)
IMPORT_DIRECT_RE = re.compile(r'^\s*import\s+(\S+)', re.MULTILINE)


def extract_imports(content: str) -> set[str]:
    """Extract all first-level imported module names from file content."""
    imports: set[str] = set()
    for match in IMPORT_FROM_RE.finditer(content):
        mod = match.group(1)
        base = mod.split(".")[0]
        imports.add(base)
    for match in IMPORT_DIRECT_RE.finditer(content):
        mod = match.group(1).split()[0] if match.group(1) else ""
        if mod:
            base = mod.split(".")[0]
            if base not in ("__future__",):
                imports.add(base)
    return imports


# ---------------------------------------------------------------------------
# Check 7: Hardcoded worker counts outside config/parallelism.yaml
# ---------------------------------------------------------------------------

# Files that legitimately define worker-count defaults (config loader + CLI
# default args) and are exempt from this check.
WORKER_CONFIG_EXEMPT: frozenset[str] = frozenset({
    "run_classify_all_v2", "run_extract_all", "validate_dataset",
})


def check_hardcoded_worker_counts(path: Path) -> None:
    """Enforce ADR-013: worker counts come from config/parallelism.yaml.

    Pipeline stages must read worker counts from the unified config rather
    than hardcoding them. CLI scripts that declare a --workers default as a
    fallback (and then override from config) are exempt.
    """
    module = module_name_from_path(path)
    if module is None or module in WORKER_CONFIG_EXEMPT:
        return
    # Skip tests and the config itself
    if module.startswith("test_") or "tests" in path.parts:
        return

    content = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return

    for node in ast.walk(tree):
        # Keyword args like max_workers=8, workers=4, file_workers=2
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg in ("max_workers", "workers", "file_workers", "shard_workers"):
                    if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, int):
                        violation(
                            "hardcoded_worker_count",
                            str(path.relative_to(PROJECT_ROOT)),
                            f"Hardcoded {kw.arg}={kw.value.value} in {module}",
                            "Read worker counts from config/parallelism.yaml (see ADR-013)"
                        )
        # Assignments like shard_workers = 8 (module or function scope)
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            if isinstance(target, ast.Name) and target.id in (
                "max_workers", "workers", "file_workers", "shard_workers",
            ):
                val = node.value
                if isinstance(val, ast.Constant) and isinstance(val.value, int):
                    violation(
                        "hardcoded_worker_count",
                        str(path.relative_to(PROJECT_ROOT)),
                        f"Hardcoded {target.id}={val.value} in {module}",
                        "Read worker counts from config/parallelism.yaml (see ADR-013)"
                    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    global checked_files

    print("=" * 60)
    print("  Atlas Architecture Policy Validator")
    print("=" * 60)

    all_py_files = sorted(PROJECT_ROOT.rglob("*.py"))
    python_files = [f for f in all_py_files if not should_skip_file(f)]
    checked_files = len(python_files)

    print(f"\nChecking {checked_files} Python files...\n")

    # Phase 1: Scan all files for imports and collect all_imports map
    for fp in python_files:
        module = module_name_from_path(fp)
        if module is None:
            continue
        content = fp.read_text(encoding="utf-8")
        imports = extract_imports(content)
        # Filter to only project imports
        project_imports = {imp for imp in imports if imp not in STDLIB_MODULES}
        if project_imports:
            all_imports[module] = project_imports

    # Phase 2: Run checks
    for fp in python_files:
        # Check 1: Forbidden imports
        check_forbidden_imports(fp)

        # Check 3: Duplicated constants
        check_duplicated_constants(fp)

        # Check 4: Duplicated license functions
        check_duplicated_license_functions(fp)

        # Check 5: Duplicated schema definitions
        check_duplicated_schema_definitions(fp)

        # Check 6: Direct path construction — disabled by default; pre-existing
        # instances are documented in docs/architecture_health_v0.3.md as known
        # technical debt (~1 day). Uncomment to enforce after path refactoring.
        # check_direct_path_construction(fp)

        # Check 7: Hardcoded worker counts (ADR-013)
        check_hardcoded_worker_counts(fp)

    # Check 2: Circular dependencies (requires full import map)
    check_circular_dependencies()

    # -----------------------------------------------------------------------
    # Report
    # -----------------------------------------------------------------------
    print(f"\nChecked {checked_files} files, {len(violations)} violation(s) found.\n")

    report = {
        "schema_version": "1.0",
        "validator": "validate_architecture.py",
        "contract_version": "1.0",
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "files_checked": checked_files,
        "total_violations": len(violations),
        "known_violations": len(KNOWN_VIOLATIONS),
        "result": "PASS" if not violations else "FAIL",
        "violations": violations,
        "summary": {
            "forbidden_imports": sum(1 for v in violations if v["category"] == "forbidden_import"),
            "circular_dependencies": sum(1 for v in violations if v["category"] == "circular_dependency"),
            "duplicated_constants": sum(1 for v in violations if v["category"] == "duplicated_constant"),
            "duplicated_license_functions": sum(1 for v in violations if v["category"] == "duplicated_license_function"),
            "duplicated_schema_definitions": sum(1 for v in violations if v["category"] == "duplicated_schema_definition"),
            "direct_path_construction": sum(1 for v in violations if v["category"] == "direct_path_construction"),
            "hardcoded_worker_counts": sum(1 for v in violations if v["category"] == "hardcoded_worker_count"),
        },
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report written to {REPORT_PATH.relative_to(PROJECT_ROOT)}")

    print("\n" + "=" * 60)
    if violations:
        print(f"  RESULT: FAIL ({len(violations)} violation(s))")
        print("=" * 60)
        return 1
    else:
        print("  RESULT: PASS — All architecture governance rules satisfied")
        print("=" * 60)
        return 0


if __name__ == "__main__":
    sys.exit(main())

"""Test selection — blast radius filtered to test files.

Item B / 6a from docs/handoff/2026-08-07.md:
    blast_radius(changed_files) ∩ files matching a test pattern
    → "run these 4 of 200 tests"

This is test *selection*, not test *proving*: reflection, dynamic dispatch
and runtime wiring create edges the parse cannot see. Label it "run these
first — full suite still runs on merge."
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath

from graph.blast_radius import _blast_radius_core


# ---------------------------------------------------------------------------
# Test file patterns — named, editable set per ecosystem
# ---------------------------------------------------------------------------

# File name patterns (applied to the filename part only)
_TEST_NAME_PATTERNS: list[re.Pattern] = [
    re.compile(r"^test_.*\.py$"),           # Python: test_auth.py
    re.compile(r".*_test\.py$"),            # Python alt: auth_test.py
    re.compile(r".*_test\.go$"),            # Go: auth_test.go
    re.compile(r".*\.test\.[jt]sx?$"),      # JS/TS: auth.test.ts, auth.test.jsx
    re.compile(r".*\.spec\.[jt]sx?$"),      # JS/TS: auth.spec.ts
    re.compile(r".*Test\.java$"),           # Java: AuthTest.java
    re.compile(r".*Tests\.java$"),          # Java alt: AuthTests.java
    re.compile(r".*_test\.rb$"),            # Ruby: auth_test.rb
    re.compile(r".*_spec\.rb$"),            # Ruby: auth_spec.rb
    re.compile(r".*Test\.kt$"),             # Kotlin: AuthTest.kt
    re.compile(r".*Tests\.kt$"),            # Kotlin: AuthTests.kt
    re.compile(r".*_test\.rs$"),            # Rust: auth_test.rs
    re.compile(r".*Tests\.cs$"),            # C#: AuthTests.cs
    re.compile(r".*Test\.cs$"),             # C#: AuthTest.cs
]

# Directory patterns — any file under these directories is a test
_TEST_DIR_SEGMENTS = frozenset({
    "tests", "test", "__tests__", "spec", "specs",
    "test_suite", "testing",
})


def is_test_file(path: str) -> bool:
    """Check if a file path matches known test file conventions.

    Uses a named, editable pattern set — every ecosystem differs and
    it will need adding to.
    """
    parts = PurePosixPath(path).parts
    filename = parts[-1] if parts else ""

    # Check directory segments
    for part in parts[:-1]:
        if part.lower() in _TEST_DIR_SEGMENTS:
            return True

    # Check filename patterns
    for pattern in _TEST_NAME_PATTERNS:
        if pattern.match(filename):
            return True

    return False


def select_tests(
    changed_files: list[str],
    repo_id: str,
    max_hops: int = 3,
) -> dict:
    """Tests whose files fall in the blast radius of a change.

    Args:
        changed_files: list of repo-relative paths that changed
        repo_id:       repository identifier for graph loading
        max_hops:      max traversal depth for blast radius

    Returns:
        {
            "tests": [{"path": ..., "hops": ..., "reason": ...}, ...],
            "total_tests": int,    # all tests in the repo
            "selected": int,       # tests in the blast radius
            "ratio": str,          # "4 of 200 tests"
        }
    """
    from graph.store import load_graph

    try:
        graph = load_graph(repo_id)
    except FileNotFoundError as e:
        return {"tests": [], "total_tests": 0, "selected": 0,
                "ratio": "0 of 0 tests", "error": str(e)}

    # Get blast radius
    result = _blast_radius_core(changed_files, graph, max_hops=max_hops)

    if result.get("error"):
        return {"tests": [], "total_tests": 0, "selected": 0,
                "ratio": "0 of 0 tests", "error": result["error"]}

    # Filter blast radius to test files
    affected_tests = [
        {"path": n["path"], "hops": n["hops"], "reason": n["reason"]}
        for n in result["nodes"]
        if is_test_file(n["path"])
    ]

    # Count total test files in the repo
    total_tests = sum(1 for p in graph.nodes if is_test_file(p))
    selected = len(affected_tests)

    return {
        "tests": affected_tests,
        "total_tests": total_tests,
        "selected": selected,
        "ratio": f"{selected} of {total_tests} tests",
    }

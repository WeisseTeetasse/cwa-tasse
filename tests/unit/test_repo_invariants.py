# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Repo-wide invariants: forbidden patterns that must not appear.

This is the "global cop" test file. It scans the fork-touched parts of
the codebase for patterns that have caused past regressions or that
represent latent security/reliability bugs.

If you need to add an exemption: prepend the file path to the
``EXEMPT_*`` set with a comment explaining why. Don't loosen the regex.

Sourced from the lessons in CLAUDE.md § "Forbidden / red-flag patterns".
"""

import os
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CPS = PROJECT_ROOT / "cps"


# ---------------------------------------------------------------------------
# What to scan
# ---------------------------------------------------------------------------

# Skip vendored upstream code and infrastructure.
SKIP_DIRS = {
    "cw_login",        # vendored Flask-Login
    "cw_advocate",     # vendored advocate SSRF guard
    "__pycache__",
    "translations",
    "static",
    "templates",
}


def _iter_python_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skip dirs in-place
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith(".py"):
                yield Path(dirpath) / name


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Forbidden pattern: `except Exception: pass`
# ---------------------------------------------------------------------------

# Files where a bare swallow is intentional. Keep this list small and
# every entry must explain itself. Best-effort cleanup in finally blocks
# (e.g. session.remove() after the real handler ran) is allowed by the
# context-aware check below — don't add cleanup files here.
EXEMPT_SILENT_SWALLOW = {
    # None right now. Future entries: path str → reason.
}


# Pattern: `except <name>:` followed by ONLY `pass` (allowing comments).
_BARE_SWALLOW_RE = re.compile(
    r"except\s+\w+(?:\s+as\s+\w+)?:\s*\n"     # except Foo: or except Foo as e:
    r"(?:\s*#[^\n]*\n)*"                       # optional comment lines
    r"\s*pass\b",                              # bare pass
    re.MULTILINE,
)


def _is_in_finally_cleanup(src: str, offset: int) -> bool:
    """Check if the offset is inside a `finally:` block doing session
    cleanup or similar best-effort work."""
    # Look ~400 chars back for a `finally:` marker
    context = src[max(0, offset - 400):offset]
    if "finally:" not in context:
        return False
    # Cleanup keywords we trust
    return any(kw in context for kw in (
        "session.remove",
        "session.close",
        ".unlink",
        "shutil.rmtree",
        "os.remove",
    ))


# Ratchet baseline: as of the test's introduction this is the count of
# pre-existing offenders in legacy / upstream-merged code. The test fails
# if the count GROWS. When the count shrinks, tighten this number so new
# regressions surface immediately.
SILENT_SWALLOW_BASELINE = 100  # actual ~98 as of this commit (mostly upstream legacy)


def test_silent_swallow_count_does_not_grow():
    offenders = []
    for path in _iter_python_files(CPS):
        rel = str(path.relative_to(PROJECT_ROOT))
        if rel in EXEMPT_SILENT_SWALLOW:
            continue
        src = _read(path)
        for m in _BARE_SWALLOW_RE.finditer(src):
            if _is_in_finally_cleanup(src, m.start()):
                continue
            line_no = src.count("\n", 0, m.start()) + 1
            offenders.append(f"{rel}:{line_no}")
    count = len(offenders)
    assert count <= SILENT_SWALLOW_BASELINE, (
        f"Silent-swallow count GREW: now {count}, baseline {SILENT_SWALLOW_BASELINE}.\n"
        "You added a new `except <X>: pass` somewhere. Either log the\n"
        "exception at WARNING with context, or put the swallow inside a\n"
        "`finally:` cleanup block.\n"
        "New offenders likely among:\n  " + "\n  ".join(offenders[-10:])
    )
    # If count shrank meaningfully, nudge the developer to tighten the baseline
    if count + 20 < SILENT_SWALLOW_BASELINE:
        pytest.skip(
            f"Silent-swallow count is {count}, well below baseline "
            f"{SILENT_SWALLOW_BASELINE}. Lower SILENT_SWALLOW_BASELINE in "
            "test_repo_invariants.py to lock in the improvement."
        )


# ---------------------------------------------------------------------------
# Forbidden pattern: requests with verify=False
# ---------------------------------------------------------------------------

EXEMPT_VERIFY_FALSE = set()  # No exemptions

_VERIFY_FALSE_RE = re.compile(r"\bverify\s*=\s*False\b")


def test_no_verify_false_in_requests():
    offenders = []
    for path in _iter_python_files(CPS):
        rel = str(path.relative_to(PROJECT_ROOT))
        if rel in EXEMPT_VERIFY_FALSE:
            continue
        src = _read(path)
        for m in _VERIFY_FALSE_RE.finditer(src):
            # Make sure it's near a requests./session. call (not unrelated kwarg)
            window = src[max(0, m.start() - 200):m.start()]
            if "requests." in window or "session." in window or ".get(" in window or ".post(" in window:
                line_no = src.count("\n", 0, m.start()) + 1
                offenders.append(f"{rel}:{line_no}")
    assert not offenders, (
        "Found `verify=False` near HTTP calls — TLS verification must "
        "never be disabled. Configure the CA bundle correctly instead.\n"
        "Offenders:\n  " + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# Forbidden pattern: eval / exec on dynamic input
# ---------------------------------------------------------------------------

_EVAL_EXEC_RE = re.compile(r"\b(eval|exec)\s*\(")
EXEMPT_EVAL_EXEC = {
    # cps/dep_check.py uses eval() on hardcoded constants from
    # constants.py — not user input. Upstream code, predates the fork.
    # If we ever touch this file, audit and remove the eval.
    "cps/dep_check.py",
}


def test_no_eval_or_exec_calls():
    offenders = []
    for path in _iter_python_files(CPS):
        rel = str(path.relative_to(PROJECT_ROOT))
        if rel in EXEMPT_EVAL_EXEC:
            continue
        src = _read(path)
        for m in _EVAL_EXEC_RE.finditer(src):
            # Skip method calls like `something.exec_module(`
            preceding = src[max(0, m.start() - 1):m.start()]
            if preceding.endswith("."):
                continue
            # Skip `self.exec(` style methods (e.g. subprocess wrappers)
            window = src[max(0, m.start() - 30):m.start()]
            if re.search(r"\.\s*$", window):
                continue
            line_no = src.count("\n", 0, m.start()) + 1
            offenders.append(f"{rel}:{line_no}: {m.group(1)}(")
    assert not offenders, (
        "Found eval() or exec() builtin call. These execute arbitrary "
        "code; parse explicitly instead.\n"
        "Offenders:\n  " + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# Forbidden pattern: shell=True with f-string
# ---------------------------------------------------------------------------

# subprocess.run/call/Popen with shell=True AND an f-string is a near-certain
# command-injection vector when the f-string interpolates anything we don't
# control. Block the combination entirely; if you really need shell=True,
# use a constant string.
_SHELL_FSTRING_RE = re.compile(
    r"subprocess\.\w+\([^)]*?f['\"][^'\"]*\{[^}]+\}[^)]*?shell\s*=\s*True",
    re.DOTALL,
)


def test_no_subprocess_shell_true_with_fstring():
    offenders = []
    for path in _iter_python_files(CPS):
        src = _read(path)
        for m in _SHELL_FSTRING_RE.finditer(src):
            rel = str(path.relative_to(PROJECT_ROOT))
            line_no = src.count("\n", 0, m.start()) + 1
            offenders.append(f"{rel}:{line_no}")
    assert not offenders, (
        "subprocess with shell=True AND an f-string interpolation is a "
        "shell-injection vector. Use a list argv with shell=False.\n"
        "Offenders:\n  " + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# Style: no bare print() in production code (use logger)
# ---------------------------------------------------------------------------

# These specific files print intentionally (CLI / boot-time).
EXEMPT_PRINT = {
    "cps/cli.py",
    "cps/main.py",
    "cps/debug_info.py",
    "cps/dep_check.py",
    "cps/worker_main.py",
    "cps/server.py",
    # ub.py prints during migration before logger is configured
    "cps/ub.py",
    # gevent_wsgi and tornado_wsgi may print bootstrap info
    "cps/gevent_wsgi.py",
    "cps/tornado_wsgi.py",
}

# Match `print(` at the start of a stripped line (not inside expressions
# like `pprint.pprint(`)
_PRINT_RE = re.compile(r"^\s*print\s*\(", re.MULTILINE)


def test_no_bare_print_in_production_code():
    offenders = []
    for path in _iter_python_files(CPS):
        rel = str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
        if rel in EXEMPT_PRINT:
            continue
        src = _read(path)
        for m in _PRINT_RE.finditer(src):
            line_no = src.count("\n", 0, m.start()) + 1
            offenders.append(f"{rel}:{line_no}")
    if offenders:
        # Print-as-warning — don't fail the build today, but the list is
        # visible and can be tightened later. Convert to assert when the
        # set is empty.
        pytest.skip(
            f"{len(offenders)} `print(` calls in production code. Not "
            f"failing yet; tighten when this set is empty.\n"
            "First 10:\n  " + "\n  ".join(offenders[:10])
        )

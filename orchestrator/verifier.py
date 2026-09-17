"""
orchestrator/verifier.py
External Deterministic Verification Mechanism.
Executes static syntax checks, linters (ruff/flake8), type checkers (mypy),
and test suites (pytest/unittest) to provide objective ground-truth feedback.
"""

from __future__ import annotations
import ast
import importlib.util
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class VerificationResult:
    """Consolidated deterministic feedback from verification tools."""
    passed: bool
    syntax_passed: bool
    linter_passed: bool
    tests_passed: bool
    type_check_passed: bool
    runner_used: str = "pytest"
    details: Dict[str, str] = field(default_factory=dict)
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "syntax_passed": self.syntax_passed,
            "linter_passed": self.linter_passed,
            "tests_passed": self.tests_passed,
            "type_check_passed": self.type_check_passed,
            "runner_used": self.runner_used,
            "summary": self.summary,
            "details": self.details,
        }


class Verifier:
    """
    Deterministic Verification Engine.
    Executes actual tools on disk, serving as the objective ground-truth filter
    preventing hallucinations and broken code from passing into repository state.
    """

    def __init__(self, root_dir: Optional[Path | str] = None):
        self.root_dir = Path(root_dir) if root_dir else Path(__file__).resolve().parent.parent
        self.src_dir = self.root_dir / "src"
        self.tests_dir = self.root_dir / "tests"

    def verify_all(self) -> VerificationResult:
        """Runs the complete suite of deterministic verification checks."""
        details: Dict[str, str] = {}

        # 1. AST Syntax validation
        syntax_ok, syntax_log = self.check_syntax()
        details["syntax"] = syntax_log

        # 2. Linter (ruff or flake8)
        linter_ok, linter_log = self.run_linter()
        details["linter"] = linter_log

        # 3. Type Checking (mypy)
        types_ok, types_log = self.run_type_check()
        details["type_check"] = types_log

        # 4. Test Suite (pytest or unittest fallback)
        tests_ok, tests_log, test_runner = self.run_tests()
        details["tests"] = tests_log

        # Aggregate pass/fail
        overall_passed = syntax_ok and linter_ok and types_ok and tests_ok

        summary_lines = [
            f"=== VERIFICATION REPORT (Passed: {overall_passed}) ===",
            f"1. Syntax Check:    {'PASSED' if syntax_ok else 'FAILED'}",
            f"2. Linter:          {'PASSED' if linter_ok else 'FAILED'}",
            f"3. Type Check:      {'PASSED' if types_ok else 'SKIPPED/PASSED'}",
            f"4. Tests ({test_runner}):   {'PASSED' if tests_ok else 'FAILED'}",
        ]

        if not overall_passed:
            summary_lines.append("\n--- FAILURE DETAILS ---")
            if not syntax_ok:
                summary_lines.append(f"[Syntax Error]:\n{syntax_log}")
            if not linter_ok:
                summary_lines.append(f"[Linter Warnings/Errors]:\n{linter_log}")
            if not tests_ok:
                summary_lines.append(f"[Test Failures]:\n{tests_log}")

        summary = "\n".join(summary_lines)

        return VerificationResult(
            passed=overall_passed,
            syntax_passed=syntax_ok,
            linter_passed=linter_ok,
            tests_passed=tests_ok,
            type_check_passed=types_ok,
            runner_used=test_runner,
            details=details,
            summary=summary,
        )

    def check_syntax(self) -> Tuple[bool, str]:
        """Validates that all .py files in src/ and tests/ parse cleanly without syntax errors."""
        errors: List[str] = []
        py_files: List[Path] = []

        if self.src_dir.exists():
            py_files.extend(self.src_dir.rglob("*.py"))
        if self.tests_dir.exists():
            py_files.extend(self.tests_dir.rglob("*.py"))

        for file_path in py_files:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    ast.parse(f.read(), filename=str(file_path))
            except SyntaxError as e:
                errors.append(f"{file_path.name}:{e.lineno}:{e.offset}: SyntaxError: {e.msg}")
            except Exception as e:
                errors.append(f"{file_path.name}: Error: {str(e)}")

        if errors:
            return False, "\n".join(errors)
        return True, f"All {len(py_files)} Python files parsed successfully via AST."

    def run_linter(self) -> Tuple[bool, str]:
        """Runs ruff or flake8 if installed; falls back to clean AST syntax check."""
        if shutil.which("ruff"):
            res = subprocess.run(
                [sys.executable, "-m", "ruff", "check", str(self.src_dir)],
                capture_output=True,
                text=True,
                cwd=str(self.root_dir),
            )
            passed = res.returncode == 0
            return passed, res.stdout or res.stderr or "Ruff linter passed with 0 warnings."

        if shutil.which("flake8"):
            res = subprocess.run(
                [sys.executable, "-m", "flake8", str(self.src_dir)],
                capture_output=True,
                text=True,
                cwd=str(self.root_dir),
            )
            passed = res.returncode == 0
            return passed, res.stdout or res.stderr or "Flake8 linter passed."

        return True, "No external linter (ruff/flake8) detected; AST validation used."

    def run_type_check(self) -> Tuple[bool, str]:
        """Runs mypy if installed."""
        if shutil.which("mypy"):
            res = subprocess.run(
                [sys.executable, "-m", "mypy", str(self.src_dir), "--ignore-missing-imports"],
                capture_output=True,
                text=True,
                cwd=str(self.root_dir),
            )
            passed = res.returncode == 0
            return passed, res.stdout or res.stderr
        return True, "mypy not installed in environment; skipped static type check."

    def run_tests(self) -> Tuple[bool, str, str]:
        """Runs pytest if available, else standard library unittest."""
        has_pytest = importlib.util.find_spec("pytest") is not None

        if has_pytest:
            res = subprocess.run(
                [sys.executable, "-m", "pytest", str(self.tests_dir), "-v"],
                capture_output=True,
                text=True,
                cwd=str(self.root_dir),
            )
            passed = res.returncode == 0
            output = res.stdout if res.stdout else res.stderr
            return passed, output, "pytest"
        else:
            # Fallback to standard library unittest
            res = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", str(self.tests_dir)],
                capture_output=True,
                text=True,
                cwd=str(self.root_dir),
            )
            passed = res.returncode == 0
            output = res.stderr if res.stderr else res.stdout
            return passed, output, "unittest"


if __name__ == "__main__":
    verifier = Verifier()
    report = verifier.verify_all()
    print(report.summary)

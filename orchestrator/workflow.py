"""
orchestrator/workflow.py
Autonomous Development Workflow Coordinator.
Implements the State Machine Loop:
    Coder ↔ Verifier (Deterministic Checks) ↔ Reviewer
Tracks code changes via Git diff and commits verified milestones.
"""

from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure UTF-8 output on Windows terminals
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure orchestrator directory is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from session_runner import SessionRunner, SessionRole, SessionResult
from verifier import Verifier, VerificationResult


class WorkflowState(str, Enum):
    INIT = "INIT"
    CODER = "CODER"
    VERIFIER = "VERIFIER"
    REVIEWER = "REVIEWER"
    APPROVED = "APPROVED"
    FAILED = "FAILED"


@dataclass
class WorkflowContext:
    """Carries environment state and history through the workflow state machine."""
    task: str
    root_dir: Path
    iteration: int = 0
    max_iterations: int = 5
    current_state: WorkflowState = WorkflowState.INIT
    last_coder_output: str = ""
    last_verification: Optional[VerificationResult] = None
    last_review_output: str = ""
    history_log: List[Dict[str, Any]] = None

    def __post_init__(self):
        if self.history_log is None:
            self.history_log = []


class AutonomousDevWorkflow:
    """
    Main State Machine Controller.
    Coordinates Coder ↔ Verifier ↔ Reviewer with isolated sessions and git diff tracking.
    """

    def __init__(self, root_dir: Optional[Path | str] = None, max_iterations: int = 5):
        self.root_dir = Path(root_dir) if root_dir else Path(__file__).resolve().parent.parent
        self.max_iterations = max_iterations
        self.session_runner = SessionRunner()
        self.verifier = Verifier(root_dir=self.root_dir)

    # ---------------- Git Tracking Helpers ----------------

    def get_git_diff(self) -> str:
        """Extracts current unstaged and staged git diffs."""
        try:
            diff_proc = subprocess.run(
                ["git", "diff", "HEAD"],
                capture_output=True,
                text=True,
                cwd=str(self.root_dir),
            )
            if diff_proc.returncode != 0:
                diff_proc = subprocess.run(
                    ["git", "diff"],
                    capture_output=True,
                    text=True,
                    cwd=str(self.root_dir),
                )
            status_proc = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                cwd=str(self.root_dir),
            )
            output = ""
            if status_proc.stdout:
                output += f"--- Working Tree Status ---\n{status_proc.stdout}\n"
            if diff_proc.stdout:
                output += f"--- Git Diff ---\n{diff_proc.stdout}\n"
            return output or "[No local git modifications detected]"
        except Exception as e:
            return f"[Error querying git diff: {str(e)}]"

    def commit_changes(self, message: str) -> bool:
        """Stages verified changes in src/ and tests/ and commits them."""
        try:
            subprocess.run(["git", "add", "src", "tests"], cwd=str(self.root_dir), check=True)
            commit_res = subprocess.run(
                ["git", "commit", "-m", message],
                capture_output=True,
                text=True,
                cwd=str(self.root_dir),
            )
            print(f"[Git Commit]: {commit_res.stdout.strip()}")
            return commit_res.returncode == 0
        except subprocess.CalledProcessError as e:
            print(f"[Git Commit Warning]: {e}")
            return False

    # ---------------- State Machine Execution ----------------

    def run(self, task: str) -> Dict[str, Any]:
        """
        Executes the autonomous Coder ↔ Verifier ↔ Reviewer loop.
        """
        ctx = WorkflowContext(task=task, root_dir=self.root_dir, max_iterations=self.max_iterations)
        print(f"\n{'='*60}")
        print(f"[START] Autonomous Dev Workflow for task:\n'{task}'")
        print(f"{'='*60}\n")

        ctx.current_state = WorkflowState.CODER

        while ctx.iteration < ctx.max_iterations:
            ctx.iteration += 1
            print(f"\n--- [Iteration {ctx.iteration}/{ctx.max_iterations}] State: {ctx.current_state.value} ---")

            # -------------------------------------------------------------
            # 1. CODER STEP: Ephemeral session mounts Coder Prompt
            # -------------------------------------------------------------
            if ctx.current_state == WorkflowState.CODER:
                print("[CODER] Spawning isolated Coder Session (KV Cache isolated)...")

                coder_context = {
                    "task": ctx.task,
                    "iteration": ctx.iteration,
                    "previous_verification_summary": (
                        ctx.last_verification.summary if ctx.last_verification else "None (Initial run)"
                    ),
                    "reviewer_feedback": ctx.last_review_output or "None",
                    "current_git_diff": self.get_git_diff(),
                }

                coder_prompt = (
                    f"Task: {ctx.task}\n\n"
                    "Implement or refine the code to satisfy all requirements and ensure all tests pass.\n"
                    "Address any linter or test failures shown in the context."
                )

                coder_result: SessionResult = self.session_runner.run_ephemeral(
                    role=SessionRole.CODER,
                    prompt=coder_prompt,
                    context=coder_context,
                )
                ctx.last_coder_output = coder_result.content
                ctx.history_log.append({"round": ctx.iteration, "agent": "Coder", "output": coder_result.content})
                print(f"[CODER] Turn complete ({len(coder_result.content)} chars).")

                # Transition to external deterministic verification
                ctx.current_state = WorkflowState.VERIFIER

            # -------------------------------------------------------------
            # 2. VERIFIER STEP: Deterministic static & test checks
            # -------------------------------------------------------------
            if ctx.current_state == WorkflowState.VERIFIER:
                print("[VERIFIER] Executing external deterministic Verifier (Syntax, Linter, pytest)...")
                verification: VerificationResult = self.verifier.verify_all()
                ctx.last_verification = verification
                ctx.history_log.append({"round": ctx.iteration, "agent": "Verifier", "result": verification.to_dict()})
                print(verification.summary)

                if not verification.passed:
                    print("[VERIFIER] Checks failed. Looping back to Coder with deterministic error trace...")
                    ctx.current_state = WorkflowState.CODER
                    continue
                else:
                    print("[VERIFIER] All checks passed! Escalating to Reviewer for code audit...")
                    ctx.current_state = WorkflowState.REVIEWER

            # -------------------------------------------------------------
            # 3. REVIEWER STEP: Ephemeral session audits diff & quality
            # -------------------------------------------------------------
            if ctx.current_state == WorkflowState.REVIEWER:
                print("[REVIEWER] Spawning isolated Reviewer Session (KV Cache isolated)...")

                reviewer_context = {
                    "task": ctx.task,
                    "git_diff": self.get_git_diff(),
                    "verification_summary": ctx.last_verification.summary,
                }

                reviewer_prompt = (
                    f"Review the code changes for task: '{ctx.task}'.\n"
                    "All automated verification tests have passed.\n"
                    "Audit the implementation against quality, edge cases, and requirements.\n"
                    "Conclude with your explicit VERDICT line."
                )

                reviewer_result: SessionResult = self.session_runner.run_ephemeral(
                    role=SessionRole.REVIEWER,
                    prompt=reviewer_prompt,
                    context=reviewer_context,
                )
                ctx.last_review_output = reviewer_result.content
                ctx.history_log.append({"round": ctx.iteration, "agent": "Reviewer", "output": reviewer_result.content})

                print(f"[REVIEWER] Audit Output:\n{reviewer_result.content}\n")

                if "APPROVED" in reviewer_result.content.upper():
                    print("[REVIEWER] Implementation approved!")
                    ctx.current_state = WorkflowState.APPROVED
                    break
                else:
                    print("[REVIEWER] Revisions requested. Looping back to Coder...")
                    ctx.current_state = WorkflowState.CODER

        # -------------------------------------------------------------
        # 4. COMPLETION & GIT COMMIT
        # -------------------------------------------------------------
        success = ctx.current_state == WorkflowState.APPROVED
        if success:
            commit_msg = f"feat(autonomous): completed '{ctx.task}' (verified & reviewed)"
            self.commit_changes(commit_msg)
            print(f"\n[SUCCESS] Workflow completed successfully in {ctx.iteration} iterations!")
        else:
            print(f"\n[INCOMPLETE] Workflow finished without full approval after {ctx.iteration} iterations.")

        return {
            "success": success,
            "final_state": ctx.current_state.value,
            "iterations": ctx.iteration,
            "git_status": self.get_git_diff(),
            "history": ctx.history_log,
        }


def main():
    parser = argparse.ArgumentParser(description="Autonomous Dev Workflow (Coder ↔ Verifier ↔ Reviewer)")
    parser.add_argument("--task", type=str, default="Verify and run standard test suite", help="Task description")
    parser.add_argument("--max-iter", type=int, default=3, help="Max loop iterations")
    args = parser.parse_args()

    workflow = AutonomousDevWorkflow(max_iterations=args.max_iter)
    result = workflow.run(task=args.task)
    print("\nSummary Result:")
    print(json.dumps({"success": result["success"], "final_state": result["final_state"], "iterations": result["iterations"]}, indent=2))


if __name__ == "__main__":
    main()

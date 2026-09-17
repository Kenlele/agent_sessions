# Agent Sessions: Autonomous Dev Architecture

A robust, deterministic multi-agent workflow framework for autonomous software development.

## Architecture Overview

```text
my-autonomous-dev/
├── orchestrator/
│   ├── session_runner.py      # Ephemeral session manager, mounts prompt identities, isolates KV Cache
│   ├── verifier.py            # External deterministic verification (Syntax AST, Linter, pytest/unittest, mypy)
│   └── workflow.py            # Main entrypoint: State Machine Loop (Coder ↔ Verifier ↔ Reviewer) + Git Diff Tracking
├── src/                       # Production codebase (Single Source of Truth)
│   └── main.py
├── tests/                     # Deterministic test suites
│   └── test_main.py
├── requirements.txt           # Tooling dependencies
└── .git/                      # Git version control & diff tracking
```

## Key Design Principles

1. **KV Cache & Context Drift Isolation**: Instead of a bloated long-lived chat session, `session_runner.py` creates ephemeral sessions with specific prompt identities (Coder, Reviewer, Planner). Once the turn completes, the session context is closed and recycled.
2. **Objective Deterministic Verifier**: The system does not rely on LLMs guessing whether code works. `verifier.py` executes real local tools (AST validation, `ruff`/`flake8`, `mypy`, `pytest`) and passes stdout/stderr back as factual ground-truth.
3. **Single Source of Truth on Disk**: The state lives in actual code files under `src/` and `tests/` tracked via Git diffs, rather than conversational memory.
4. **Finite State Machine Loop**:
   - `CODER`: Writes code patches based on task and verifier logs.
   - `VERIFIER`: Runs tests and linters. On failure, loops back to Coder with tracebacks.
   - `REVIEWER`: Audits quality and requirements on passing code. If revision needed, loops back to Coder; if approved, commits changes to Git.

## Quickstart

### 1. Requirements
Install optional linters and test frameworks (pure Python fallbacks are included):
```bash
pip install -r requirements.txt
```

### 2. Run Autonomous Dev Workflow
Execute the state machine loop:
```bash
python orchestrator/workflow.py --task "Verify initial codebase and test suites"
```

### 3. Run Deterministic Verifier Directly
```bash
python orchestrator/verifier.py
```
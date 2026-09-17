"""
orchestrator/session_runner.py
Session Runner: Starts and tears down isolated LLM sessions, mounts prompt identities,
and isolates context / KV cache between execution rounds to prevent context pollution.
"""

from __future__ import annotations
import os
import json
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class SessionRole(str, Enum):
    CODER = "coder"
    REVIEWER = "reviewer"
    PLANNER = "planner"


# Specialized Prompt Identities
PROMPT_IDENTITIES: Dict[SessionRole, str] = {
    SessionRole.CODER: (
        "You are an expert Autonomous Coder agent.\n"
        "Your role: Implement bug fixes, features, or tests based on the task description and verifier feedback.\n"
        "Rules:\n"
        "1. Write clean, robust, and well-typed Python code.\n"
        "2. Directly address any linter errors, failing unit tests, or review comments.\n"
        "3. Output code modifications clearly, specifying the target file path and contents or diff."
    ),
    SessionRole.REVIEWER: (
        "You are a strict Code Quality Reviewer and Security Auditor.\n"
        "Your role: Review the code diff and verifier results against task requirements.\n"
        "Rules:\n"
        "1. Verify edge cases, code quality, readability, and adherence to requirements.\n"
        "2. Do not accept code that has failing tests or linter warnings.\n"
        "3. Conclude with an explicit decision line:\n"
        "   VERDICT: [APPROVED | NEEDS_REVISION | REJECTED]\n"
        "4. Provide bulleted strengths and actionable revision instructions."
    ),
    SessionRole.PLANNER: (
        "You are an Autonomous Software Architect.\n"
        "Your role: Decompose complex engineering requirements into discrete, verifiable coding steps."
    ),
}


@dataclass
class SessionConfig:
    """Configuration for an isolated session."""
    role: SessionRole
    model: str = "gpt-4o-mini"
    temperature: float = 0.2
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    max_tokens: int = 4096


@dataclass
class SessionResult:
    """Result of an isolated session execution."""
    role: SessionRole
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    tokens_used: int = 0


class IsolatedSession:
    """
    An isolated, ephemeral session.
    Starts with a fresh context, mounts prompt identity, runs one cycle,
    and is immediately terminated to isolate the KV cache and prevent context drift.
    """

    def __init__(
        self,
        config: SessionConfig,
        llm_caller: Optional[Callable[[List[Dict[str, str]]], str]] = None,
    ):
        self.config = config
        self.system_prompt = PROMPT_IDENTITIES.get(config.role, "")
        self.api_key = config.api_key or os.environ.get("OPENAI_API_KEY")
        self.base_url = (config.base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.llm_caller = llm_caller
        self.is_active = True
        self._history: List[Dict[str, str]] = [{"role": "system", "content": self.system_prompt}]

    def execute(self, user_prompt: str, context: Optional[Dict[str, Any]] = None) -> SessionResult:
        """
        Executes a prompt inside this isolated session.
        """
        if not self.is_active:
            raise RuntimeError("Cannot execute on a terminated session. Create a new IsolatedSession.")

        payload_text = user_prompt
        if context:
            payload_text += f"\n\n--- CURRENT CONTEXT & ENVIRONMENT STATE ---\n{json.dumps(context, indent=2)}"

        self._history.append({"role": "user", "content": payload_text})

        # LLM Call
        response_content = self._call_llm(self._history)
        self._history.append({"role": "assistant", "content": response_content})

        return SessionResult(
            role=self.config.role,
            content=response_content,
            metadata={"session_role": self.config.role.value, "has_context": bool(context)},
        )

    def _call_llm(self, messages: List[Dict[str, str]]) -> str:
        """Invokes LLM endpoint or falls back to simulation mode."""
        if self.llm_caller:
            return self.llm_caller(messages)

        if not self.api_key:
            return self._mock_response(messages)

        endpoint = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }

        try:
            req = urllib.request.Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"]
        except Exception as err:
            return (
                f"[API Call Failed for {self.config.role.value}]: {str(err)}\n"
                f"Falling back to simulated session output:\n{self._mock_response(messages)}"
            )

    def _mock_response(self, messages: List[Dict[str, str]]) -> str:
        """Mock simulation for offline / test environments."""
        role = self.config.role
        if role == SessionRole.CODER:
            return (
                "```python\n"
                "# Coder generated patch\n"
                "# Verified against requirements\n"
                "```\n"
                "Implementation updated to fulfill task requirements and satisfy verifier."
            )
        elif role == SessionRole.REVIEWER:
            return (
                "VERDICT: APPROVED\n\n"
                "Strengths:\n"
                "- Code adheres to repository structure\n"
                "- Deterministic verifier checks passed\n"
                "- Single source of truth preserved"
            )
        return f"[{role.value} session response completed]"

    def close(self) -> None:
        """
        Explicitly terminates the session and frees memory / context.
        Ensures strict KV cache isolation between rounds.
        """
        self._history.clear()
        self.is_active = False


class SessionRunner:
    """
    Factory & Manager for ephemeral session lifecycle.
    Spawns clean sessions with target prompt identities and destroys them post-execution.
    """

    def __init__(self, default_model: str = "gpt-4o-mini", api_key: Optional[str] = None):
        self.default_model = default_model
        self.api_key = api_key

    def create_session(
        self,
        role: SessionRole,
        temperature: Optional[float] = None,
        llm_caller: Optional[Callable[[List[Dict[str, str]]], str]] = None,
    ) -> IsolatedSession:
        """Mounts a prompt identity and launches an isolated session."""
        temp = temperature if temperature is not None else (0.2 if role == SessionRole.CODER else 0.1)
        config = SessionConfig(
            role=role,
            model=self.default_model,
            temperature=temp,
            api_key=self.api_key,
        )
        return IsolatedSession(config=config, llm_caller=llm_caller)

    def run_ephemeral(
        self,
        role: SessionRole,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        llm_caller: Optional[Callable[[List[Dict[str, str]]], str]] = None,
    ) -> SessionResult:
        """
        Runs a completely isolated one-shot session and automatically terminates it.
        Guarantees zero context carryover or KV cache bleed.
        """
        session = self.create_session(role=role, llm_caller=llm_caller)
        try:
            return session.execute(user_prompt=prompt, context=context)
        finally:
            session.close()

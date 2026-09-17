"""
src/main.py
Single Source of Truth - Application Implementation.
"""

from typing import Any, Dict, List, Optional


class TaskProcessor:
    """Core processor for autonomous dev workflow execution."""

    def __init__(self, name: str = "DefaultProcessor") -> None:
        self.name: str = name
        self.processed_tasks: List[Dict[str, Any]] = []

    def execute_task(self, task_name: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Executes a discrete task and records execution state.
        """
        if not task_name or not isinstance(task_name, str):
            raise ValueError("task_name must be a non-empty string.")

        record = {
            "task_name": task_name.strip(),
            "status": "completed",
            "payload": payload or {},
            "processor": self.name,
        }
        self.processed_tasks.append(record)
        return record

    def get_task_count(self) -> int:
        """Returns the total number of tasks processed so far."""
        return len(self.processed_tasks)

    def reset(self) -> None:
        """Clears execution history."""
        self.processed_tasks.clear()


def main() -> None:
    """Entrypoint for the src application."""
    processor = TaskProcessor(name="AutonomousDevRunner")
    result = processor.execute_task("sample_task", {"detail": "Initial setup test"})
    print(f"Executed: {result}")


if __name__ == "__main__":
    main()

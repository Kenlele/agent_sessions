"""
tests/test_main.py
Unit tests verifying src/main.py functionality.
Compatible with both pytest and standard library unittest.
"""

import sys
import unittest
from pathlib import Path

# Ensure src is in python path
src_dir = Path(__file__).resolve().parent.parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from main import TaskProcessor


class TestTaskProcessor(unittest.TestCase):
    """Test suite for TaskProcessor."""

    def setUp(self):
        self.processor = TaskProcessor(name="TestProcessor")

    def test_task_processor_initialization(self):
        self.assertEqual(self.processor.name, "TestProcessor")
        self.assertEqual(self.processor.get_task_count(), 0)

    def test_task_processor_execute(self):
        result = self.processor.execute_task("build_feature", {"version": "1.0"})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["task_name"], "build_feature")
        self.assertEqual(self.processor.get_task_count(), 1)

    def test_task_processor_invalid_name(self):
        with self.assertRaises(ValueError):
            self.processor.execute_task("")

    def test_task_processor_reset(self):
        self.processor.execute_task("t1")
        self.assertEqual(self.processor.get_task_count(), 1)
        self.processor.reset()
        self.assertEqual(self.processor.get_task_count(), 0)


if __name__ == "__main__":
    unittest.main()

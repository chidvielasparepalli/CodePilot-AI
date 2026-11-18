from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bot import _html_to_text
from core.extractor import normalize_language
from core.progress import load_progress, mark_completed, mark_failed, save_progress
from core.solver import _response_text, generate_code, strip_code_fence
from core.submitter import classify_result


class LanguageTests(unittest.TestCase):
    def test_language_aliases_and_extensions(self):
        cases = {
            "Python 3": "python", "py": "python", "ace/mode/python": "python",
            "JavaScript": "javascript", "main.js": "javascript",
            "Java": "java", "C++": "c++", "solution.cpp": "c++", "ace/mode/c_cpp": "c++",
            "C": "c", "main.c": "c", "SQL": "sql",
            "HTML": "html", "CSS": "css", "C#": "unknown", None: "unknown",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_language(raw), expected)


class ApiHtmlExtractionTests(unittest.TestCase):
    def test_html_statement_is_decoded_with_real_line_breaks(self):
        text = _html_to_text("<p>Print <b>2</b></p><pre>4\n5</pre>")
        self.assertIn("Print 2", text)
        self.assertIn("4", text)
        self.assertIn("5", text)
        self.assertNotIn("\\n", text)


class SolverTests(unittest.TestCase):
    def test_response_parser_joins_text_parts(self):
        payload = {"candidates": [{"content": {"parts": [
            {"text": "line one"}, {"text": "line two"}
        ]}}]}
        self.assertEqual(_response_text(payload), "line one\nline two")

    def test_empty_candidate_is_reported(self):
        with self.assertRaises(RuntimeError):
            _response_text({"candidates": []})

    def test_code_fence_is_removed(self):
        fence = chr(96) * 3
        source = f"{fence}python\nprint('hello')\n{fence}"
        self.assertEqual(strip_code_fence(source, "python"), "print('hello')\n")

    def test_feedback_is_sent_to_repair_prompt(self):
        problem = "Read two integers and print their sum."
        first_code = "print('wrong')"
        with patch("core.solver.call_gemini", return_value="print(a + b)") as mocked:
            code = generate_code(
                problem, "python",
                previous_code=first_code,
                feedback="NameError: a is not defined; read input first.",
            )
        self.assertEqual(code, "print(a + b)\n")
        prompt = mocked.call_args.args[0]
        self.assertIn("NameError", prompt)
        self.assertIn(first_code, prompt)
        self.assertIn(problem, prompt)


    def test_platform_template_and_reference_cases_are_in_prompt(self):
        with patch("core.solver.call_gemini", return_value="class Solution { public: int solve(int n) { return n; } };") as mocked:
            generate_code(
                "Implement the requested method.",
                "c++",
                starter_code="class Solution { public: int solve(int n) { } };",
                test_cases=[{"input": "5", "output": "120"}],
            )
        prompt = mocked.call_args.args[0]
        self.assertIn("PLATFORM STARTER CODE", prompt)
        self.assertIn("class Solution", prompt)
        self.assertIn("REFERENCE TEST CASES", prompt)
        self.assertIn("Expected output:", prompt)
        self.assertIn("120", prompt)


class ResultTests(unittest.TestCase):
    def test_accepted_is_passed(self):
        self.assertEqual(classify_result("Accepted - all test cases passed"), "passed")

    def test_failure_overrides_pass_count(self):
        self.assertEqual(
            classify_result("3 test cases passed, 1 test case failed: Wrong Answer"),
            "failed",
        )

    def test_compilation_error_is_failed(self):
        self.assertEqual(classify_result("Compilation Error at line 4"), "failed")

    def test_submission_received_is_not_accepted(self):
        self.assertEqual(classify_result("Submission received successfully"), "submitted")

    def test_unknown_is_not_assumed_success(self):
        self.assertEqual(classify_result("Your code is being judged"), "unknown")


class ProgressTests(unittest.TestCase):
    def test_round_trip_and_status_updates(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "progress.json"
            state = load_progress(path)
            mark_completed(state, "Question A")
            mark_failed(state, "Question B")
            save_progress(state, path)
            loaded = load_progress(path)
            self.assertEqual(loaded["completed"], ["Question A"])
            self.assertEqual(loaded["failed"], ["Question B"])

    def test_acceptance_removes_previous_failure(self):
        state = {"completed": [], "failed": ["Question A"], "current_page": 1}
        mark_completed(state, "Question A")
        self.assertEqual(state["completed"], ["Question A"])
        self.assertEqual(state["failed"], [])

    def test_invalid_progress_does_not_crash(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "progress.json"
            path.write_text("{broken", encoding="utf-8")
            self.assertEqual(load_progress(path)["completed"], [])


if __name__ == "__main__":
    unittest.main()

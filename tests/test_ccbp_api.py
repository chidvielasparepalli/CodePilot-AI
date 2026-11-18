from __future__ import annotations

import json
import urllib.error
import unittest
from unittest.mock import MagicMock, patch

from core.ccbp_api import (
    API_BASE,
    CCBPApiClient,
    CCBPApiError,
    BrowserTokenCapture,
    SubmissionOutcomeUnknown,
    build_payload,
)


class PayloadTests(unittest.TestCase):
    def test_payload_is_double_encoded_as_expected(self):
        inner = {"question_id": "abc", "should_mark_attempted": True}
        payload = build_payload(inner)
        self.assertEqual(payload["clientKeyDetailsId"], 1)
        encoded_inner = json.loads(payload["data"])
        self.assertIsInstance(encoded_inner, str)
        self.assertEqual(json.loads(encoded_inner), inner)


class BrowserTokenCaptureTests(unittest.TestCase):
    def test_captures_only_token_from_successful_ccbp_response(self):
        page = MagicMock()
        capture = BrowserTokenCapture()
        capture.attach(page)
        self.assertEqual(page.on.call_args.args[0], "response")
        handler = page.on.call_args.args[1]

        def response(url, status, headers):
            request = MagicMock()
            request.url = url
            request.headers = headers
            result = MagicMock()
            result.url = url
            result.status = status
            result.request = request
            return result

        external = response(
            "https://example.com/api",
            200,
            {"authorization": "Bearer external-token"},
        )
        handler(external)
        self.assertIsNone(capture.token)

        unauthorized = response(
            API_BASE + "/api/first",
            401,
            {"authorization": "Bearer rejected-token"},
        )
        handler(unauthorized)
        self.assertIsNone(capture.token)

        successful = response(
            API_BASE + "/api/second",
            200,
            {
                "authorization": "Bearer valid-session-token",
                "x-app-version": "1140",
                "x-browser-session-id": "current-browser-session",
                "user-agent": "Chrome-Test/1.0",
                "sec-ch-ua": '"Chromium";v="145"',
                "cookie": "must-not-capture",
            },
        )
        handler(successful)
        self.assertEqual(capture.token, "valid-session-token")
        self.assertEqual(capture.app_version, "1140")
        self.assertEqual(capture.browser_session_id, "current-browser-session")
        self.assertEqual(capture.browser_headers.get("user-agent"), "Chrome-Test/1.0")
        self.assertNotIn("cookie", capture.browser_headers)
        self.assertEqual(capture.source_status, 200)
        self.assertEqual(capture.source_path, "/api/second")


class ApiClientTests(unittest.TestCase):
    def setUp(self):
        self.client = CCBPApiClient("unit-test-token")

    def test_client_forwards_browser_headers_but_not_cookie(self):
        client = CCBPApiClient(
            "unit-test-token",
            browser_headers={
                "user-agent": "Chrome-Test/1.0",
                "sec-ch-ua": '"Chromium";v="145"',
                "cookie": "must-not-forward",
            },
        )
        response = MagicMock()
        response.read.return_value = b"{}"
        manager = MagicMock()
        manager.__enter__.return_value = response
        manager.__exit__.return_value = False
        with patch("core.ccbp_api.urllib.request.urlopen", return_value=manager) as opened:
            client._post("/api/test/", {"x": 1})
        request = opened.call_args.args[0]
        self.assertEqual(request.get_header("User-agent"), "Chrome-Test/1.0")
        self.assertEqual(request.get_header("Sec-ch-ua"), '"Chromium";v="145"')
        self.assertIsNone(request.get_header("Cookie"))

    def test_question_detail_uses_question_ids(self):
        expected = {"question_id": "q-1", "question": {"content": "Task"}}
        with patch.object(
            self.client,
            "_post",
            return_value={"questions": [expected]},
        ) as post:
            actual = self.client.get_coding_question("q-1")
        self.assertEqual(actual, expected)
        post.assert_called_once_with(
            "/api/nkb_coding_practice/user/coding/questions/",
            {"question_ids": ["q-1"]},
        )

    def test_start_question_marks_it_attempted(self):
        with patch.object(self.client, "_post", return_value={}) as post:
            self.client.start_coding_question("q-2")
        post.assert_called_once_with(
            "/api/nkb_coding_practice/coding/question/start/",
            {"question_id": "q-2", "should_mark_attempted": True},
            allow_empty=True,
        )

    def test_save_code_uses_platform_save_endpoint_and_encoded_source(self):
        with patch.object(self.client, "_post", return_value={}) as post:
            self.client.save_coding_answer("q-save", "print('saved')\n", "python")
        post.assert_called_once()
        endpoint, body = post.call_args.args[:2]
        self.assertEqual(endpoint, "/api/nkb_coding_practice/question/coding/save/")
        answer = body["responses"][0]
        self.assertEqual(answer["question_id"], "q-save")
        self.assertEqual(answer["coding_answer"]["language"], "PYTHON")
        self.assertEqual(json.loads(answer["coding_answer"]["code_content"]), "print('saved')\n")

    def test_submission_encodes_source_and_parses_correct(self):
        response = {
            "submission_result": [{
                "question_id": "q-3",
                "evaluation_result": "CORRECT",
                "passed_test_cases_count": 4,
                "total_test_cases_count": 4,
            }]
        }
        with patch.object(self.client, "_post", return_value=response) as post:
            result = self.client.submit_coding_question(
                "q-3", "print('hello')\n", "python", time_spent_seconds=7
            )

        self.assertEqual(result.verdict, "passed")
        self.assertEqual(result.passed_tests, 4)
        self.assertEqual(result.total_tests, 4)
        body = post.call_args.args[1]
        answer = body["responses"][0]
        self.assertEqual(answer["question_id"], "q-3")
        self.assertEqual(answer["time_spent"], 7)
        self.assertEqual(answer["coding_answer"]["language"], "PYTHON")
        self.assertEqual(
            json.loads(answer["coding_answer"]["code_content"]),
            "print('hello')\n",
        )

    def test_incorrect_result_preserves_feedback(self):
        response = {
            "submission_result": [{
                "question_id": "q-4",
                "evaluation_result": "INCORRECT",
                "passed_test_cases_count": 1,
                "total_test_cases_count": 3,
                "failing_test_case_details": {"case": 2, "expected": "8", "actual": "7"},
                "error_explanation_details": {"message": "Wrong output"},
            }]
        }
        with patch.object(self.client, "_post", return_value=response):
            result = self.client.submit_coding_question(
                "q-4", "print(7)", "python", time_spent_seconds=3
            )
        self.assertEqual(result.verdict, "failed")
        self.assertIn("Wrong output", result.feedback)
        self.assertIn('"expected": "8"', result.feedback)

    def test_uncertain_network_error_is_not_safe_to_retry(self):
        with patch.object(
            self.client,
            "_post",
            side_effect=CCBPApiError("network unavailable"),
        ):
            with self.assertRaises(SubmissionOutcomeUnknown):
                self.client.submit_coding_question(
                    "q-5", "print(1)", "python", time_spent_seconds=2
                )

    def test_http_rejection_keeps_status_for_caller(self):
        error = urllib.error.HTTPError(
            API_BASE + "/api/test", 429, "rate limited", {}, None
        )
        with patch("core.ccbp_api.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(CCBPApiError) as caught:
                self.client._post("/api/test", {"question_id": "q"})
        self.assertEqual(caught.exception.status_code, 429)

    def test_unknown_language_is_rejected_before_network(self):
        with patch.object(self.client, "_post") as post:
            with self.assertRaises(ValueError):
                self.client.submit_coding_question(
                    "q-6", "solution", "c", time_spent_seconds=1
                )
            post.assert_not_called()


if __name__ == "__main__":
    unittest.main()

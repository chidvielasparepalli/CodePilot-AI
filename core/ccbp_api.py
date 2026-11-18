"""Experimental CCBP coding API adapter.

The endpoint contract is based on the public niatbuttcracker reference:
https://github.com/pragnyanramtha/niatbuttcracker

These are undocumented platform endpoints, not a public CCBP API. This adapter
uses only the currently signed-in browser's bearer token, keeps it in memory,
sends one question at a time, and never simulates time or retries uncertain
submissions.
"""
from __future__ import annotations

import json
import time
import uuid
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

API_BASE = "https://nkb-backend-ccbp-prod-apis.ccbp.in"
LEARNING_ORIGIN = "https://learning.ccbp.in"
FORWARDED_BROWSER_HEADERS = {
    "accept-language",
    "sec-ch-ua",
    "sec-ch-ua-mobile",
    "sec-ch-ua-platform",
    "sec-fetch-dest",
    "sec-fetch-mode",
    "sec-fetch-site",
    "user-agent",
}

GET_CODING_QUESTIONS = "/api/nkb_coding_practice/user/coding/questions/"
START_CODING_QUESTION = "/api/nkb_coding_practice/coding/question/start/"
SAVE_CODING_ANSWER = "/api/nkb_coding_practice/question/coding/save/"
SUBMIT_CODING_ANSWER = "/api/nkb_coding_practice/question/coding/submit/"

LANGUAGE_TO_API = {
    "python": "PYTHON",
    "javascript": "NODE_JS",
    "java": "JAVA",
    "c++": "CPP",
}


class CCBPApiError(RuntimeError):
    """A definite CCBP API request rejection."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class SubmissionOutcomeUnknown(CCBPApiError):
    """The submit request may have reached CCBP; never auto-submit it again."""


@dataclass(frozen=True)
class ApiSubmissionResult:
    verdict: str
    feedback: str
    passed_tests: int | None = None
    total_tests: int | None = None
    raw: dict[str, Any] | None = None


def build_payload(inner: dict[str, Any]) -> dict[str, Any]:
    """Build CCBP's double-encoded JSON envelope."""
    inner_json = json.dumps(inner, ensure_ascii=False, separators=(",", ":"))
    return {
        "data": json.dumps(inner_json, ensure_ascii=False),
        "clientKeyDetailsId": 1,
    }


class BrowserTokenCapture:
    """Capture the bearer token from the authenticated browser's own API calls."""

    def __init__(self) -> None:
        self._token: str | None = None
        self.app_version: str | None = None
        self.browser_session_id: str | None = None
        self.browser_headers: dict[str, str] = {}
        self.source_path: str | None = None
        self.source_status: int | None = None
        self._attached = False

    @property
    def token(self) -> str | None:
        return self._token

    def attach(self, page) -> None:
        """Capture only a bearer token used by a successful backend response."""
        if self._attached:
            return

        def on_response(response) -> None:
            if self._token or not response.url.startswith(API_BASE + "/"):
                return
            try:
                status = int(response.status)
                if status < 200 or status >= 400:
                    return
                headers = response.request.headers
                authorization = next(
                    (value for key, value in headers.items() if key.lower() == "authorization"),
                    "",
                )
                if not authorization.lower().startswith("bearer "):
                    return

                candidate = authorization[7:].strip()
                if not candidate:
                    return

                self._token = candidate
                self.app_version = next(
                    (value for key, value in headers.items() if key.lower() == "x-app-version"),
                    None,
                )
                self.browser_session_id = next(
                    (value for key, value in headers.items() if key.lower() == "x-browser-session-id"),
                    None,
                )
                self.browser_headers = {
                    key.lower(): value
                    for key, value in headers.items()
                    if key.lower() in FORWARDED_BROWSER_HEADERS
                }
                self.source_path = urlparse(response.url).path
                self.source_status = status
            except Exception:
                # Request/response inspection must never interrupt page activity.
                return

        page.on("response", on_response)
        self._attached = True

    def wait(self, page, timeout_seconds: float = 8.0) -> str | None:
        """Wait briefly for the SPA to make an authenticated API request."""
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        while not self._token and time.monotonic() < deadline:
            try:
                page.wait_for_timeout(150)
            except Exception:
                break
        return self._token


class CCBPApiClient:
    """Small serial client for CCBP's coding-question endpoints."""

    def __init__(
        self,
        bearer_token: str,
        timeout_seconds: int = 25,
        app_version: str = "1128",
        browser_session_id: str | None = None,
        browser_headers: dict[str, str] | None = None,
    ) -> None:
        token = (bearer_token or "").strip()
        if not token:
            raise ValueError("A signed-in CCBP browser token is required.")
        self._token = token
        self.timeout_seconds = max(5, int(timeout_seconds))
        self.app_version = str(app_version)
        self.browser_session_id = browser_session_id or str(uuid.uuid4())
        self.browser_headers = {
            key.lower(): value
            for key, value in (browser_headers or {}).items()
            if key.lower() in FORWARDED_BROWSER_HEADERS
        }

    def _post(self, endpoint: str, body: dict[str, Any], allow_empty: bool = False) -> dict[str, Any]:
        if not endpoint.startswith("/") or endpoint.startswith("//"):
            raise ValueError("Only relative CCBP API endpoints are allowed.")

        url = API_BASE + endpoint
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != urlparse(API_BASE).netloc:
            raise ValueError("Refusing to send the session token outside the CCBP API host.")

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._token}",
            "Origin": LEARNING_ORIGIN,
            "Referer": LEARNING_ORIGIN + "/",
            "x-app-version": self.app_version,
            "x-browser-session-id": self.browser_session_id,
        }
        # Forward only browser compatibility headers from the authenticated
        # CCBP request. Never forward cookies, host, content-length or secrets
        # other than the in-memory bearer token set explicitly above.
        headers.update(self.browser_headers)

        request = urllib.request.Request(
            url,
            data=json.dumps(build_payload(body), ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            # Do not log response bodies: platform responses can contain account data.
            raise CCBPApiError(
                f"CCBP API rejected {endpoint} (HTTP {exc.code}).",
                status_code=exc.code,
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CCBPApiError(
                f"Could not complete CCBP API request to {endpoint}: {type(exc).__name__}."
            ) from None

        if not raw.strip() and allow_empty:
            return {}
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise CCBPApiError(f"CCBP API returned invalid JSON for {endpoint}.") from None

        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                raise CCBPApiError(f"CCBP API returned an unexpected payload for {endpoint}.") from None

        if not isinstance(result, dict):
            raise CCBPApiError(f"CCBP API returned an unexpected response for {endpoint}.")
        return result

    @staticmethod
    def _unwrap(result: dict[str, Any]) -> dict[str, Any]:
        """Handle direct responses and common object/string data wrappers."""
        nested = result.get("data")
        if isinstance(nested, dict):
            return nested
        if isinstance(nested, str):
            try:
                decoded = json.loads(nested)
                if isinstance(decoded, dict):
                    inner = decoded.get("data")
                    return inner if isinstance(inner, dict) else decoded
            except json.JSONDecodeError:
                pass
        return result

    def get_coding_question(self, question_id: str) -> dict[str, Any] | None:
        """Fetch one coding question's template and test cases."""
        if not question_id:
            raise ValueError("question_id is required.")
        result = self._unwrap(
            self._post(GET_CODING_QUESTIONS, {"question_ids": [question_id]})
        )
        questions = result.get("questions")
        if not isinstance(questions, list):
            return None
        for question in questions:
            if isinstance(question, dict) and question.get("question_id") == question_id:
                return question
        return None

    def start_coding_question(self, question_id: str) -> None:
        if not question_id:
            raise ValueError("question_id is required.")
        self._post(
            START_CODING_QUESTION,
            {"question_id": question_id, "should_mark_attempted": True},
            allow_empty=True,
        )

    def save_coding_answer(self, question_id: str, code: str, language: str) -> None:
        """Persist the generated code as the platform's saved draft."""
        api_language = LANGUAGE_TO_API.get((language or "").lower())
        if not question_id or not api_language:
            raise ValueError("A question ID and supported language are required to save code.")
        self._post(
            SAVE_CODING_ANSWER,
            {
                "responses": [{
                    "question_id": question_id,
                    "coding_answer": {
                        "code_content": json.dumps(code, ensure_ascii=False),
                        "language": api_language,
                    },
                }]
            },
            allow_empty=True,
        )

    def submit_coding_question(
        self,
        question_id: str,
        code: str,
        language: str,
        time_spent_seconds: int,
    ) -> ApiSubmissionResult:
        """Submit once and return the synchronous judge verdict.

        If transport fails after the request is sent, the outcome is ambiguous.
        The caller must not blindly submit the same answer through the UI.
        """
        api_language = LANGUAGE_TO_API.get((language or "").lower())
        if not api_language:
            raise ValueError(f"CCBP API submission does not support language '{language}'.")

        request_body = {
            "responses": [{
                "question_id": question_id,
                "time_spent": max(1, int(time_spent_seconds)),
                "coding_answer": {
                    "code_content": json.dumps(code, ensure_ascii=False),
                    "language": api_language,
                },
            }]
        }

        try:
            result = self._unwrap(self._post(SUBMIT_CODING_ANSWER, request_body))
        except CCBPApiError as exc:
            if exc.status_code is None or exc.status_code >= 500:
                raise SubmissionOutcomeUnknown(
                    "The API submission may have reached CCBP, but no response was received. "
                    "Check the portal before retrying."
                ) from exc
            raise

        submissions = result.get("submission_result")
        if not isinstance(submissions, list) or not submissions:
            raise SubmissionOutcomeUnknown(
                "CCBP received a submission request but returned no readable evaluation result."
            )

        item = next(
            (
                entry for entry in submissions
                if isinstance(entry, dict) and entry.get("question_id") == question_id
            ),
            submissions[0] if isinstance(submissions[0], dict) else {},
        )
        status = str(item.get("evaluation_result") or "UNKNOWN").upper()
        verdict = "passed" if status == "CORRECT" else "failed" if status == "INCORRECT" else "unknown"

        feedback_parts = []
        for field in (
            "error_explanation_details",
            "failing_test_case_details",
            "reason_for_error",
            "reason_for_failures",
        ):
            value = item.get(field)
            if value:
                feedback_parts.append(
                    value if isinstance(value, str)
                    else json.dumps(value, ensure_ascii=False, indent=2, default=str)
                )
        feedback = "\n".join(feedback_parts).strip()

        def optional_int(value):
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        return ApiSubmissionResult(
            verdict=verdict,
            feedback=feedback,
            passed_tests=optional_int(item.get("passed_test_cases_count")),
            total_tests=optional_int(item.get("total_test_cases_count")),
            raw=item,
        )

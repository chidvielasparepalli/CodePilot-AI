"""CCBP Question Bank automation with Gemini judge-feedback retries."""
from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from html import unescape
from html.parser import HTMLParser

from dotenv import dotenv_values, load_dotenv

from core.auth import ensure_authenticated
from core.ccbp_api import (
    BrowserTokenCapture,
    CCBPApiClient,
    CCBPApiError,
    SubmissionOutcomeUnknown,
    LANGUAGE_TO_API,
)
from core.browser import LMS_URL, start_browser
from core.editor import inject_code, read_editor_value
from core.extractor import detect_language, extract_problem
from core.filters import apply_unsolved_filters
from core.navigator import (
    get_unsolved_questions,
    go_to_next_page,
    open_question,
    open_question_bank,
    return_to_question_bank,
)
from core.progress import (
    is_completed,
    load_progress,
    mark_completed,
    mark_failed,
    save_progress,
)
from core.solver import generate_code
from core.submitter import check_results, extract_feedback, snapshot_result, submit_code

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=True)

MAX_ATTEMPTS = max(1, int(os.getenv("MAX_ATTEMPTS_PER_QUESTION", "6")))
MAX_PAGES = max(1, int(os.getenv("MAX_QUESTION_BANK_PAGES", "500")))
RESULT_TIMEOUT = max(10, int(os.getenv("RESULT_TIMEOUT_SECONDS", "50")))
MAX_CONSECUTIVE_ERRORS = max(1, int(os.getenv("MAX_CONSECUTIVE_ERRORS", "8")))
CCBP_API_MODE = os.getenv("CCBP_API_MODE", "api").strip().lower()


def log(message: str) -> None:
    print(f"[BOT] {message}", flush=True)


def question_key(item: dict) -> str:
    return (item.get("title") or "").strip()


def _decode_api_code(value) -> str:
    if not isinstance(value, str):
        return ""
    try:
        decoded = json.loads(value)
        return decoded if isinstance(decoded, str) else value
    except json.JSONDecodeError:
        return value


class _QuestionHtmlText(HTMLParser):
    BLOCK_TAGS = {
        "p", "br", "div", "li", "ul", "ol", "pre", "code",
        "h1", "h2", "h3", "h4", "tr", "td", "th", "section",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag.lower() in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def _html_to_text(value) -> str:
    parser = _QuestionHtmlText()
    parser.feed(unescape(value or "") if isinstance(value, str) else "")
    lines = [line.strip() for line in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if line).strip()


def process_question(
    page,
    item: dict,
    progress: dict,
    token_capture: BrowserTokenCapture | None = None,
) -> bool:
    title = question_key(item)
    log(f"Opening: {title}")

    api_only = CCBP_API_MODE == "api"
    if not open_question(page, item, wait_for_editor=not api_only):
        mark_failed(progress, title, "Question/editor did not become ready.")
        save_progress(progress)
        return False

    match = re.search(r"/question/([^/?#]+)", page.url)
    question_id = match.group(1) if match else ""

    api_client = None
    if CCBP_API_MODE in {"hybrid", "api"}:
        token = (
            token_capture.token or token_capture.wait(page, timeout_seconds=4.0)
            if token_capture is not None else None
        )
        if token:
            api_client = CCBPApiClient(
                token,
                timeout_seconds=int(os.getenv("CCBP_API_TIMEOUT_SECONDS", "25")),
                app_version=token_capture.app_version or os.getenv("CCBP_APP_VERSION", "1128"),
                browser_session_id=token_capture.browser_session_id,
                browser_headers=token_capture.browser_headers,
            )
            log(f"[API] Captured a successful CCBP browser session via {token_capture.source_path} (HTTP {token_capture.source_status}).")
        elif api_only:
            raise RuntimeError(
                "API-only mode could not capture a CCBP Bearer token from the signed-in browser. "
                "No code was pasted and no browser submission was attempted."
            )
        else:
            log("[API] No browser token captured; hybrid mode will use browser submission.")

    api_question = None
    if api_client and question_id:
        try:
            api_question = api_client.get_coding_question(question_id)
        except CCBPApiError as exc:
            if api_only:
                raise RuntimeError(f"API question retrieval failed: {exc}") from exc
            log(f"[API] Detail lookup unavailable ({exc}); using browser content.")

    if api_only:
        if not api_client:
            raise RuntimeError("API-only mode requires a captured CCBP session.")
        if not question_id:
            raise RuntimeError("Could not read the question ID from the CCBP question route.")
        if not api_question:
            raise RuntimeError("CCBP API did not return the requested coding question.")

        question_data = api_question.get("question") or {}
        problem = _html_to_text(question_data.get("content"))
        if len(problem) < 25:
            raise RuntimeError("CCBP API question statement was empty or unreadable.")

        code_info = api_question.get("code") or {}
        saved_info = api_question.get("latest_saved_code") or {}
        saved_code = _decode_api_code(saved_info.get("code_content"))
        default_code = _decode_api_code(code_info.get("code_content"))
        starter_code = saved_code or default_code
        api_language = str(code_info.get("language") or "").upper()
        language_map = {
            "PYTHON": "python",
            "NODE_JS": "javascript",
            "JAVA": "java",
            "CPP": "c++",
        }
        language = language_map.get(api_language, "unknown")
        if language == "unknown":
            raise RuntimeError(
                f"CCBP API returned unsupported starter language: {api_language or 'missing'}."
            )

        candidate_cases = api_question.get("test_cases")
        test_cases = candidate_cases if isinstance(candidate_cases, list) else []
        log(
            f"[API] Question details loaded: {len(problem)} characters, "
            f"{len(test_cases)} reference cases, language={language}."
        )
    else:
        problem = extract_problem(page)
        if not problem or len(problem.strip()) < 25:
            log("Question statement did not become stable/readable; skipping safely.")
            mark_failed(progress, title, "Question statement was not ready.")
            save_progress(progress)
            return False

        language = detect_language(page)
        if language == "unknown":
            log("Could not identify the actual coding editor language; refusing to guess.")
            mark_failed(progress, title, "Coding editor language detection failed.")
            save_progress(progress)
            return False

        starter_code = read_editor_value(page) or ""
        test_cases = None
        if api_question:
            code_info = api_question.get("code") or {}
            saved_info = api_question.get("latest_saved_code") or {}
            saved_code = _decode_api_code(saved_info.get("code_content"))
            default_code = _decode_api_code(code_info.get("code_content"))
            starter_code = saved_code or default_code or starter_code
            candidate_cases = api_question.get("test_cases")
            if isinstance(candidate_cases, list):
                test_cases = candidate_cases
            log(
                "[API] Question details loaded"
                + (f" with {len(test_cases)} reference case(s)." if test_cases is not None else ".")
            )

    log(
        f"Detected coding editor language: {language} | "
        f"question length: {len(problem)} characters"
    )

    previous_code = None
    feedback = None
    question_started = False

    for attempt in range(1, MAX_ATTEMPTS + 1):
        attempt_started_at = time.monotonic()
        log(f"Attempt {attempt}/{MAX_ATTEMPTS}")

        try:
            code = generate_code(
                problem_text=problem,
                language=language,
                previous_code=previous_code,
                feedback=feedback,
                starter_code=starter_code,
                test_cases=test_cases,
            )
        except Exception as exc:
            message = str(exc).lower()
            if any(token in message for token in ("api key", "quota", "permissions", "rate limit")):
                raise RuntimeError(str(exc)) from exc
            log(f"Gemini error: {exc}")
            mark_failed(progress, title, f"Gemini generation failed: {exc}")
            save_progress(progress)
            return False

        # API-only mode deliberately skips editor typing and browser Submit.
        if not api_only:
            if not inject_code(page, code):
                log("Actual coding editor did not contain the generated code; refusing to submit.")
                mark_failed(progress, title, "Could not verify code in actual coding editor.")
                save_progress(progress)
                return False
        else:
            log("[API] API-only mode: skipping editor typing and browser Submit.")

        verdict = "unknown"
        api_used = False
        if api_client and question_id and language in LANGUAGE_TO_API:
            try:
                if not question_started:
                    api_client.start_coding_question(question_id)
                    question_started = True
                    log("[API] Question started.")
                try:
                    api_client.save_coding_answer(question_id, code, language)
                    log("[API] Code draft saved through CCBP API.")
                except CCBPApiError as save_error:
                    log(f"[API] Draft save was not confirmed ({save_error}); continuing to judge submission.")

                api_result = api_client.submit_coding_question(
                    question_id=question_id,
                    code=code,
                    language=language,
                    time_spent_seconds=max(1, int(time.monotonic() - attempt_started_at)),
                )
                verdict = api_result.verdict
                feedback = api_result.feedback
                api_used = True
                tests_label = (
                    f" ({api_result.passed_tests}/{api_result.total_tests} tests)"
                    if api_result.passed_tests is not None and api_result.total_tests is not None
                    else ""
                )
                log(f"[API] Judge verdict: {verdict.upper()}{tests_label}")
            except SubmissionOutcomeUnknown as exc:
                log(f"[API] {exc}")
                mark_failed(progress, title, "API submission outcome unknown; inspect portal before retrying.")
                save_progress(progress)
                return False
            except CCBPApiError as exc:
                # Never auto-submit through the UI after an uncertain API submit.
                log(f"[API] Submission could not be confirmed: {exc}")
                mark_failed(progress, title, "API submission uncertain; inspect portal before retrying.")
                save_progress(progress)
                return False
        else:
            if api_only:
                raise RuntimeError(
                    "API-only submission path is unavailable for this question/language; "
                    "browser submission is disabled in API-only mode."
                )
            previous_result = snapshot_result(page)
            if not submit_code(page):
                mark_failed(progress, title, "Submit button did not become ready.")
                save_progress(progress)
                return False
            verdict = check_results(
                page,
                timeout_seconds=RESULT_TIMEOUT,
                previous_text=previous_result,
            )
            log(f"Judge verdict: {verdict.upper()}")
            feedback = extract_feedback(page) if verdict == "failed" else None

        if verdict == "passed":
            mark_completed(progress, title)
            save_progress(progress)
            log(f"ACCEPTED: {title}")
            return True

        if verdict == "unknown":
            if not feedback and not api_used:
                feedback = extract_feedback(page)
            log("No fresh explicit accepted/failed result was detected; stopping this question.")
            if feedback:
                log(f"Visible feedback captured ({len(feedback)} characters).")
            mark_failed(progress, title, "Judge result unknown; manual inspection required.")
            save_progress(progress)
            return False

        if not feedback and not api_used:
            feedback = extract_feedback(page)
        if not feedback:
            feedback = (
                "The CCBP API returned INCORRECT but did not include detailed test feedback."
                if api_used else
                "The portal reported a failed submission but did not expose detailed feedback."
            )
        previous_code = code

        if attempt < MAX_ATTEMPTS:
            log("Fresh failed verdict captured. Asking Gemini to repair the previous solution...")
        else:
            log("Maximum repair attempts reached for this question.")

    mark_failed(progress, title, f"Not accepted after {MAX_ATTEMPTS} attempts.")
    save_progress(progress)
    return False


def run() -> int:
    local_env = dotenv_values(os.path.join(PROJECT_ROOT, ".env"))
    if not (local_env.get("GEMINI_API_KEY") or "").strip():
        log("Project .env has no GEMINI_API_KEY. Add a newly rotated key before starting.")
        return 2

    progress = load_progress()
    log("=== CODEPILOT-AI | QUESTION BANK AUTOMATION ===")
    log(f"Previously accepted: {len(progress['completed'])} | Previously failed: {len(progress['failed'])}")
    log(f"Repair attempts per question: {MAX_ATTEMPTS}")
    log("Launching persistent browser session...")

    playwright = context = page = None
    token_capture = BrowserTokenCapture()
    total_passed = 0
    total_failed = 0
    consecutive_errors = 0
    run_failed: set[str] = set()
    seen_pages: set[tuple[str, ...]] = set()

    try:
        playwright, context, page = start_browser()
        token_capture.attach(page)
        page.goto(LMS_URL, timeout=120000, wait_until="domcontentloaded")
        ensure_authenticated(page)

        log("Waiting for Question Bank controls and question cards...")
        open_question_bank(page)
        apply_unsolved_filters(page)
        if CCBP_API_MODE in {"hybrid", "api"}:
            token_capture.wait(page, timeout_seconds=2.0)
            log(f"API mode: {CCBP_API_MODE.upper()} (API-only mode never types or clicks UI Submit).")
        else:
            log("API mode disabled; using browser submission.")

        for page_number in range(1, MAX_PAGES + 1):
            questions = get_unsolved_questions(page)
            fingerprint = tuple(question_key(item) for item in questions)
            if fingerprint in seen_pages:
                log("Pagination returned to an already visited page; stopping to avoid a loop.")
                break
            seen_pages.add(fingerprint)

            log(f"PAGE {page_number}: {len(questions)} visible unsolved questions")
            target = next(
                (
                    item for item in questions
                    if question_key(item)
                    and not is_completed(progress, question_key(item))
                    and question_key(item) not in run_failed
                ),
                None,
            )

            while target is not None:
                title = question_key(target)
                try:
                    accepted = process_question(page, target, progress, token_capture=token_capture)
                    if accepted:
                        total_passed += 1
                        consecutive_errors = 0
                    else:
                        total_failed += 1
                        run_failed.add(title)

                    # return_to_question_bank waits for a new stable list before
                    # the next card is considered. No fixed inter-question sleep.
                    return_to_question_bank(page)
                    questions = get_unsolved_questions(page)
                    target = next(
                        (
                            item for item in questions
                            if question_key(item)
                            and not is_completed(progress, question_key(item))
                            and question_key(item) not in run_failed
                        ),
                        None,
                    )
                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    message = str(exc).lower()
                    if any(token in message for token in ("api key", "quota", "permissions", "rate limit")):
                        raise
                    consecutive_errors += 1
                    total_failed += 1
                    run_failed.add(title)
                    log(f"Question-level error for '{title}': {str(exc)[:220]}")
                    mark_failed(progress, title, str(exc))
                    save_progress(progress)
                    try:
                        return_to_question_bank(page)
                    except Exception as recovery_error:
                        log(f"Could not return to Question Bank: {recovery_error}")
                        raise
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        log("Too many consecutive errors; stopping safely.")
                        return 2
                    questions = get_unsolved_questions(page)
                    target = next(
                        (
                            item for item in questions
                            if question_key(item)
                            and not is_completed(progress, question_key(item))
                            and question_key(item) not in run_failed
                        ),
                        None,
                    )

            if go_to_next_page(page, get_unsolved_questions(page)):
                apply_unsolved_filters(page)
                continue

            log("No more Question Bank pages were detected.")
            break

        log("========== RUN SUMMARY ==========")
        log(f"Accepted this run: {total_passed}")
        log(f"Needs retry/manual check: {total_failed}")
        log(f"Total accepted in history: {len(progress['completed'])}")
        log("Progress saved to progress.json.")
        return 0

    except KeyboardInterrupt:
        log("Stopped by user. Saving progress...")
        save_progress(progress)
        return 130
    except Exception as exc:
        log(f"FATAL: {exc}")
        traceback.print_exc()
        save_progress(progress)
        return 1
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass
        log("Browser closed; progress remains saved.")


if __name__ == "__main__":
    sys.exit(run())

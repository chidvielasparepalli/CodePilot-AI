"""Submit code and wait for a fresh, final judge verdict."""
from __future__ import annotations

import re

SUBMIT_SELECTORS = (
    "button[data-testid='submitCode']",
    "button:has-text('Submit Code')",
    "button:has-text('Submit')",
    "button:has-text('SUBMIT')",
    "[data-testid*='submit']",
    ".submit-btn",
    ".submit-button",
)

FAIL_PATTERN = re.compile(
    r"WRONG ANSWER|COMPILATION ERROR|COMPILER ERROR|RUNTIME ERROR|"
    r"TIME LIMIT EXCEEDED|MEMORY LIMIT EXCEEDED|TEST CASE\s*\d+\s*FAILED|"
    r"\bFAILED\b|\bFAILURE\b",
    re.I,
)
PASS_PATTERN = re.compile(
    r"ALL TEST CASES PASSED|ALL TESTS PASSED|TEST CASES PASSED|"
    r"ACCEPTED|SUBMISSION ACCEPTED|PASSED ALL TEST CASES|"
    r"\bPASSED\s+\d+\s+OF\s+\d+\b",
    re.I,
)
PENDING_PATTERN = re.compile(
    r"SUBMISSION IN PROGRESS|SUBMITTING|QUEUED|PENDING|COMPILING|"
    r"RUNNING TEST|JUDGING|EVALUATING|PROCESSING SUBMISSION",
    re.I,
)


def submit_code(page) -> bool:
    """Wait for the real Submit control to be ready, then click it."""
    for selector in SUBMIT_SELECTORS:
        try:
            button = page.locator(selector).first
            if not button.count():
                continue
            button.wait_for(state="visible", timeout=12000)
            page.wait_for_function(
                """selector => {
                    const button = document.querySelector(selector);
                    return !!button && !button.disabled &&
                           button.getAttribute('aria-disabled') !== 'true';
                }""",
                arg=selector,
                timeout=15000,
            )
            button.click()
            print("[SUBMIT] Submit control was ready and clicked.")
            return True
        except Exception:
            continue
    print("[SUBMIT] Submit button did not become visible and enabled.")
    return False


def _visible_result_text(page) -> str:
    snippets = []
    selectors = (
        "[data-testid*='result']",
        "[data-testid*='submission']",
        "[data-testid*='test-case']",
        "[class*='result']",
        "[class*='submission']",
        "[class*='test-case']",
        "[class*='compiler']",
        "[class*='error']",
    )
    for selector in selectors:
        try:
            locator = page.locator(selector)
            for index in range(min(locator.count(), 12)):
                item = locator.nth(index)
                if item.is_visible():
                    value = item.inner_text(timeout=500).strip()
                    if value and value not in snippets:
                        snippets.append(value)
        except Exception:
            continue

    try:
        body = page.locator("body").inner_text(timeout=2000)
        if body:
            snippets.append(body)
    except Exception:
        pass
    return "\n".join(snippets)[-14000:]


def classify_result(text: str) -> str:
    upper = (text or "").upper()
    if FAIL_PATTERN.search(upper):
        return "failed"
    if PASS_PATTERN.search(upper):
        return "passed"
    if re.search(r"\bSUBMITTED SUCCESSFULLY\b|\bSUBMISSION RECEIVED\b", upper):
        return "submitted"
    return "unknown"


def snapshot_result(page) -> str:
    """Capture currently visible judge output before a new attempt."""
    return _visible_result_text(page)


def check_results(
    page,
    timeout_seconds: int = 50,
    previous_text: str | None = None,
) -> str:
    """Wait for a changed result that has reached a final pass/fail state.

    Mutation-driven page evaluation replaces a fixed one-second polling loop.
    Pending states take priority over stale verdict text still visible nearby.
    """
    previous = (previous_text or "").strip()
    try:
        page.wait_for_function(
            """previous => {
                const visible = el => {
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 &&
                           s.display !== 'none' && s.visibility !== 'hidden';
                };
                const parts = [];
                const selectors = [
                    '[data-testid*="result"]',
                    '[data-testid*="submission"]',
                    '[data-testid*="test-case"]',
                    '[class*="result"]',
                    '[class*="submission"]',
                    '[class*="test-case"]',
                    '[class*="compiler"]',
                    '[class*="error"]'
                ];
                for (const selector of selectors) {
                    for (const node of document.querySelectorAll(selector)) {
                        if (visible(node)) {
                            const text = (node.innerText || '').trim();
                            if (text && !parts.includes(text)) parts.push(text);
                        }
                    }
                }
                const body = document.body?.innerText || '';
                if (body) parts.push(body);
                const current = parts.join('\\n').slice(-14000);
                if (!current.trim() || current.trim() === previous) return false;

                const upper = current.toUpperCase();
                const pending = /SUBMISSION IN PROGRESS|SUBMITTING|QUEUED|PENDING|COMPILING|RUNNING TEST|JUDGING|EVALUATING|PROCESSING SUBMISSION/.test(upper);
                if (pending) return false;

                const failed = /WRONG ANSWER|COMPILATION ERROR|COMPILER ERROR|RUNTIME ERROR|TIME LIMIT EXCEEDED|MEMORY LIMIT EXCEEDED|TEST CASE\\s*\\d+\\s*FAILED|\\bFAILED\\b|\\bFAILURE\\b/.test(upper);
                const passed = /ALL TEST CASES PASSED|ALL TESTS PASSED|TEST CASES PASSED|ACCEPTED|SUBMISSION ACCEPTED|PASSED ALL TEST CASES|\\bPASSED\\s+\\d+\\s+OF\\s+\\d+\\b/.test(upper);
                return failed || passed;
            }""",
            arg=previous,
            timeout=timeout_seconds * 1000,
            polling=100,
        )
    except Exception:
        print("[SUBMIT] No fresh final pass/fail verdict appeared before timeout.")
        return "unknown"

    verdict = classify_result(_visible_result_text(page))
    if verdict not in {"passed", "failed"}:
        print("[SUBMIT] Result changed, but no explicit final verdict was readable.")
        return "unknown"
    return verdict


def extract_feedback(page, max_chars: int = 7000) -> str:
    """Collect compiler and test-case details for a repair prompt."""
    text = _visible_result_text(page)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    keywords = re.compile(
        r"error|failed|wrong|expected|actual|input|output|test case|line \d+|"
        r"compil|runtime|time limit|memory limit|exception|traceback",
        re.I,
    )
    selected = []
    for line in lines:
        if keywords.search(line) and line not in selected:
            selected.append(line)
    feedback = "\n".join(selected[-45:]) or "\n".join(lines[-25:])
    return feedback[-max_chars:]

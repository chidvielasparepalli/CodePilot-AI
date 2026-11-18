"""CCBP Question Bank navigation helpers."""
from __future__ import annotations

import re
from typing import Any

from core.browser import LMS_URL
from core.waits import (
    QUESTION_ROW,
    question_rows_signature,
    wait_for_question_bank,
    wait_for_question_detail,
    wait_for_question_rows,
)

EDITOR_SELECTOR = (
    "#codingQuestionEditor, "
    ".commonCodeEditor .monaco-editor, "
    ".commonCodeEditor .ace_editor:not(.ace_autocomplete), "
    "[data-testid='code-editor'] .monaco-editor"
)


def open_question_bank(page) -> None:
    """Open the Question Bank and wait for its actual filters and rows to settle."""
    try:
        if "/problems-set" in page.url:
            wait_for_question_bank(page, timeout_ms=20000)
            return
    except Exception:
        pass

    candidates = (
        page.get_by_role("link", name="Question Bank", exact=True),
        page.get_by_role("tab", name="Question Bank", exact=True),
        page.get_by_text("Question Bank", exact=True),
    )
    for locator in candidates:
        try:
            item = locator.first
            if item.count() and item.is_visible():
                item.click()
                wait_for_question_bank(page, timeout_ms=45000)
                print("[NAV] Question Bank is ready.")
                return
        except Exception:
            continue

    page.goto(LMS_URL, timeout=90000, wait_until="domcontentloaded")
    wait_for_question_bank(page, timeout_ms=60000)
    print("[NAV] Question Bank is ready.")


def get_unsolved_questions(page) -> list[dict[str, Any]]:
    """Read the currently visible question cards from the Question Bank."""
    try:
        return page.evaluate(
            """() => {
                const rows = Array.from(document.querySelectorAll(
                    '[data-testid="question-list-question"]'
                ));
                return rows.map((row, index) => {
                    const titleNode = row.querySelector(
                        'span[title], [data-testid*="question-title"]'
                    );
                    const title = (
                        (titleNode && (titleNode.getAttribute('title') || titleNode.innerText)) ||
                        (row.innerText || '').split('\\n')[0] || ''
                    ).trim();
                    const rowText = (row.innerText || '').trim();
                    const link = row.querySelector('a[href]');
                    const status = rowText.toLowerCase();
                    return {
                        title,
                        href: link ? link.getAttribute('href') : '',
                        index,
                        rowText: rowText.slice(0, 500),
                        solved: /\\b(solved|completed|accepted)\\b/i.test(status)
                    };
                }).filter(item => item.title && !item.solved);
            }"""
        ) or []
    except Exception as exc:
        print(f"[NAV] Could not scan question rows: {exc}")
        return []


def open_question(
    page,
    question: str | dict[str, Any],
    wait_for_editor: bool = True,
) -> bool:
    """Open a card; API mode can wait only for its question route."""
    title = question["title"] if isinstance(question, dict) else str(question)
    try:
        row = page.locator(QUESTION_ROW).filter(has_text=title).first
        if row.count() and row.is_visible():
            row.scroll_into_view_if_needed()
            row.click()
        else:
            title_node = page.get_by_text(title, exact=True).first
            title_node.wait_for(state="visible", timeout=15000)
            title_node.scroll_into_view_if_needed()
            title_node.click()

        if wait_for_editor:
            # Browser mode requires the visible editor and stable statement.
            wait_for_question_detail(page, timeout_ms=60000, stable_ms=350)
        else:
            # API mode needs the question ID from the SPA route, not editor rendering.
            page.wait_for_function(
                "() => location.pathname.includes('/question/')",
                timeout=30000,
                polling=100,
            )
        print(f"[NAV] Question page is ready: {title}")
        return True
    except Exception as exc:
        print(f"[NAV] Could not open '{title}': {str(exc)[:220]}")
        return False


def _confirm_save_code_prompt(page, wait_ms: int = 1800) -> bool:
    """Click YES only when CCBP's explicit save-before-leaving prompt is visible."""
    prompt_text = "Do you want to save code before leaving?"
    try:
        page.wait_for_function(
            """() => {
                const text = (document.body?.innerText || '').toLowerCase();
                return text.includes('do you want to save code before leaving') ||
                       location.pathname.includes('/problems-set');
            }""",
            timeout=wait_ms,
            polling=100,
        )
    except Exception:
        pass

    prompt = page.get_by_text(prompt_text, exact=False).first
    try:
        if not prompt.count() or not prompt.is_visible():
            return False
        yes = page.get_by_role("button", name="YES", exact=True).last
        if not yes.count():
            yes = page.locator("button:has-text('YES')").last
        yes.wait_for(state="visible", timeout=5000)
        yes.click()
        page.wait_for_function(
            """() => location.pathname.includes('/problems-set') &&
                !(document.body?.innerText || '').toLowerCase()
                    .includes('do you want to save code before leaving')""",
            timeout=12000,
            polling=100,
        )
        print("[NAV] Confirmed YES to save code before leaving.")
        return True
    except Exception as exc:
        raise RuntimeError(
            f"CCBP showed its save-code prompt, but YES could not be confirmed: {exc}"
        ) from exc


def return_to_question_bank(page) -> None:
    """Leave the question, confirm CCBP's save prompt, and wait for the list."""
    if "/problems-set" in page.url:
        wait_for_question_bank(page, timeout_ms=30000)
        return

    navigated = False
    try:
        back = page.get_by_text(
            re.compile(r"^\s*QUESTION BANK\s*$", re.I)
        ).first
        if back.count() and back.is_visible():
            back.click(timeout=7000)
            navigated = True
            _confirm_save_code_prompt(page, wait_ms=2200)
    except Exception as exc:
        print(f"[NAV] Question Bank button navigation did not complete: {str(exc)[:140]}")

    if not navigated or "/problems-set" not in page.url:
        # Browser history is the fallback for portal layouts with no visible
        # Question Bank header button.
        if "/problems-set" not in page.url:
            try:
                page.go_back(wait_until="domcontentloaded", timeout=12000)
                _confirm_save_code_prompt(page, wait_ms=2200)
            except Exception:
                pass

    if "/problems-set" not in page.url:
        try:
            wait_for_question_bank(page, timeout_ms=7000)
        except Exception:
            page.goto(LMS_URL, timeout=60000, wait_until="domcontentloaded")

    wait_for_question_bank(page, timeout_ms=45000)
    print("[NAV] Question Bank is ready for the next question.")

def go_to_next_page(page, before_questions: list[dict[str, Any]] | None = None) -> bool:
    """Advance pagination only after the question-card content actually changes."""
    before = tuple(
        item.get("title", "")
        for item in (before_questions or get_unsolved_questions(page))
    )
    selectors = (
        "button[aria-label='Next']",
        "button[aria-label='Next page']",
        "[data-testid*='pagination-next']",
        "button:has-text('Next')",
        "button:has-text('›')",
        "button:has-text('»')",
        "button:has-text('>')",
        "[class*='next']",
        "[aria-label*='next' i]",
    )

    for selector in selectors:
        try:
            button = page.locator(selector).last
            if not button.count() or not button.is_visible() or not button.is_enabled():
                continue
            button.click()
            wait_for_question_rows(
                page,
                timeout_ms=20000,
                previous_signature=before,
                stable_ms=300,
            )
            print("[NAV] Next Question Bank page is ready.")
            return True
        except Exception:
            continue

    # Numbered pagination fallback.
    try:
        active = page.locator(
            "button[aria-current='page'], [aria-current='page'], "
            "button.active, button.selected, [class*='active'] button"
        ).first
        if active.count():
            current_text = active.inner_text().strip()
            if current_text.isdigit():
                candidate = page.get_by_role(
                    "button", name=str(int(current_text) + 1), exact=True
                ).first
                if candidate.count() and candidate.is_visible() and candidate.is_enabled():
                    candidate.click()
                    wait_for_question_rows(
                        page,
                        timeout_ms=20000,
                        previous_signature=before,
                        stable_ms=300,
                    )
                    print("[NAV] Next numbered Question Bank page is ready.")
                    return True
    except Exception:
        pass

    return False

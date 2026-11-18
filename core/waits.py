"""Page-state waits for the asynchronous CCBP single-page application."""
from __future__ import annotations

from typing import Iterable

QUESTION_ROW = '[data-testid="question-list-question"]'


def wait_for_document(page, timeout_ms: int = 45000) -> None:
    page.wait_for_function(
        "() => document.readyState === 'interactive' || document.readyState === 'complete'",
        timeout=timeout_ms,
    )


def wait_for_filter_controls(page, timeout_ms: int = 30000) -> None:
    page.wait_for_function(
        """() => {
            const values = ['SOLVED', 'ATTEMPTED', 'NOT_ATTEMPTED'];
            return values.every(value => {
                const label = document.querySelector(
                    'label[data-testid="' + value + '-filter-option"]'
                );
                if (!label) return false;
                const rect = label.getBoundingClientRect();
                const style = getComputedStyle(label);
                return rect.width > 0 && rect.height > 0 &&
                       style.display !== 'none' && style.visibility !== 'hidden';
            });
        }""",
        timeout=timeout_ms,
    )


def question_rows_signature(page) -> tuple[str, ...]:
    return tuple(
        page.locator(QUESTION_ROW).evaluate_all(
            """rows => rows
                .filter(row => {
                    const r = row.getBoundingClientRect();
                    const s = getComputedStyle(row);
                    return r.width > 0 && r.height > 0 &&
                           s.display !== 'none' && s.visibility !== 'hidden';
                })
                .map(row => (row.innerText || row.textContent || '').trim())"""
        )
    )


def wait_for_question_rows(
    page,
    timeout_ms: int = 45000,
    previous_signature: Iterable[str] | None = None,
    stable_ms: int = 600,
) -> tuple[str, ...]:
    """Wait for visible question cards to arrive and stop changing."""
    previous = list(previous_signature) if previous_signature is not None else None
    page.evaluate("window.__codepilotQuestionRowsState = null")
    page.wait_for_function(
        """({selector, previous, stableMs}) => {
            const visible = el => {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 &&
                       s.display !== 'none' && s.visibility !== 'hidden';
            };
            const loading = Array.from(document.querySelectorAll(
                '[aria-busy="true"], [role="progressbar"], ' +
                '[data-testid*="loading" i], [data-testid*="spinner" i]'
            )).some(visible);
            const rows = Array.from(document.querySelectorAll(selector)).filter(visible);
            const signature = rows.map(row =>
                (row.innerText || row.textContent || '').trim()
            );
            if (loading || !signature.length) {
                window.__codepilotQuestionRowsState = null;
                return false;
            }
            if (previous && JSON.stringify(signature) === JSON.stringify(previous)) {
                window.__codepilotQuestionRowsState = null;
                return false;
            }
            const current = JSON.stringify(signature);
            const state = window.__codepilotQuestionRowsState;
            if (!state || state.signature !== current) {
                window.__codepilotQuestionRowsState = {
                    signature: current,
                    since: performance.now()
                };
                return false;
            }
            return performance.now() - state.since >= stableMs;
        }""",
        arg={"selector": QUESTION_ROW, "previous": previous, "stableMs": stable_ms},
        timeout=timeout_ms,
    )
    return question_rows_signature(page)


def wait_for_question_bank(page, timeout_ms: int = 45000) -> tuple[str, ...]:
    wait_for_document(page, timeout_ms=min(timeout_ms, 15000))
    wait_for_filter_controls(page, timeout_ms=timeout_ms)
    return wait_for_question_rows(page, timeout_ms=timeout_ms, stable_ms=600)


def wait_for_question_detail(page, timeout_ms: int = 45000, stable_ms: int = 350) -> None:
    """Wait for the actual coding editor and problem statement, not sample snippets."""
    page.evaluate("window.__codepilotQuestionDetailState = null")
    page.wait_for_function(
        """({stableMs}) => {
            const visible = el => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 &&
                       s.display !== 'none' && s.visibility !== 'hidden';
            };
            if (!location.pathname.includes('/question/')) {
                window.__codepilotQuestionDetailState = null;
                return false;
            }

            const aceRoot = document.querySelector('#codingQuestionEditor') ||
                document.querySelector('.commonCodeEditor .ace_editor:not(.ace_autocomplete)');
            const monoRoot = document.querySelector(
                '.commonCodeEditor .monaco-editor, #codingQuestionEditor.monaco-editor'
            );
            let editorReady = false;
            let editorMode = '';

            try {
                if (aceRoot && visible(aceRoot) && window.ace) {
                    const editor = window.ace.edit(aceRoot);
                    editorMode = editor && editor.session &&
                        editor.session.getMode() && editor.session.getMode().$id || '';
                    editorReady = !!(editor && editor.session && editorMode);
                }
            } catch (e) {}

            try {
                if (!editorReady && monoRoot && visible(monoRoot) &&
                    window.monaco && monaco.editor) {
                    const editor = monaco.editor.getEditors().find(candidate => {
                        const node = candidate.getDomNode();
                        return node === monoRoot || monoRoot.contains(node);
                    });
                    const model = editor && editor.getModel();
                    if (model) {
                        editorReady = true;
                        editorMode = model.getLanguageId() || '';
                    }
                }
            } catch (e) {}

            if (!editorReady) {
                window.__codepilotQuestionDetailState = null;
                return false;
            }

            const descriptionSelectors = [
                '[data-testid="problem-description"]',
                '[data-testid*="problem-statement"]',
                '.problem-description',
                '.problem-statement',
                '.question-content',
                '.coding-question'
            ];
            let problemText = '';
            for (const selector of descriptionSelectors) {
                const node = document.querySelector(selector);
                if (visible(node)) {
                    problemText = (node.innerText || node.textContent || '').trim();
                    if (problemText.length >= 40) break;
                }
            }
            if (problemText.length < 40) {
                const clone = document.body.cloneNode(true);
                clone.querySelectorAll(
                    'nav, header, footer, aside, button, form, input, textarea, select, ' +
                    '.monaco-editor, .ace_editor, .commonCodeEditor, ' +
                    '[contenteditable="true"], [role="navigation"], [role="button"]'
                ).forEach(node => node.remove());
                problemText = (clone.innerText || clone.textContent || '').trim();
            }
            if (problemText.length < 40) {
                window.__codepilotQuestionDetailState = null;
                return false;
            }

            const busy = Array.from(document.querySelectorAll(
                '[aria-busy="true"], [role="progressbar"], ' +
                '[data-testid*="loading" i], [data-testid*="spinner" i]'
            )).some(visible);
            if (busy) {
                window.__codepilotQuestionDetailState = null;
                return false;
            }

            const signature = location.pathname + '|' + editorMode + '|' +
                problemText.length + '|' + problemText.slice(0, 500) + '|' +
                problemText.slice(-200);
            const state = window.__codepilotQuestionDetailState;
            if (!state || state.signature !== signature) {
                window.__codepilotQuestionDetailState = {
                    signature,
                    since: performance.now()
                };
                return false;
            }
            return performance.now() - state.since >= stableMs;
        }""",
        arg={"stableMs": stable_ms},
        timeout=timeout_ms,
    )


def wait_for_editor_value(page, expected: str, timeout_ms: int = 8000) -> bool:
    """Wait until the real coding editor model contains exactly the requested code."""
    try:
        page.wait_for_function(
            """expected => {
                const aceRoot = document.querySelector('#codingQuestionEditor') ||
                    document.querySelector('.commonCodeEditor .ace_editor:not(.ace_autocomplete)');
                try {
                    if (aceRoot && window.ace) {
                        const editor = window.ace.edit(aceRoot);
                        if (editor && editor.getValue() === expected) return true;
                    }
                } catch (e) {}
                try {
                    const root = document.querySelector(
                        '.commonCodeEditor .monaco-editor, #codingQuestionEditor.monaco-editor'
                    );
                    if (root && window.monaco && monaco.editor) {
                        const editor = monaco.editor.getEditors().find(candidate => {
                            const node = candidate.getDomNode();
                            return node === root || root.contains(node);
                        });
                        const model = editor && editor.getModel();
                        if (model && model.getValue() === expected) return true;
                    }
                } catch (e) {}
                const textarea = document.querySelector(
                    '#codingQuestionEditor textarea.ace_text-input'
                );
                return !!textarea && textarea.value === expected;
            }""",
            arg=expected,
            timeout=timeout_ms,
            polling=100,
        )
        return True
    except Exception:
        return False

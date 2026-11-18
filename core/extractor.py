"""Conservative extraction of the current coding question and editor language."""
from __future__ import annotations

import re
from pathlib import PurePath

from core.waits import wait_for_question_detail

PROBLEM_SELECTORS = (
    "[data-testid='problem-description']",
    "[data-testid*='problem-statement']",
    ".problem-description",
    ".problem-statement",
    ".question-content",
    ".coding-question",
)


def extract_problem(page, minimum_length: int = 40) -> str | None:
    """Wait for the detail page to settle, then return its statement text."""
    try:
        wait_for_question_detail(page, timeout_ms=20000, stable_ms=150)
    except Exception as exc:
        print(f"[EXTRACT] Question content/editor did not become ready: {str(exc)[:180]}")
        return None

    for selector in PROBLEM_SELECTORS:
        try:
            locator = page.locator(selector).first
            if locator.count() and locator.is_visible():
                text = locator.inner_text(timeout=3000).strip()
                if len(text) >= minimum_length:
                    return text[:16000]
        except Exception:
            continue

    # Fallback removes the editor and page controls before reading the statement.
    try:
        text = page.evaluate(
            """() => {
                const clone = document.body.cloneNode(true);
                clone.querySelectorAll(
                    'nav, header, footer, aside, button, form, input, textarea, ' +
                    'select, .monaco-editor, .ace_editor, .commonCodeEditor, ' +
                    '[contenteditable="true"], [role="navigation"], [role="button"]'
                ).forEach(node => node.remove());
                return (clone.innerText || clone.textContent || '').trim();
            }"""
        )
        text = (text or "").strip()
        if len(text) >= minimum_length:
            return text[:16000]
    except Exception:
        pass
    return None


def normalize_language(raw_language: str | None) -> str:
    """Normalize common language labels, Ace modes, and filenames."""
    if not raw_language:
        return "unknown"

    raw = str(raw_language).strip().lower()
    raw = raw.rsplit("/", 1)[-1]
    raw = raw.removeprefix("mode-").removeprefix("mode_")
    basename = raw.replace("\\", "/").rsplit("/", 1)[-1]
    suffix = PurePath(basename).suffix

    extension_map = {
        ".py": "python",
        ".js": "javascript",
        ".mjs": "javascript",
        ".cjs": "javascript",
        ".java": "java",
        ".cpp": "c++",
        ".cc": "c++",
        ".cxx": "c++",
        ".c": "c",
        ".html": "html",
        ".htm": "html",
        ".css": "css",
        ".sql": "sql",
    }
    if suffix in extension_map:
        return extension_map[suffix]

    compact = re.sub(r"[^a-z0-9+#]", "", raw)
    aliases = {
        "py": "python",
        "python": "python",
        "python3": "python",
        "javascript": "javascript",
        "js": "javascript",
        "nodejs": "javascript",
        "jsx": "javascript",
        "typescript": "javascript",
        "ts": "javascript",
        "java": "java",
        "cpp": "c++",
        "c++": "c++",
        "cc": "c++",
        "cxx": "c++",
        "c_cpp": "c++",
        "ccpp": "c++",
        "c": "c",
        "c99": "c",
        "c11": "c",
        "c17": "c",
        "c23": "c",
        "sql": "sql",
        "html": "html",
        "css": "css",
    }
    return aliases.get(compact, "unknown")


def detect_language(page) -> str:
    """Detect language from the real coding editor, not the question's sample code."""
    try:
        result = page.evaluate(
            """() => {
                const aceRoot = document.querySelector('#codingQuestionEditor') ||
                    document.querySelector('.commonCodeEditor .ace_editor:not(.ace_autocomplete)');
                try {
                    if (aceRoot && window.ace) {
                        const editor = window.ace.edit(aceRoot);
                        const mode = editor && editor.session &&
                            editor.session.getMode() && editor.session.getMode().$id;
                        if (mode) return mode;
                    }
                } catch (e) {}

                const monoRoot = document.querySelector(
                    '.commonCodeEditor .monaco-editor, #codingQuestionEditor.monaco-editor'
                ) || document.querySelector('[data-testid="code-editor"] .monaco-editor');
                try {
                    if (monoRoot && window.monaco && monaco.editor) {
                        const editor = monaco.editor.getEditors().find(candidate => {
                            const node = candidate.getDomNode();
                            return node === monoRoot || monoRoot.contains(node);
                        });
                        const model = editor && editor.getModel();
                        if (model) return model.getLanguageId();
                    }
                } catch (e) {}

                const select = document.querySelector(
                    'select[class*="language"], select[id*="language"]'
                );
                if (select && select.selectedIndex >= 0) {
                    const option = select.options[select.selectedIndex];
                    return option.value || option.text;
                }
                return null;
            }"""
        )
        language = normalize_language(result)
        if language != "unknown":
            return language
    except Exception:
        pass

    return "unknown"

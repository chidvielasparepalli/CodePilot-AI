"""Input and verification for the actual CCBP coding editor."""
from __future__ import annotations

from core.waits import wait_for_editor_value, wait_for_question_detail

EDITOR_SELECTORS = (
    "#codingQuestionEditor",
    ".commonCodeEditor .monaco-editor",
    ".commonCodeEditor .ace_editor:not(.ace_autocomplete)",
    "[data-testid='code-editor'] .monaco-editor",
    "[data-testid='code-editor'] .ace_editor:not(.ace_autocomplete)",
)


def read_editor_value(page) -> str:
    """Read only the active coding editor, never read-only code examples."""
    return page.evaluate(
        """() => {
            const aceRoot = document.querySelector('#codingQuestionEditor') ||
                document.querySelector('.commonCodeEditor .ace_editor:not(.ace_autocomplete)');
            try {
                if (aceRoot && window.ace) {
                    const editor = window.ace.edit(aceRoot);
                    if (editor && editor.session) return editor.getValue();
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
                    if (model) return model.getValue();
                }
            } catch (e) {}

            const textarea = document.querySelector(
                '#codingQuestionEditor textarea.ace_text-input, ' +
                '.commonCodeEditor textarea.ace_text-input, ' +
                '[data-testid="code-editor"] textarea'
            );
            return textarea ? textarea.value : null;
        }"""
    )


def _find_editor(page):
    """Return the actual editable code workspace, not an embedded sample editor."""
    for selector in EDITOR_SELECTORS:
        locator = page.locator(selector).first
        try:
            if locator.count() and locator.is_visible():
                return locator
        except Exception:
            continue
    return None


def inject_code(page, code: str) -> bool:
    """Wait for the coding editor, enter code, and verify its editor model."""
    if not code or not code.strip():
        raise ValueError("Refusing to enter an empty solution.")

    try:
        wait_for_question_detail(page, timeout_ms=20000, stable_ms=150)
    except Exception as exc:
        print(f"[EDITOR] Coding workspace is not ready: {str(exc)[:180]}")
        return False

    editor = _find_editor(page)
    if editor is None:
        print("[EDITOR] The actual coding editor was not found.")
        return False

    try:
        editor.click()
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        page.keyboard.insert_text(code)

        if wait_for_editor_value(page, code, timeout_ms=8000):
            print("[EDITOR] Code entered and verified in the coding editor.")
            return True

        # Fallback for editors that ignore insertText; still verify the model.
        editor.click()
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        lines = code.replace("\r\n", "\n").split("\n")
        for index, line in enumerate(lines):
            if line:
                page.keyboard.type(line, delay=0)
            if index < len(lines) - 1:
                page.keyboard.press("Enter")

        if wait_for_editor_value(page, code, timeout_ms=10000):
            print("[EDITOR] Code entered and verified using keyboard typing.")
            return True

        print("[EDITOR] Editor content did not match generated code; refusing to submit.")
        return False
    except Exception as exc:
        print(f"[EDITOR] Input failed: {str(exc)[:180]}")
        return False

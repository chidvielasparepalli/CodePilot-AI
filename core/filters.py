"""State-aware Question Bank filter controls."""
from __future__ import annotations

from core.waits import wait_for_filter_controls, wait_for_question_rows

FILTERS = {
    "SOLVED": False,
    "ATTEMPTED": True,
    "NOT_ATTEMPTED": True,
}


def set_checkbox_state(page, value: str, target_checked: bool) -> bool:
    """Change a filter only when its current state differs from the requested state."""
    checkbox = page.locator(f'input[type="checkbox"][value="{value}"]').first
    if checkbox.count() == 0:
        checkbox = page.locator(f'input[value="{value}"]').first
    if checkbox.count() == 0:
        raise RuntimeError(f"Question Bank filter checkbox '{value}' was not found.")

    if checkbox.is_checked() == target_checked:
        return False

    label = page.locator(f'label[data-testid="{value}-filter-option"]').first
    if not label.count():
        raise RuntimeError(f"Visible label for Question Bank filter '{value}' was not found.")
    label.wait_for(state="visible", timeout=10000)
    label.click()

    page.wait_for_function(
        """({value, checked}) => {
            const input = document.querySelector('input[value="' + value + '"]');
            return !!input && input.checked === checked;
        }""",
        arg={"value": value, "checked": target_checked},
        timeout=8000,
        polling=100,
    )
    if checkbox.is_checked() != target_checked:
        raise RuntimeError(f"Question Bank filter '{value}' did not reach its requested state.")
    return True


def apply_unsolved_filters(page) -> None:
    """Keep In Progress and Not Attempted selected, with Solved excluded."""
    wait_for_filter_controls(page, timeout_ms=20000)

    changed = False
    for value, target in FILTERS.items():
        changed = set_checkbox_state(page, value, target) or changed

    if changed:
        print("[FILTER] Applied: In Progress + Not Attempted; Solved excluded.")
    else:
        print("[FILTER] Requested filters are already selected.")

    # Wait for the cards to be mounted and briefly stable; don't wait for the
    # old card list to disappear if the filtered result is legitimately equal.
    wait_for_question_rows(page, timeout_ms=30000, stable_ms=600)


def reapply_filters(page) -> None:
    apply_unsolved_filters(page)

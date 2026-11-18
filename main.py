"""Open CCBP and establish the persistent sign-in session."""
from core.auth import ensure_authenticated
from core.browser import LMS_URL, start_browser
from core.navigator import open_question_bank
from core.filters import apply_unsolved_filters


def main() -> None:
    playwright, context, page = start_browser()
    try:
        page.goto(LMS_URL, timeout=120000, wait_until="domcontentloaded")
        ensure_authenticated(page)
        open_question_bank(page)
        apply_unsolved_filters(page)
        print("Question Bank is ready. Close this window when finished.")
        input("Press Enter to close...")
    finally:
        context.close()
        playwright.stop()


if __name__ == "__main__":
    main()

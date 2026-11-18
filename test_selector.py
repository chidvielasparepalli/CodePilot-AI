"""Inspect Question Bank rows, filters, and editor selectors after sign-in."""
from core.auth import ensure_authenticated
from core.browser import LMS_URL, start_browser
from core.extractor import detect_language, extract_problem
from core.filters import apply_unsolved_filters
from core.navigator import get_unsolved_questions, open_question_bank


def main() -> None:
    playwright, context, page = start_browser()
    try:
        page.goto(LMS_URL, timeout=120000, wait_until="domcontentloaded")
        ensure_authenticated(page)
        open_question_bank(page)
        apply_unsolved_filters(page)
        questions = get_unsolved_questions(page)
        print(f"Visible unsolved questions: {len(questions)}")
        for item in questions[:20]:
            print("-", item["title"])
        if questions:
            input("Press Enter to inspect the first question...")
            from core.navigator import open_question
            if open_question(page, questions[0]):
                print("Language:", detect_language(page))
                print("Problem:", (extract_problem(page) or "NOT FOUND")[:4000])
        input("Press Enter to close...")
    finally:
        context.close()
        playwright.stop()


if __name__ == "__main__":
    main()

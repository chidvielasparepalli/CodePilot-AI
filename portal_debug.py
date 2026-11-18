"""Manual portal diagnostic using the same persistent session as the app."""
from core.browser import LMS_URL, start_browser
from core.extractor import detect_language, extract_problem


def main() -> None:
    playwright, context, page = start_browser()
    try:
        page.goto(LMS_URL, timeout=120000, wait_until="domcontentloaded")
        print(f"Opened: {page.url}")
        input("Sign in and open a coding question, then press Enter...")
        print(f"Title: {page.title()}")
        print(f"Language: {detect_language(page)}")
        problem = extract_problem(page)
        print(problem or "No question text could be identified.")
    finally:
        context.close()
        playwright.stop()


if __name__ == "__main__":
    main()

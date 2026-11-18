"""Capture visible page diagnostics for a question opened manually."""
from core.browser import LMS_URL, start_browser
from core.extractor import extract_problem


def main() -> None:
    playwright, context, page = start_browser()
    try:
        page.goto(LMS_URL, timeout=120000, wait_until="domcontentloaded")
        input("Sign in and open a question, then press Enter to capture diagnostics...")
        page.screenshot(path="debug_screenshot.png", full_page=True)
        text = extract_problem(page) or "No question description could be identified."
        with open("debug_page_text.txt", "w", encoding="utf-8") as handle:
            handle.write(text)
        print("Saved debug_screenshot.png and debug_page_text.txt")
    finally:
        context.close()
        playwright.stop()


if __name__ == "__main__":
    main()

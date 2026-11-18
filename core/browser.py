"""Shared, persistent Playwright browser setup for all entry points."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env", override=True)

LMS_URL = os.getenv("LMS_URL", "https://learning.ccbp.in/problems-set").strip()
_profile_value = Path(os.getenv("PLAYWRIGHT_PROFILE_DIR", "playwright_profile")).expanduser()
PROFILE_DIR = _profile_value if _profile_value.is_absolute() else PROJECT_ROOT / _profile_value
BROWSER_CHANNEL = os.getenv("PLAYWRIGHT_CHANNEL", "chrome").strip().lower()
CHROME_PROFILE_NAME = os.getenv("CHROME_PROFILE_NAME", "Default").strip() or "Default"


def _is_default_chrome_data_dir(path: Path) -> bool:
    """Chrome 136+ refuses remote debugging against its default user-data directory."""
    local_app_data = os.getenv("LOCALAPPDATA")
    if not local_app_data:
        return False
    default_dir = Path(local_app_data) / "Google" / "Chrome" / "User Data"
    try:
        return os.path.normcase(str(path.resolve())) == os.path.normcase(str(default_dir.resolve()))
    except OSError:
        return False


def start_browser():
    """Start one persistent browser context and return (playwright, context, page).

    All entry points share the same dedicated CodePilot profile. It must be a
    non-default Chrome data directory; Chrome 136+ blocks Playwright's remote
    debugging pipe when pointed at the everyday Chrome User Data directory.
    """
    if BROWSER_CHANNEL == "chrome" and _is_default_chrome_data_dir(PROFILE_DIR):
        raise RuntimeError(
            "PLAYWRIGHT_PROFILE_DIR points to Chrome's default User Data folder. "
            "Chrome 136+ blocks remote debugging there. Use a separate persistent "
            "folder, such as %LOCALAPPDATA%\\CodePilot-AI\\Chrome User Data."
        )

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    playwright = sync_playwright().start()

    options = {
        "user_data_dir": str(PROFILE_DIR.resolve()),
        "headless": False,
        "no_viewport": True,
        "args": ["--start-maximized", f"--profile-directory={CHROME_PROFILE_NAME}"],
    }
    if BROWSER_CHANNEL and BROWSER_CHANNEL != "chromium":
        options["channel"] = BROWSER_CHANNEL

    try:
        context = playwright.chromium.launch_persistent_context(**options)
        page = next((candidate for candidate in context.pages if not candidate.is_closed()), None)
        if page is None:
            page = context.new_page()
        return playwright, context, page
    except PlaywrightError as exc:
        playwright.stop()
        detail = str(exc).strip()
        raise RuntimeError(
            f"Could not launch Chrome with CodePilot profile at {PROFILE_DIR}. "
            "Close any process using that dedicated profile and try again. "
            f"Browser error: {detail}"
        ) from exc
    except Exception:
        playwright.stop()
        raise

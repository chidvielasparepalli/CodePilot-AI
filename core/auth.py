"""Wait for CCBP's redirect and authenticated application state."""
from __future__ import annotations


def is_login_page(page) -> bool:
    url = (getattr(page, "url", "") or "").lower()
    return "accounts.ccbp.in/login" in url or (
        "accounts.ccbp.in" in url and ("/login" in url or "mode=otp" in url)
    )


def ensure_authenticated(page, timeout_seconds: int = 600) -> None:
    """Wait until CCBP has either redirected to sign-in or mounted its app shell."""
    try:
        page.wait_for_function(
            """() => {
                const host = location.hostname.toLowerCase();
                const login = host === 'accounts.ccbp.in' &&
                    (location.pathname.includes('/login') || location.search.includes('mode=otp'));
                if (login) return true;
                if (host !== 'learning.ccbp.in') return false;
                const row = document.querySelector('[data-testid="question-list-question"]');
                const filter = document.querySelector('label[data-testid="SOLVED-filter-option"]');
                const navText = (document.body?.innerText || '').includes('Question Bank');
                return document.readyState === 'complete' && (!!row || !!filter || navText);
            }""",
            timeout=45000,
        )
    except Exception as exc:
        raise TimeoutError(
            "CCBP did not finish its initial redirect or mount the learning app. "
            "The bot stopped instead of acting on a partially loaded page."
        ) from exc

    if not is_login_page(page):
        print("[AUTH] CCBP application shell detected.")
        return

    print("\n[AUTH] CCBP requires sign-in in the opened browser.")
    print("[AUTH] Complete the portal OTP/login step; the CodePilot profile will retain it.")

    try:
        page.wait_for_function(
            """() => {
                const host = location.hostname.toLowerCase();
                return host === 'learning.ccbp.in' &&
                       !location.pathname.includes('/login') &&
                       !location.search.includes('mode=otp') &&
                       document.readyState === 'complete';
            }""",
            timeout=timeout_seconds * 1000,
        )
    except Exception as exc:
        raise TimeoutError(
            "CCBP sign-in was not completed before timeout. "
            "The bot did not continue against the login page."
        ) from exc

    print("[AUTH] Sign-in redirect completed; waiting for the Question Bank UI.")

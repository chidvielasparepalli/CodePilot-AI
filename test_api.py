"""Optional live Gemini connectivity check; requires GEMINI_API_KEY in .env."""
from __future__ import annotations

from dotenv import load_dotenv

from core.solver import DEFAULT_MODEL, call_gemini

load_dotenv()


def main() -> int:
    try:
        response = call_gemini(
            "Reply with exactly the two words: API READY",
            model=DEFAULT_MODEL,
            timeout=30,
        )
    except Exception as exc:
        print(f"Gemini check failed: {exc}")
        return 1

    print(f"Gemini check succeeded ({DEFAULT_MODEL}): {response[:120]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

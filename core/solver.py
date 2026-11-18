"""Gemini code generation with judge-feedback repair iterations."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env", override=True)

DEFAULT_MODEL = "gemini-3.8-flash"
MAX_OUTPUT_TOKENS = max(1024, int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "3072")))
GEMINI_TIMEOUT_SECONDS = max(20, int(os.getenv("GEMINI_TIMEOUT_SECONDS", "75")))


def configured_models() -> list[str]:
    primary = os.getenv("GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    fallbacks = os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.5-flash-lite")
    return list(dict.fromkeys(
        [primary] + [item.strip() for item in fallbacks.split(",") if item.strip()]
    ))


def _response_text(payload: dict) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        reason = (payload.get("promptFeedback") or {}).get("blockReason")
        raise RuntimeError(f"Gemini returned no usable candidate (block reason: {reason or 'none'}).")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    output = "\n".join(
        part.get("text", "") for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    ).strip()
    if not output:
        raise RuntimeError("Gemini returned an empty response.")
    return output


def call_gemini(
    prompt: str,
    model: str | None = None,
    api_key: str | None = None,
    timeout: int | None = None,
) -> str:
    """Call Gemini without embedding credentials in source or logs."""
    key = (api_key or os.getenv("GEMINI_API_KEY", "")).strip()
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is empty. Add a newly rotated Google AI Studio key to the local .env file."
        )

    selected_model = model or os.getenv("GEMINI_MODEL", DEFAULT_MODEL).strip()
    request_timeout = timeout or GEMINI_TIMEOUT_SECONDS
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{selected_model}:generateContent"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "topP": 0.8,
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
        },
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=request_timeout) as response:
            return _response_text(json.loads(response.read().decode("utf-8")))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise RuntimeError("Gemini rejected the API key or its permissions. Check .env.") from None
        if exc.code == 404:
            raise RuntimeError(f"Gemini model '{selected_model}' is unavailable.") from None
        if exc.code == 429:
            raise RuntimeError("Gemini quota/rate limit reached. Check your AI Studio quota.") from None
        raise RuntimeError(f"Gemini API request failed with HTTP {exc.code}.") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Gemini API: {exc.reason}.") from None
    except json.JSONDecodeError:
        raise RuntimeError("Gemini returned invalid JSON.") from None


def strip_code_fence(response: str, language: str) -> str:
    """Remove a single Markdown fence if Gemini wraps its source."""
    text = response.strip()
    fence = chr(96) * 3
    pattern = re.escape(fence) + r"(?:[a-zA-Z0-9_+#.-]+)?\s*([\s\S]*?)\s*" + re.escape(fence)
    match = re.search(pattern, text)
    if match:
        text = match.group(1).strip()
    else:
        text = re.sub(r"^" + re.escape(fence) + r"[^\n]*\n?", "", text)
        text = re.sub(r"\n?" + re.escape(fence) + r"\s*$", "", text)
    if not text:
        raise RuntimeError("Gemini response did not contain source code.")
    return text.strip() + "\n"


LANGUAGE_RULES = {
    "python": "Write Python 3. Use input() and print(). No external packages.",
    "javascript": "Write Node.js JavaScript. Read stdin with fs.readFileSync(0, 'utf8') and print with console.log.",
    "java": "Write a complete Java program with public class Main and required imports.",
    "c++": "Write a complete C++17 program with #include <bits/stdc++.h> and int main().",
    "c": "Write a complete C11 program with required headers and int main().",
    "sql": "Return the SQL statement only, without Markdown or commentary.",
    "html": "Return a complete HTML document, with required CSS/JavaScript inline.",
    "css": "Return only the CSS required by the task.",
}


def generate_code(
    problem_text: str,
    language: str,
    previous_code: str | None = None,
    feedback: str | None = None,
    starter_code: str | None = None,
    test_cases: list[dict] | None = None,
) -> str:
    """Generate a complete solution; include judge/compiler feedback on repair attempts."""
    if not problem_text or len(problem_text.strip()) < 25:
        raise ValueError("Question statement is too short; refusing to guess.")
    language = (language or "unknown").strip().lower()
    if language not in LANGUAGE_RULES:
        raise ValueError(f"Unsupported or undetected language: {language}")

    repair_section = ""
    if previous_code and feedback:
        repair_section = f"""
PREVIOUS ATTEMPT (must be corrected):
{previous_code[:12000]}

JUDGE / COMPILER FEEDBACK:
{feedback[:7000]}

Use the feedback to identify the real defect. Re-check the original problem statement,
input format, output format, constraints, indexing, and edge cases. Return a corrected
complete program, not a patch. Do not repeat the same failed approach blindly.
"""

    template_section = ""
    if starter_code and starter_code.strip():
        template_rule = (
            "Complete the supplied platform template. Preserve its class names, "
            "function signatures, imports, and required structure. Fill the intended "
            "implementation only; do not add a second entry point or main() unless "
            "the template itself requires one."
        )
        template_section = (
            "\nPLATFORM STARTER CODE (preserve its required structure):\n"
            + starter_code[:12000]
        )
    else:
        template_rule = "Return a complete program appropriate for the judge."

    examples_section = ""
    if test_cases:
        rendered = []
        for index, case in enumerate(test_cases[:8], 1):
            if not isinstance(case, dict):
                continue
            input_value = case.get("input", "")
            output_value = case.get("output", "")
            normalized = []
            for value in (input_value, output_value):
                if isinstance(value, str):
                    try:
                        decoded = json.loads(value)
                        if isinstance(decoded, str):
                            value = decoded
                    except json.JSONDecodeError:
                        pass
                normalized.append(str(value)[:1800])
            if normalized[0] or normalized[1]:
                rendered.append(
                    f"Case {index}:\nInput:\n{normalized[0]}\nExpected output:\n{normalized[1]}"
                )
        if rendered:
            examples_section = "\nREFERENCE TEST CASES:\n" + "\n\n".join(rendered)

    language_instruction = LANGUAGE_RULES[language]
    if starter_code and starter_code.strip():
        language_instruction = (
            f"Use {language} and preserve the supplied platform starter structure and signatures."
        )

    prompt = f"""Solve this programming problem.

Language: {language}
{language_instruction}
{template_rule}

Rules:
- Match the required input and output format exactly.
- Handle constraints and edge cases efficiently.
- Return complete source code ready for the platform judge.
- Output source code only. No explanation, headings, or Markdown fences.
{template_section}
{examples_section}

{repair_section}
Problem:
{problem_text[:16000]}
"""
    last_error: Exception | None = None
    for model in configured_models():
        for attempt in range(2):
            try:
                print(f"[AI] Generating code with {model}...")
                started = time.perf_counter()
                response = call_gemini(prompt, model=model)
                code = strip_code_fence(response, language)
                elapsed = time.perf_counter() - started
                print(f"[AI] Code ready: {len(code)} characters in {elapsed:.1f}s")
                return code
            except RuntimeError as exc:
                last_error = exc
                message = str(exc).lower()
                if "quota" in message or "api key" in message or "permissions" in message:
                    raise
                if "rate limit" in message and attempt == 0:
                    time.sleep(1.5)
                    continue
                break
    raise RuntimeError(f"Code generation failed: {last_error or 'no model response'}")


def solve_problem(problem_text: str, language: str = "python") -> str:
    """Backward-compatible name used by the original bot."""
    return generate_code(problem_text, language)

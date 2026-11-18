# CodePilot-AI

A local hybrid Playwright + CCBP API + Gemini automation tool for the CCBP Question Bank. Playwright handles sign-in and question navigation; the API retrieves question data, saves code drafts, submits solutions, and returns judge feedback.

## Workflow

1. Launch Chrome using the dedicated CodePilot profile.
2. Reuse the CCBP login session. If the session has expired, the bot waits while you complete the portal OTP/sign-in step once.
3. Open Question Bank and set In Progress + Not Attempted, with Solved unchecked.
4. Open the first visible unanswered question.
5. Read the question statement, starter template, supported language, and reference cases from the CCBP coding API.
6. Ask Gemini for a complete solution using the platform template and reference cases.
7. Save the generated code draft and submit it through the authenticated CCBP coding API; API-only mode does not type into the browser editor or click its Submit button.
8. If the judge reports a failure, send its compiler/test feedback and previous code to Gemini, replace the code, and retry.
9. Only mark a question complete when the portal displays a clear accepted/pass verdict.
10. Return to the Question Bank and continue. Progress is saved after every accepted or failed question.

The bot stops a question after the configured retry cap rather than submitting forever when portal feedback is missing or Gemini repeatedly fails. Failed questions remain eligible for a later run. In API-only mode, the draft is saved through the CCBP save-code endpoint; the browser's save-code dialog is not used.

## Requirements

- Windows 10/11
- Python 3.10+
- Google Chrome
- A Gemini Developer API key

## Setup

From PowerShell, in A:\clone\CodePilot-AI:

    py -3.14 -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    Copy-Item .env.example .env
    notepad .env

Add a Gemini API key to GEMINI_API_KEY. Never commit the real .env file or place credentials inside Python source.

The default model is gemini-3.8-flash, with gemini-3.5-flash-lite as a configurable fallback.

## Browser profile and login

Chrome 136+ intentionally rejects Playwright remote debugging when it is launched against the normal Chrome User Data folder. CodePilot therefore uses a separate persistent Chrome data directory. Do not set PLAYWRIGHT_PROFILE_DIR to %LOCALAPPDATA%\Google\Chrome\User Data.

On this PC, CodePilot uses:

    C:\Users\chidv\AppData\Local\CodePilot-AI\Chrome User Data

The folder was seeded from the normal Profile 1 profile so the browser starts with a copy of its settings, extensions, cookies, and site storage. Saved-password databases and browsing history were excluded. Your original Chrome profile is untouched.

This is a one-time snapshot, not a live mirror. CodePilot and normal Chrome now keep separate sessions. The copied CCBP session redirected to the portal login during the launch test, so complete the CCBP OTP/sign-in once in the CodePilot browser. That new session will then persist in the dedicated folder and be shared by login.py, main.py, and bot.py.

Run the login setup first:

    cd A:\clone\CodePilot-AI
    .\.venv\Scripts\Activate.ps1
    python login.py

Complete the CCBP sign-in in the opened Chrome window. Close the window when the Question Bank is ready. Then run the bot:

    python bot.py

Normal Chrome can stay separate; CodePilot no longer tries to lock or debug your everyday Chrome profile.


## CCBP API mode

In API-only mode, CodePilot keeps Playwright for sign-in, Question Bank navigation, and opening a question to identify its ID. It captures a bearer token from the authenticated browser's own CCBP network traffic, then uses coding endpoints to fetch the problem/template/reference cases, save the generated draft, and submit for judging. It does not type into the page editor or click the page Submit button. It does not read tokens from source files or write them to disk.

    CCBP_API_MODE=api

Set CCBP_API_MODE=hybrid to also type code into the visible editor, or CCBP_API_MODE=browser to disable direct API submission and use the browser's Submit control. The API adapter is serial and coding-question-only. It does not automate MCQ exams or mark learning resources complete. It does not spoof elapsed time, rotate tokens, or retry a submission when the network outcome is ambiguous.

Important: These CCBP endpoints are undocumented internal endpoints described by the public niatbuttcracker reference at https://github.com/pragnyanramtha/niatbuttcracker, not a documented public CCBP API. Their payloads and availability may change, and using them should be consistent with CCBP's rules and your account permissions. API tests are mocked; this repository has not verified a live API submission. In API-only mode, token capture or API setup failure stops that question instead of silently falling back to browser submission. If the API submit request may have reached the server but no result is received, it stops for manual inspection rather than sending a duplicate.

## Configuration

| Variable | Default | Purpose |
|---|---:|---|
| CCBP_API_MODE | api | api uses API-only question retrieval/save/submit; hybrid also types into the UI; browser uses UI submission |
| CCBP_API_TIMEOUT_SECONDS | 25 | Timeout for one CCBP API request |
| CCBP_APP_VERSION | 1128 | App-version header used by the current endpoint contract |
| MAX_ATTEMPTS_PER_QUESTION | 6 | Maximum generate/submit/fix attempts per question |
| MAX_QUESTION_BANK_PAGES | 500 | Pagination safety cap |
| RESULT_TIMEOUT_SECONDS | 50 | Wait for judge after each submission |
| QUESTION_DELAY_SECONDS | 0.8 | Delay between questions |
| MAX_CONSECUTIVE_ERRORS | 8 | Stop on repeated browser/runtime errors |

## Testing

    python -m unittest discover -s tests -v
    python -m compileall -q .
    python -m pip check

The tests are offline. A final live Question Bank test still requires a valid CCBP sign-in and an active Gemini API key.

## Security and local files

The following are ignored by Git: .env, auth.json, browser profiles, progress.json, generated drafts, caches, debug images, and virtual environments. Existing local profiles and progress files are preserved.

Previously committed Gemini keys and browser cookies should be treated as compromised. Rotate the Gemini key and invalidate exposed CCBP sessions. Untracking files does not erase old copies from remote Git history; history cleanup and force-push should be done separately.

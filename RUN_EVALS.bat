@echo off
REM Runs the AI evals against Gemini (needs GEMINI_API_KEY in .env; about 30 free-tier calls).
cd /d "%~dp0"
if not exist .venv (
  python -m venv .venv
  .venv\Scripts\python -m pip install --quiet -r requirements.txt
)
.venv\Scripts\python evals\run_evals.py
pause

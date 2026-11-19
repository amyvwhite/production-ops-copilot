@echo off
REM One-click local run on Windows: creates a virtual environment the first time,
REM installs the app, starts it and opens http://localhost:8000.
REM Put your Gemini key in a file named .env (copy .env.example) to turn AI on.
cd /d "%~dp0"
if not exist .venv (
  echo Setting up for the first time...
  python -m venv .venv || (echo Python 3.11+ is required: https://www.python.org/downloads/ & pause & exit /b 1)
  .venv\Scripts\python -m pip install --quiet -r requirements.txt
)
start "" http://localhost:8000
.venv\Scripts\python -m uvicorn app.main:app --port 8000

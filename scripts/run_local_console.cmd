@echo off
cd /d "%~dp0.."

if exist ".venv\Scripts\activate.bat" (
  call ".venv\Scripts\activate.bat"
) else (
  echo [local-asr-service] Virtual environment was not found at .venv\Scripts\activate.bat
  echo [local-asr-service] Create it first: python -m venv .venv
  echo.
  pause
  exit /b 1
)

set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
python -m local_asr_service.main

echo.
echo [local-asr-service] Service stopped.
pause

@echo off
REM Navigate to the directory where this script is located
cd /d "%~dp0"

REM Go into the backend directory
cd backend

echo Starting Mutagent Issue Recommendation Test...
echo.

REM Run the Mutagent harness using the virtual environment python
.\venv\Scripts\python -u -m mutagent.run issue_rec

echo.
pause

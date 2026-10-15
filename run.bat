@echo off
REM Start Binance Trading Bot locally

REM Activate virtual environment
call venv\Scripts\activate.bat

REM Create data directory if it doesn't exist
if not exist "data" mkdir data

REM Start the FastAPI server
echo Starting Binance Trading Bot server...
echo Server will be available at http://localhost:8000
python -m uvicorn main:app --host 127.0.0.1 --port 8000

pause

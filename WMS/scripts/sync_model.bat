@echo off
REM Automatic model synchronization script for Windows
REM Double-click this file to download the latest Production model

echo.
echo ============================================================
echo  Water Meters Segmentation - Model Synchronization
echo ============================================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found!
    echo Please install Python 3.7+ and add it to PATH
    pause
    exit /b 1
)

REM Check if virtual environment exists
if exist ".venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call .venv\Scripts\activate.bat
) else (
    echo WARNING: Virtual environment not found at .venv
    echo Using system Python...
)

REM Run the synchronization script
python WMS\scripts\sync_model.py %*

REM Keep window open
echo.
pause

@echo off
setlocal

:: Card Counter Portable Application - Windows Launch Script
:: This script sets up the environment and launches the Card Counter application

:: Check Python installation
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in PATH
    echo Please install Python 3.8+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Check and install requirements
if not exist ".venv" (
    echo Setting up Python virtual environment...
    python -m venv .venv
    call .venv\Scripts\activate
    pip install --upgrade pip
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate
)

:: Run the application
echo Starting Card Counter...
python main.py

endlocal
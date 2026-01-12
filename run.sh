#!/bin/bash

# Card Counter Portable Application - Linux/macOS Launch Script
# This script sets up the environment and launches the Card Counter application

# Check Python installation
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed"
    echo "Please install Python 3.8+"
    exit 1
fi

# Check and install requirements
if [ ! -d ".venv" ]; then
    echo "Setting up Python virtual environment..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
else
    source .venv/bin/activate
fi

# Run the application
echo "Starting Card Counter..."
python main.py
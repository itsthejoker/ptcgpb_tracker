#!/usr/bin/env python3
"""
Card Counter - Main Entry Point

This is the main entry point for the Card Counter PyQt6 application.
It initializes the application, checks dependencies, and starts the main window.
"""

import sys
import os
import logging
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

# Add the app directory to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main_window import MainWindow
from app.utils import check_dependencies, initialize_data_directory

def setup_logging():
    """Set up logging configuration"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('data/logs/app.log'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

def main():
    """Main application entry point"""
    logger = setup_logging()
    logger.info("Starting PTCGP Card Tracker application")
    
    # Initialize data directory structure
    try:
        initialize_data_directory()
        logger.info("Data directory initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize data directory: {e}")
        sys.exit(1)
    
    # Check dependencies
    if not check_dependencies():
        logger.error("Dependency check failed")
        sys.exit(1)
    
    # Create Qt application
    app = QApplication(sys.argv)
    app.setApplicationName("PTCGP Card Tracker")
    app.setOrganizationName("CardCounter")
    app.setOrganizationDomain("cardcounter.local")
    
    # Set application style
    # app.setStyle('Fusion')
    
    # Create and show main window
    try:
        main_window = MainWindow()
        main_window.show()
        logger.info("Main window created and shown")
        
        # Start application event loop
        sys.exit(app.exec())
        
    except Exception as e:
        logger.error(f"Failed to start application: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

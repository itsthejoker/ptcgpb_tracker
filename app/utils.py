"""
Card Counter Utilities

Utility functions for the Card Counter application including:
- Dependency checking
- Path handling
- Data directory management
- Error handling
"""

import sys
import os
import logging
import tomllib
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtCore import QSettings

logger = logging.getLogger(__name__)


def get_portable_path(*parts):
    """
    Get absolute path relative to application root

    Args:
        *parts: Path components to join

    Returns:
        str: Absolute path
    """
    if hasattr(sys, "_MEIPASS"):  # PyInstaller
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
        # Go up one level to get to the root directory
        base_path = os.path.dirname(base_path)

    # If the path starts with 'data', ensure it's in '_internal/data'
    # unless base_path already points to '_internal'
    if parts and parts[0] == "data":
        if os.path.basename(base_path) != "_internal":
            return os.path.join(base_path, "_internal", *parts)

    return os.path.join(base_path, *parts)


def get_app_version():
    """
    Get the application version from pyproject.toml

    Returns:
        str: Version string
    """
    try:
        pyproject_path = get_portable_path("pyproject.toml")
        if os.path.exists(pyproject_path):
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)
                return data.get("project", {}).get("version", "unknown")
        return "unknown"
    except Exception as e:
        logger.error(f"Failed to load version from pyproject.toml: {e}")
        return "unknown"


def initialize_data_directory():
    """
    Ensure data directory structure exists

    Creates the following structure:
    - data/
      - uploads/
      - logs/
      - cardcounter.db (if doesn't exist)
    """
    data_dir = get_portable_path("data")
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(os.path.join(data_dir, "uploads"), exist_ok=True)
    os.makedirs(os.path.join(data_dir, "logs"), exist_ok=True)

    # Initialize database if it doesn't exist
    db_path = os.path.join(data_dir, "cardcounter.db")
    if not os.path.exists(db_path):
        from app.database import Database

        try:
            db = Database(db_path)
            db._initialize_database()
            logger.info(f"Initialized new database at {db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise


def check_dependencies():
    """
    Check if all required dependencies are available

    Returns:
        bool: True if all dependencies are available, False otherwise
    """
    required_modules = ["PyQt6", "cv2", "numpy", "PIL"]

    missing = []
    for module in required_modules:
        try:
            __import__(module)
        except ImportError:
            missing.append(module)

    if missing:
        error_msg = f"Missing required dependencies: {', '.join(missing)}"
        error_msg += "\nPlease run: pip install -r requirements.txt"
        logger.error(error_msg)
        return False

    logger.info("All dependencies are available")
    return True


class PortableSettings:
    """
    Portable settings management using QSettings

    Stores settings in a portable INI file within the data directory.
    """

    def __init__(self):
        config_path = get_portable_path("data", "config.ini")
        self.settings = QSettings(config_path, QSettings.Format.IniFormat)

    def load_settings(self):
        """Load settings from portable config file"""
        # Implement as needed
        pass

    def save_settings(self):
        """Save settings to portable config file"""
        # Implement as needed
        pass

    def get_setting(self, key, default=None):
        """Get a specific setting"""
        return self.settings.value(key, default)

    def set_setting(self, key, value):
        """Set a specific setting"""
        self.settings.setValue(key, value)


def show_error_message(title, message):
    """
    Show an error message dialog

    Args:
        title: Dialog title
        message: Error message
    """
    msg_box = QMessageBox()
    msg_box.setIcon(QMessageBox.Icon.Critical)
    msg_box.setWindowTitle(title)
    msg_box.setText(message)
    msg_box.exec()


def show_info_message(title, message):
    """
    Show an information message dialog

    Args:
        title: Dialog title
        message: Information message
    """
    msg_box = QMessageBox()
    msg_box.setIcon(QMessageBox.Icon.Information)
    msg_box.setWindowTitle(title)
    msg_box.setText(message)
    msg_box.exec()

"""
Card Counter Application - Main Application Package

This package contains the core application components for the PyQt6-based
card counter application.
"""

from .main_window import MainWindow
from .database import Database
from .image_processing import ImageProcessor
from .utils import get_app_version

__version__ = get_app_version()
__author__ = "Card Counter Team"

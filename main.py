#!/usr/bin/env python3
"""
Card Counter - Main Entry Point

This is the main entry point for the Card Counter PyQt6 application.
It initializes the application, checks dependencies, and starts the main window.
"""

import ctypes
import sys
import os
import logging
from PyQt6 import QtCore
from PyQt6.QtWidgets import QApplication
from PyQt6 import QtGui

# Turn off bytecode generation
sys.dont_write_bytecode = True
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")

import django

django.setup()

from settings import BASE_DIR
from app.db.models import *  # noqa

# Add the app directory to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# meipass is the _internal directory when the application is packaged with PyInstaller
basedir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))

from app.main_window import MainWindow
from app.utils import (
    check_dependencies,
    initialize_data_directory,
    get_app_version,
    PortableSettings,
)
from settings import BASE_DIR


def setup_translations(app, settings, basedir):
    """Load translation based on settings or system locale"""
    translator = QtCore.QTranslator()

    # Get language from settings, fallback to system locale
    lang = settings.get_setting("General/language")
    if not lang:
        lang = QtCore.QLocale.system().name()[:2]

    # Path to translation files - using app/translations as confirmed by ls
    translations_path = os.path.join(basedir, "app", "translations")

    logger = logging.getLogger(__name__)
    if translator.load(f"{lang}.qm", translations_path):
        app.installTranslator(translator)
        logger.info(f"Loaded translation for {lang}")
    else:
        # Fallback to English if the system locale is not supported
        if lang != "en":
            if translator.load("en.qm", translations_path):
                app.installTranslator(translator)
                logger.info("Loaded English fallback translation")

    return translator  # Keep reference to avoid garbage collection


def setup_logging():
    """Set up logging configuration"""

    log_file = BASE_DIR / "data" / "logs" / "app.log"

    # Ensure log directory exists
    log_dir = os.path.dirname(log_file)
    try:
        os.makedirs(log_dir, exist_ok=True)
        # Create the log file if it doesn't exist
        if not os.path.exists(log_file):
            with open(log_file, "a", encoding="utf-8"):
                pass
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        handlers = [file_handler]
        if sys.stderr is not None:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            handlers.append(console_handler)
    except Exception as e:
        handlers = []
        if sys.stderr is not None:
            print(
                f"Warning: Could not initialize file logging at {log_file}: {e}",
                file=sys.stderr,
            )
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            handlers.append(console_handler)

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - [%(threadName)s] - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
    )
    return logging.getLogger(__name__)


def main():
    """Main application entry point"""
    # Ensure standard streams use UTF-8 encoding if possible
    import io

    if sys.stdout is not None:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, io.UnsupportedOperation):
            pass
    if sys.stderr is not None:
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, io.UnsupportedOperation):
            pass

    logger = setup_logging()

    # Redirect stdout and stderr to logger when running in windowed mode
    class StreamToLogger:
        def __init__(self, log_func):
            self.log_func = log_func

        def write(self, buf):
            for line in buf.rstrip().splitlines():
                self.log_func(line.rstrip())

        def flush(self):
            pass

    if sys.stdout is None:
        sys.stdout = StreamToLogger(logger.info)
    if sys.stderr is None:
        sys.stderr = StreamToLogger(logger.error)

    logger.info("Starting PTCGP Card Tracker application")

    # Initialize data directory structure
    try:
        initialize_data_directory()
        logger.info("Data directory initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize data directory: {e}")
        sys.exit(1)

    # Run database migrations
    try:
        from django.core.management import call_command

        logger.info("Running database migrations...")
        import io

        out = io.StringIO()
        call_command("migrate", interactive=False, stdout=out, stderr=out)
        for line in out.getvalue().splitlines():
            logger.info(f"Migration: {line}")
        logger.info("Database migrations completed successfully")

        # One-time fix for card names and rarities
        from app.db.models import Card

        cards_to_fix = Card.objects.filter(name__contains="(")
        if cards_to_fix.exists():
            logger.info(f"Fixing {cards_to_fix.count()} card records...")
            for card in cards_to_fix:
                card.save()
            logger.info("Card records fixed.")
    except Exception as e:
        logger.error(f"Database migration failed: {e}")
        sys.exit(1)

    # Check dependencies
    if not check_dependencies():
        logger.error("Dependency check failed")
        sys.exit(1)

    # Create Qt application
    app = QApplication(sys.argv)

    # Setup translations
    settings = PortableSettings()
    translator = setup_translations(app, settings, basedir)

    app.setApplicationName("PTCGP Card Tracker")
    app.setOrganizationName("CardCounter")
    app.setOrganizationDomain("cardcounter.local")

    icon = QtGui.QIcon()

    sizes = [16, 24, 32, 48, 64, 96, 128, 256, 512]

    for size in sizes:
        icon.addFile(
            os.path.join(basedir, "ptcgpb-companion-icon.ico"), QtCore.QSize(size, size)
        )

    app.setWindowIcon(icon)

    myappid = f"itsthejoker.ptcgpb-companion.{get_app_version()}"
    if os.name == "nt":
        # windows-based witchcraft
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

    # Set application style
    app.setStyle("Fusion")

    # Create and show main window
    try:
        main_window = MainWindow()
        main_window.setWindowIcon(QtGui.QIcon(icon))
        main_window.show()
        logger.info("Main window created and shown")

        # Start application event loop
        sys.exit(app.exec())

    except Exception as e:
        logger.error(f"Failed to start application: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

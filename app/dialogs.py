"""
Card Counter Dialogs

Dialog classes for the Card Counter PyQt6 application.
This module provides various dialog windows for user interactions.
"""

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFileDialog,
    QLineEdit,
    QComboBox,
    QCheckBox,
    QProgressBar,
    QTextEdit,
    QFormLayout,
    QDialogButtonBox,
    QMessageBox,
    QApplication,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QWidget,
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QSize
from PyQt6.QtGui import QIcon, QValidator, QPixmap
import os
import csv
from datetime import datetime
from app.utils import get_app_version, SECTION_ORDER, record_traded_card
from typing import Optional, Dict, Any, Callable


class IntValidator(QValidator):
    """Custom integer validator for QLineEdit"""

    def __init__(self, min_val: int, max_val: int, parent=None):
        super().__init__(parent)
        self.min_val = min_val
        self.max_val = max_val

    def validate(self, input_text: str, pos: int) -> tuple:
        """Validate the input text"""
        try:
            val = int(input_text)
            if self.min_val <= val <= self.max_val:
                return (QValidator.State.Acceptable, input_text, pos)
            else:
                return (QValidator.State.Intermediate, input_text, pos)
        except ValueError:
            if input_text == "":
                return (QValidator.State.Intermediate, input_text, pos)
            else:
                return (QValidator.State.Invalid, input_text, pos)


class CSVImportDialog(QDialog):
    """Dialog for importing CSV files with pack metadata"""

    csv_imported = pyqtSignal(
        str
    )  # Signal emitted when CSV is successfully imported (file_path)

    def __init__(self, parent=None, initial_path="", settings=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Import CSV"))
        self.setMinimumSize(500, 400)

        self._initial_path = initial_path
        self._settings = settings
        self._setup_ui()
        self._csv_data = None
        self._file_path = ""

        # Auto-load if initial_path is a file
        if self._initial_path and os.path.isfile(self._initial_path):
            self._file_path = self._initial_path
            self.file_path_label.setText(self._initial_path)
            self._load_csv_preview(self._initial_path)

    def _setup_ui(self):
        """Set up the user interface"""
        main_layout = QVBoxLayout()

        # File selection section
        file_layout = QHBoxLayout()
        self.file_path_label = QLabel(self.tr("No file selected"))
        self.file_path_label.setWordWrap(True)

        browse_btn = QPushButton(self.tr("Browse..."))
        browse_btn.clicked.connect(self._browse_file)

        file_layout.addWidget(QLabel(self.tr("CSV File:")))
        file_layout.addWidget(self.file_path_label, 1)
        file_layout.addWidget(browse_btn)

        main_layout.addLayout(file_layout)

        # CSV preview section
        preview_label = QLabel(self.tr("CSV Preview (first 10 rows):"))
        main_layout.addWidget(preview_label)

        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMinimumHeight(200)
        main_layout.addWidget(self.preview_text)

        # Options section
        # Options can be added here in the future

        # Progress section
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel("")
        main_layout.addWidget(self.status_label)

        # Buttons
        button_box = QDialogButtonBox()
        self.import_btn = button_box.addButton(
            self.tr("Import"), QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.import_btn.setEnabled(False)
        cancel_btn = button_box.addButton(
            self.tr("Cancel"), QDialogButtonBox.ButtonRole.RejectRole
        )

        self.import_btn.clicked.connect(self._import_csv)
        cancel_btn.clicked.connect(self.reject)

        main_layout.addWidget(button_box)

        self.setLayout(main_layout)

    def _browse_file(self):
        """Open file dialog to select CSV file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Select CSV File"),
            self._initial_path,
            self.tr("CSV Files (*.csv);;All Files (*)"),
        )

        if file_path:
            self._file_path = file_path
            self.file_path_label.setText(file_path)
            self._load_csv_preview(file_path)

            # Save the path to settings
            if self._settings:
                self._settings.set_setting("General/csv_import_path", file_path)

    def _load_csv_preview(self, file_path: str):
        """Load and display preview of CSV file"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = []
                for i, row in enumerate(reader):
                    if i >= 10:  # Limit to 10 rows
                        break
                    rows.append(", ".join(row))

                self.preview_text.setPlainText("\n".join(rows))
                self.import_btn.setEnabled(True)
                self.status_label.setText(self.tr("CSV file loaded successfully"))

        except Exception as e:
            self.preview_text.setPlainText(
                self.tr("Error loading CSV: %1").replace("%1", str(e))
            )
            self.import_btn.setEnabled(False)
            self.status_label.setText(self.tr("Error: %1").replace("%1", str(e)))

    def _import_csv(self):
        """Import the CSV file"""
        try:
            # Emit signal and close
            self.csv_imported.emit(self._file_path)
            self.accept()

        except Exception as e:
            QMessageBox.critical(
                self,
                self.tr("Import Error"),
                self.tr("Failed to import CSV: %1").replace("%1", str(e)),
            )
            self.status_label.setText(self.tr("Error: %1").replace("%1", str(e)))
            self.import_btn.setEnabled(True)

    def _process_csv_data(self):
        """Process CSV data and store in database"""
        # This is now handled by the CSVImportWorker in the main window
        pass


class ScreenshotProcessingDialog(QDialog):
    """Dialog for processing screenshot images"""

    processing_started = pyqtSignal(
        str, bool
    )  # Signal emitted when processing starts (directory_path, overwrite)

    def __init__(self, parent=None, initial_dir="", settings=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Process Screenshots"))
        self.setMinimumSize(500, 300)

        self._initial_dir = initial_dir
        self._settings = settings
        self._setup_ui()
        self._directory_path = ""

        # Auto-load if initial_dir is a directory
        if self._initial_dir and os.path.isdir(self._initial_dir):
            self._directory_path = self._initial_dir
            self.dir_path_label.setText(self._initial_dir)
            self._load_file_list(self._initial_dir)

    def _setup_ui(self):
        """Set up the user interface"""
        main_layout = QVBoxLayout()

        # Directory selection section
        dir_layout = QHBoxLayout()
        self.dir_path_label = QLabel(self.tr("No directory selected"))
        self.dir_path_label.setWordWrap(True)

        browse_btn = QPushButton(self.tr("Browse..."))
        browse_btn.clicked.connect(self._browse_directory)

        dir_layout.addWidget(QLabel(self.tr("Screenshots Directory:")))
        dir_layout.addWidget(self.dir_path_label, 1)
        dir_layout.addWidget(browse_btn)

        main_layout.addLayout(dir_layout)

        # Options section
        options_layout = QFormLayout()

        # Processing options
        self.overwrite_check = QCheckBox(self.tr("Overwrite existing results"))
        self.overwrite_check.setChecked(False)
        options_layout.addRow(self.overwrite_check)

        main_layout.addLayout(options_layout)

        # File list section
        file_list_label = QLabel(self.tr("Files to process:"))
        main_layout.addWidget(file_list_label)

        self.file_list_text = QTextEdit()
        self.file_list_text.setReadOnly(True)
        self.file_list_text.setMinimumHeight(100)
        main_layout.addWidget(self.file_list_text)

        # Progress section
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel("")
        main_layout.addWidget(self.status_label)

        # Buttons
        button_box = QDialogButtonBox()
        self.process_btn = button_box.addButton(
            self.tr("Process"), QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.process_btn.setEnabled(False)
        cancel_btn = button_box.addButton(
            self.tr("Cancel"), QDialogButtonBox.ButtonRole.RejectRole
        )

        self.process_btn.clicked.connect(self._process_screenshots)
        cancel_btn.clicked.connect(self.reject)

        main_layout.addWidget(button_box)

        self.setLayout(main_layout)

    def _browse_directory(self):
        """Open directory dialog to select screenshots directory"""
        dir_path = QFileDialog.getExistingDirectory(
            self, self.tr("Select Screenshots Directory"), self._initial_dir
        )

        if dir_path:
            self._directory_path = dir_path
            self.dir_path_label.setText(dir_path)
            self._load_file_list(dir_path)

            # Save the directory to settings
            if self._settings:
                self._settings.set_setting("General/screenshots_dir", dir_path)

    def _load_file_list(self, dir_path: str):
        """Load and display list of image files in directory"""
        try:
            image_extensions = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")
            image_files = []

            for filename in os.listdir(dir_path):
                if filename.lower().endswith(image_extensions):
                    image_files.append(filename)

            if image_files:
                self.file_list_text.setPlainText("\n".join(image_files))
                self.process_btn.setEnabled(True)
                self.status_label.setText(
                    self.tr("Found %1 image files").replace("%1", str(len(image_files)))
                )
            else:
                self.file_list_text.setPlainText(
                    self.tr("No image files found in directory")
                )
                self.process_btn.setEnabled(False)
                self.status_label.setText(self.tr("No image files found"))

        except Exception as e:
            self.file_list_text.setPlainText(
                self.tr("Error loading directory: %1").replace("%1", str(e))
            )
            self.process_btn.setEnabled(False)
            self.status_label.setText(self.tr("Error: %1").replace("%1", str(e)))

    def _process_screenshots(self):
        """Process the screenshot images"""
        try:
            # Validate directory
            if not os.path.isdir(self._directory_path):
                QMessageBox.warning(
                    self,
                    self.tr("Invalid Directory"),
                    self.tr("Selected directory does not exist"),
                )
                return

            # Emit signal with overwrite flag and close
            overwrite_flag = self.overwrite_check.isChecked()
            self.processing_started.emit(self._directory_path, overwrite_flag)
            self.accept()

        except Exception as e:
            QMessageBox.critical(
                self,
                self.tr("Processing Error"),
                self.tr("Failed to process screenshots: %1").replace("%1", str(e)),
            )
            self.status_label.setText(self.tr("Error: %1").replace("%1", str(e)))
            self.process_btn.setEnabled(True)


class PreferencesDialog(QDialog):
    """Dialog for managing application preferences"""

    def __init__(self, parent=None, settings=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Preferences"))
        self.setMinimumSize(600, 400)
        self._settings = settings
        self._inputs = {}
        self._setup_ui()
        self._load_preferences()

    def _setup_ui(self):
        """Set up the user interface"""
        layout = QVBoxLayout(self)

        # Scroll area for many settings
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        self.form_layout = QFormLayout(scroll_content)
        scroll.setWidget(scroll_content)

        layout.addWidget(scroll)

        # Buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _load_preferences(self):
        """Load preferences from settings and create form fields"""
        if not self._settings:
            return

        # Help messages for settings
        help_messages = {
            "General/csv_import_path": self.tr(
                "Path to the main account database CSV file."
            ),
            "General/screenshots_dir": self.tr(
                "Directory where your PTCGP screenshots are stored."
            ),
            "General/language": self.tr(
                "Select the display language for the application."
            ),
            "Screenshots/watch_directory": self.tr(
                "Enable or disable automatic monitoring of the screenshots directory."
            ),
            "Screenshots/check_interval": self.tr(
                "How often (in minutes) to check for new screenshots when monitoring is enabled."
            ),
            "Debug/max_cores": self.tr(
                "Override the maximum number of cores used for processing. Set to 0 to use system default."
            ),
        }

        keys = self._settings.settings.allKeys()

        # Group keys by section
        sections_map = {}
        for key in keys:
            section = key.split("/")[0] if "/" in key else ""
            if section not in sections_map:
                sections_map[section] = []
            sections_map[section].append(key)

        # Sort sections according to SECTION_ORDER
        def section_sort_key(s):
            try:
                return SECTION_ORDER.index(s)
            except ValueError:
                return len(SECTION_ORDER) + (1 if not s else 0), s

        sorted_sections = sorted(sections_map.keys(), key=section_sort_key)

        # Translation map for section headers
        section_translations = {
            "General": self.tr("General"),
            "Screenshots": self.tr("Screenshots"),
            "Debug": self.tr("Debug"),
            "": self.tr("Other"),
        }

        current_section = None
        for section in sorted_sections:
            # Add spacing and a header for the new section
            if current_section is not None:
                # Add a gap before the next section
                spacer = QWidget()
                spacer.setMinimumHeight(20)
                self.form_layout.addRow(spacer)

            # Add a section header
            header_text = section_translations.get(section, section).upper()
            header_label = QLabel(header_text)
            header_label.setStyleSheet(
                "font-weight: bold; color: #555; margin-top: 10px;"
            )
            self.form_layout.addRow(header_label)
            current_section = section

            # Sort keys within section
            for key in sorted(sections_map[section]):
                value = self._settings.get_setting(key)

                row_layout = QHBoxLayout()

                # Create a label for the key (show only the setting name, not the section)
                setting_name = key.split("/")[-1] if "/" in key else key
                # Translation map for setting names
                setting_name_translations = {
                    "csv_import_path": self.tr("CSV Import Path"),
                    "screenshots_dir": self.tr("Screenshots Directory"),
                    "language": self.tr("Language"),
                    "watch_directory": self.tr("Watch Directory"),
                    "check_interval": self.tr("Check Interval (min)"),
                    "max_cores": self.tr("Max Cores"),
                }
                display_name = setting_name_translations.get(setting_name, setting_name)
                label = QLabel(display_name)

                # Help message support
                if key in help_messages:
                    # Add tooltip to label
                    label.setToolTip(help_messages[key])

                    # Add a small help icon
                    help_icon = QLabel("ⓘ")
                    help_icon.setToolTip(help_messages[key])
                    help_icon.setStyleSheet(
                        "color: #0078d7; font-weight: bold; margin-right: 5px;"
                    )
                    row_layout.addWidget(help_icon)

                input_widget = None

                # Handle language specifically with a combo box
                if key == "General/language":
                    combo = QComboBox()
                    languages = {
                        "": self.tr("System Default"),
                        "en": "English",
                        "zh": "Chinese",
                        "ja": "Japanese",
                        "de": "German",
                        "fr": "French",
                        "ko": "Korean",
                        "es": "Spanish",
                        "it": "Italian",
                    }
                    for code, name in languages.items():
                        combo.addItem(name, code)

                    index = combo.findData(str(value))
                    if index >= 0:
                        combo.setCurrentIndex(index)

                    row_layout.addWidget(combo)
                    input_widget = combo
                # Handle booleans
                elif isinstance(value, bool) or str(value).lower() in ("true", "false"):
                    checkbox = QCheckBox()
                    checkbox.setChecked(str(value).lower() == "true" or value is True)
                    row_layout.addWidget(checkbox)
                    input_widget = checkbox
                else:
                    line_edit = QLineEdit(str(value))
                    row_layout.addWidget(line_edit)
                    input_widget = line_edit

                    # Add Browse button for path-like keys
                    if "path" in key.lower() or "dir" in key.lower():
                        browse_btn = QPushButton(self.tr("Browse..."))
                        browse_btn.clicked.connect(
                            lambda checked, k=key, le=line_edit: self._browse(k, le)
                        )
                        row_layout.addWidget(browse_btn)

                self._inputs[key] = input_widget
                self.form_layout.addRow(label, row_layout)

    def _browse(self, key, line_edit):
        """Open a file or directory browser based on the key name"""
        current_path = line_edit.text()
        if "dir" in key.lower():
            path = QFileDialog.getExistingDirectory(
                self, self.tr("Select %1").replace("%1", key), current_path
            )
        else:
            path, _ = QFileDialog.getOpenFileName(
                self,
                self.tr("Select %1").replace("%1", key),
                current_path,
                self.tr("All Files (*)"),
            )

        if path:
            line_edit.setText(path)

    def accept(self):
        """Save settings and close"""
        if self._settings:
            restart_required = False
            for key, widget in self._inputs.items():
                old_value = self._settings.get_setting(key)
                new_value = None

                if isinstance(widget, QCheckBox):
                    new_value = widget.isChecked()
                elif isinstance(widget, QLineEdit):
                    new_value = widget.text()
                elif isinstance(widget, QComboBox):
                    new_value = widget.currentData()

                if new_value is not None:
                    self._settings.set_setting(key, new_value)
                    if key == "General/language" and str(old_value) != str(new_value):
                        restart_required = True

            if restart_required:
                QMessageBox.information(
                    self,
                    self.tr("Restart Required"),
                    self.tr(
                        "The language change will take effect after you restart the application."
                    ),
                )
        super().accept()


class AboutDialog(QDialog):
    """About dialog for the application"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("About PTCGPB Companion"))
        self.setMinimumSize(400, 100)

        self._setup_ui()

    def _setup_ui(self):
        """Set up the user interface"""
        main_layout = QVBoxLayout()

        # Application icon
        icon_label = QLabel()
        icon_label.setPixmap(QIcon.fromTheme("cardcounter").pixmap(64, 64))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(icon_label)

        # Application info
        version = get_app_version()
        info_label = QLabel(self.tr("""<h2>PTCGPB Companion</h2>
               <p>Pokémon Card Identification Tool</p>
               <p>Version %1</p>
               <p>© 2026 itsthejoker</p>
               <p>MIT License & open source. Made with 🌯.<br><a href="https://github.com/itsthejoker/ptcgpb_companion">https://github.com/itsthejoker/ptcgpb-companion</a></p>
               <p>Built with PyQt6 and OpenCV</p><p></p>""").replace("%1", version))
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(info_label)

        # Close button
        close_btn = QPushButton(self.tr("Close"))
        close_btn.clicked.connect(self.accept)
        close_btn.setMinimumWidth(100)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        btn_layout.addStretch()

        main_layout.addLayout(btn_layout)

        self.setLayout(main_layout)


class CardImageDialog(QDialog):
    """Dialog for displaying a full-size card image"""

    def __init__(
        self,
        image_path: str,
        card_name: str = "Card Image",
        parent=None,
        scale: float = 1.0,
    ):
        super().__init__(parent)
        self.setWindowTitle(card_name)

        # Load pixmap
        pixmap = QPixmap(str(image_path))
        if pixmap.isNull():
            # If image failed to load, show an error and close
            QMessageBox.critical(
                self,
                self.tr("Error"),
                self.tr("Could not load image: %1").replace("%1", image_path),
            )
            # Use QTimer to close after the event loop starts if needed,
            # but reject() here might be fine if called after super().__init__
            self.reject()
            return

        # Scale pixmap if requested
        if scale != 1.0:
            new_width = int(pixmap.width() * scale)
            new_height = int(pixmap.height() * scale)
            pixmap = pixmap.scaled(
                new_width,
                new_height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

        # Set up UI
        layout = QVBoxLayout()

        # Create scroll area for large images
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)

        # Image label
        self.image_label = QLabel()
        self.image_label.setPixmap(pixmap)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        scroll_area.setWidget(self.image_label)
        layout.addWidget(scroll_area)

        # Close button
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)

        # Adjust size based on image, but with a maximum
        screen_size = QApplication.primaryScreen().availableSize()
        max_width = int(screen_size.width() * 0.8)
        max_height = int(screen_size.height() * 0.8)

        dialog_width = min(pixmap.width() + 40, max_width)
        dialog_height = min(pixmap.height() + 100, max_height)

        self.resize(dialog_width, dialog_height)


class NumericTableWidgetItem(QTableWidgetItem):
    """Custom QTableWidgetItem for numeric sorting"""

    def __init__(self, value, is_age=False):
        if value is None or (isinstance(value, str) and not value.strip()):
            self.sort_value = -1 if not is_age else -1
            display_value = "-"
        elif is_age:
            # For age, value is like "5d"
            try:
                self.sort_value = int(value.replace("d", ""))
                display_value = value
            except (ValueError, AttributeError):
                self.sort_value = -1
                display_value = "-"
        else:
            try:
                self.sort_value = int(value)
                display_value = str(value)
            except (ValueError, TypeError):
                self.sort_value = -1
                display_value = "-"

        super().__init__(display_value)

    def __lt__(self, other):
        if isinstance(other, NumericTableWidgetItem):
            return self.sort_value < other.sort_value
        return super().__lt__(other)


class AccountCardListDialog(QDialog):
    """Dialog showing a filterable list of accounts that have a specific card"""

    def __init__(
        self,
        card_name: str,
        card_code: str,
        account_data: list,
        screenshots_dir: str = "",
        on_removed: Callable = None,
        parent=None,
        **kwargs,
    ):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Accounts owning %1").replace("%1", card_name))
        self.setMinimumSize(600, 500)

        self.card_name = card_name
        self.card_code = card_code
        self.screenshots_dir = screenshots_dir
        self.all_data = (
            account_data  # List of (account_name, count, screenshot_path, shinedust)
        )
        self.on_removed = on_removed

        self._setup_ui()
        self._populate_table(self.all_data)

    def _setup_ui(self):
        """Set up the user interface"""
        layout = QVBoxLayout(self)

        # Header info
        info_label = QLabel(
            self.tr("Showing account distribution for: <b>%1</b>").replace(
                "%1", self.card_name
            )
        )
        layout.addWidget(info_label)

        # Search/Filter bar
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel(self.tr("Filter:")))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(self.tr("Search account name..."))
        self.search_input.textChanged.connect(self._filter_data)
        filter_layout.addWidget(self.search_input)
        layout.addLayout(filter_layout)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            [
                self.tr("Account Name"),
                self.tr("Quantity"),
                self.tr("Shinedust"),
                self.tr("Age"),
                self.tr("Screenshot"),
                self.tr("Action"),
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Interactive
        )
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Interactive
        )
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Interactive
        )
        self.table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Interactive
        )
        self.table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.Interactive
        )

        # Set default widths for small columns to avoid layout jumping
        self.table.setColumnWidth(1, 60)
        self.table.setColumnWidth(2, 80)
        self.table.setColumnWidth(3, 60)
        self.table.setColumnWidth(4, 100)
        self.table.setColumnWidth(5, 80)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

        # Close button
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        copy_button = QPushButton(self.tr("Copy all to clipboard"))
        copy_button.clicked.connect(self._copy_all_accounts)
        button_box.addButton(copy_button, QDialogButtonBox.ButtonRole.ActionRole)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _populate_table(self, data):
        """Populate table with data"""
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(data))
        for i, row_data in enumerate(data):
            account = row_data[0]
            count = row_data[1]
            screenshot_path = row_data[2] if len(row_data) > 2 else None
            shinedust = row_data[3] if len(row_data) > 3 else None

            self.table.setItem(i, 0, QTableWidgetItem(str(account)))

            count_item = NumericTableWidgetItem(count)
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(i, 1, count_item)

            # Shinedust column
            shinedust_item = NumericTableWidgetItem(shinedust)
            shinedust_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(i, 2, shinedust_item)

            # Age column
            age_val = "-"
            try:
                dt = datetime.strptime(str(account), "%Y%m%d%H%M%S")
                now = datetime.now()
                diff = now - dt
                age_val = self.tr("%1d").replace("%1", str(diff.days))
            except (ValueError, TypeError):
                pass
            age_item = NumericTableWidgetItem(age_val, is_age=True)
            age_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(i, 3, age_item)

            # Screenshot button
            if screenshot_path:
                screenshot_btn = QPushButton(self.tr("Screenshot"))
                screenshot_btn.clicked.connect(
                    lambda checked, p=screenshot_path: self._view_screenshot(p)
                )
                self.table.setCellWidget(i, 4, screenshot_btn)
            else:
                self.table.setItem(i, 4, QTableWidgetItem(""))

            # Remove button
            remove_button = QPushButton(self.tr("Remove"))
            remove_button.clicked.connect(
                lambda checked, a=account, p=screenshot_path: self._remove_card(a, p)
            )
            self.table.setCellWidget(i, 5, remove_button)
        self.table.setSortingEnabled(True)

    def _view_screenshot(self, path):
        """Open the screenshot in a new window"""
        # Resolve path if it's not absolute and we have a screenshots_dir
        resolved_path = path
        if path and not os.path.isabs(path) and self.screenshots_dir:
            # Handle potential cross-platform issues by normalizing separators
            normalized_name = path.replace("\\", os.sep).replace("/", os.sep)
            resolved_path = os.path.join(self.screenshots_dir, normalized_name)

        if not resolved_path or not os.path.exists(resolved_path):
            QMessageBox.warning(
                self,
                self.tr("Error"),
                self.tr("The screenshot path could not be found:\n%1").replace(
                    "%1", resolved_path or path
                ),
            )
            return

        dialog = CardImageDialog(
            resolved_path, f"{os.path.basename(resolved_path)}", self, scale=2.0
        )
        dialog.exec()

    def _remove_card(self, account_name, screenshot_path=None):
        """Handle card removal from an account"""
        from app.db.models import Card, Account, ScreenshotCard
        from app.names import SHINEDUST_REQUIREMENTS

        card = Card.objects.filter(code=self.card_code).first()
        if not card:
            QMessageBox.warning(
                self, self.tr("Error"), self.tr("Card not found in database.")
            )
            return

        rarity = card.rarity
        cost = 0

        if rarity == "1S":
            # Ask 4000 or 10000
            msg = QMessageBox(self)
            msg.setWindowTitle(self.tr("Select Shinedust Cost"))
            msg.setText(
                self.tr("Is this a 4,000 or 10,000 shinedust move for %1?").replace(
                    "%1", self.card_name
                )
            )
            btn4k = msg.addButton("4,000", QMessageBox.ButtonRole.ActionRole)
            btn10k = msg.addButton("10,000", QMessageBox.ButtonRole.ActionRole)
            msg.addButton(QMessageBox.StandardButton.Cancel)
            msg.exec()
            if msg.clickedButton() == btn4k:
                cost = 4000
            elif msg.clickedButton() == btn10k:
                cost = 10000
            else:
                return  # Cancelled
        elif rarity == "2S":
            # Ask 25000 or 30000
            msg = QMessageBox(self)
            msg.setWindowTitle(self.tr("Select Shinedust Cost"))
            msg.setText(
                self.tr("Is this a 25,000 or 30,000 shinedust move for %1?").replace(
                    "%1", self.card_name
                )
            )
            btn25k = msg.addButton("25,000", QMessageBox.ButtonRole.ActionRole)
            btn30k = msg.addButton("30,000", QMessageBox.ButtonRole.ActionRole)
            msg.addButton(QMessageBox.StandardButton.Cancel)
            msg.exec()
            if msg.clickedButton() == btn25k:
                cost = 25000
            elif msg.clickedButton() == btn30k:
                cost = 30000
            else:
                return  # Cancelled
        else:
            cost = SHINEDUST_REQUIREMENTS.get(rarity, 0)

        # Get account and check shinedust
        account = Account.objects.filter(name=account_name).first()
        if not account:
            QMessageBox.warning(
                self,
                self.tr("Error"),
                self.tr("Account '%1' not found.").replace("%1", account_name),
            )
            return

        try:
            current_shinedust = int(account.shinedust) if account.shinedust else 0
        except (ValueError, TypeError):
            current_shinedust = 0

        if current_shinedust < cost:
            insufficient_box = QMessageBox(self)
            insufficient_box.setWindowTitle(self.tr("Insufficient Shinedust"))
            insufficient_box.setText(
                self.tr(
                    "Account <b>%1</b> does not have enough shinedust (%2) "
                    "to perform this action (cost: %3)."
                )
                .replace("%1", account_name)
                .replace("%2", f"{current_shinedust:,}")
                .replace("%3", f"{cost:,}")
            )
            remove_anyway_btn = insufficient_box.addButton(
                self.tr("Remove anyway"), QMessageBox.ButtonRole.ActionRole
            )
            insufficient_box.addButton(QMessageBox.StandardButton.Cancel)
            insufficient_box.exec()
            if insufficient_box.clickedButton() != remove_anyway_btn:
                return
            cost = 0

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self.tr("Remove Card?"))
        msg_box.setText(
            self.tr(
                "One instance of <b>%1</b> will be removed from account <b>%2</b>.<br><br>"
                "This will cost <b>%3</b> shinedust.<br><br>"
                "If the account has multiples of this same card, only one will be removed."
            )
            .replace("%1", self.card_name)
            .replace("%2", account_name)
            .replace("%3", f"{cost:,}")
        )
        msg_box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)

        if msg_box.exec() == QMessageBox.StandardButton.Yes:
            # Find one instance to remove
            query = ScreenshotCard.objects.filter(
                screenshot__account__name=account_name, card__code=self.card_code
            )

            if screenshot_path:
                query = query.filter(screenshot__name=screenshot_path)

            sc = query.first()
            if sc:
                # Update shinedust
                account.shinedust = str(current_shinedust - cost)
                account.save()

                sc.delete()
                success = True
            else:
                success = False

            if success:
                record_traded_card(account_name, self.card_code)

                # Update local data
                new_shinedust_str = str(current_shinedust - cost)
                to_remove_idx = -1
                for i in range(len(self.all_data)):
                    row = self.all_data[i]
                    acc = row[0]
                    if acc == account_name:
                        new_row = list(row)
                        if len(new_row) > 3:
                            new_row[3] = new_shinedust_str

                        count = row[1]
                        spath = row[2] if len(row) > 2 else None

                        # Match by account AND screenshot path if possible for the one to remove
                        if to_remove_idx == -1 and (
                            screenshot_path is None or spath == screenshot_path
                        ):
                            if count > 1:
                                new_row[1] = count - 1
                                self.all_data[i] = tuple(new_row)
                                to_remove_idx = -2  # Handled
                            else:
                                to_remove_idx = i
                        else:
                            self.all_data[i] = tuple(new_row)

                if to_remove_idx >= 0:
                    self.all_data.pop(to_remove_idx)

                # Refresh table
                self._filter_data(self.search_input.text())

                # Notify callback
                if self.on_removed:
                    self.on_removed()
            else:
                QMessageBox.warning(
                    self,
                    self.tr("Error"),
                    self.tr("Could not find card in database to remove."),
                )

    def _copy_all_accounts(self):
        """Copy unique account names to clipboard"""
        account_names = {str(item[0]) for item in self.all_data}
        accounts_text = "\n".join(sorted(account_names))
        QApplication.clipboard().setText(accounts_text)

    def _filter_data(self, text):
        """Filter table data based on search text"""
        search_text = text.lower()
        filtered_data = [
            item for item in self.all_data if search_text in str(item[0]).lower()
        ]
        self._populate_table(filtered_data)

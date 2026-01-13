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
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QSize
from PyQt6.QtGui import QIcon, QValidator, QPixmap
import os
import csv
from typing import Optional, Dict, Any


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
        self.setWindowTitle("Import CSV")
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
        self.file_path_label = QLabel("No file selected")
        self.file_path_label.setWordWrap(True)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_file)

        file_layout.addWidget(QLabel("CSV File:"))
        file_layout.addWidget(self.file_path_label, 1)
        file_layout.addWidget(browse_btn)

        main_layout.addLayout(file_layout)

        # CSV preview section
        preview_label = QLabel("CSV Preview (first 10 rows):")
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
            "Import", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.import_btn.setEnabled(False)
        cancel_btn = button_box.addButton(
            "Cancel", QDialogButtonBox.ButtonRole.RejectRole
        )

        self.import_btn.clicked.connect(self._import_csv)
        cancel_btn.clicked.connect(self.reject)

        main_layout.addWidget(button_box)

        self.setLayout(main_layout)

    def _browse_file(self):
        """Open file dialog to select CSV file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select CSV File",
            self._initial_path,
            "CSV Files (*.csv);;All Files (*)",
        )

        if file_path:
            self._file_path = file_path
            self.file_path_label.setText(file_path)
            self._load_csv_preview(file_path)

            # Save the path to settings
            if self._settings:
                self._settings.set_setting("csv_import_path", file_path)

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
                self.status_label.setText("CSV file loaded successfully")

        except Exception as e:
            self.preview_text.setPlainText(f"Error loading CSV: {e}")
            self.import_btn.setEnabled(False)
            self.status_label.setText(f"Error: {e}")

    def _import_csv(self):
        """Import the CSV file"""
        try:
            # Emit signal and close
            self.csv_imported.emit(self._file_path)
            self.accept()

        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Failed to import CSV: {e}")
            self.status_label.setText(f"Error: {e}")
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
        self.setWindowTitle("Process Screenshots")
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
        self.dir_path_label = QLabel("No directory selected")
        self.dir_path_label.setWordWrap(True)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_directory)

        dir_layout.addWidget(QLabel("Screenshots Directory:"))
        dir_layout.addWidget(self.dir_path_label, 1)
        dir_layout.addWidget(browse_btn)

        main_layout.addLayout(dir_layout)

        # Options section
        options_layout = QFormLayout()

        # Processing options
        self.overwrite_check = QCheckBox("Overwrite existing results")
        self.overwrite_check.setChecked(False)
        options_layout.addRow(self.overwrite_check)

        main_layout.addLayout(options_layout)

        # File list section
        file_list_label = QLabel("Files to process:")
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
            "Process", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.process_btn.setEnabled(False)
        cancel_btn = button_box.addButton(
            "Cancel", QDialogButtonBox.ButtonRole.RejectRole
        )

        self.process_btn.clicked.connect(self._process_screenshots)
        cancel_btn.clicked.connect(self.reject)

        main_layout.addWidget(button_box)

        self.setLayout(main_layout)

    def _browse_directory(self):
        """Open directory dialog to select screenshots directory"""
        dir_path = QFileDialog.getExistingDirectory(
            self, "Select Screenshots Directory", self._initial_dir
        )

        if dir_path:
            self._directory_path = dir_path
            self.dir_path_label.setText(dir_path)
            self._load_file_list(dir_path)

            # Save the directory to settings
            if self._settings:
                self._settings.set_setting("screenshots_dir", dir_path)

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
                self.status_label.setText(f"Found {len(image_files)} image files")
            else:
                self.file_list_text.setPlainText("No image files found in directory")
                self.process_btn.setEnabled(False)
                self.status_label.setText("No image files found")

        except Exception as e:
            self.file_list_text.setPlainText(f"Error loading directory: {e}")
            self.process_btn.setEnabled(False)
            self.status_label.setText(f"Error: {e}")

    def _process_screenshots(self):
        """Process the screenshot images"""
        try:
            # Validate directory
            if not os.path.isdir(self._directory_path):
                QMessageBox.warning(
                    self, "Invalid Directory", "Selected directory does not exist"
                )
                return

            # Emit signal with overwrite flag and close
            overwrite_flag = self.overwrite_check.isChecked()
            self.processing_started.emit(self._directory_path, overwrite_flag)
            self.accept()

        except Exception as e:
            QMessageBox.critical(
                self, "Processing Error", f"Failed to process screenshots: {e}"
            )
            self.status_label.setText(f"Error: {e}")
            self.process_btn.setEnabled(True)

    def _process_images(self):
        """Process image files and extract card information"""
        # This is now handled by the ScreenshotProcessingWorker in the main window
        pass


class AboutDialog(QDialog):
    """About dialog for the application"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About Card Counter")
        self.setMinimumSize(400, 300)

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
        info_label = QLabel(
            """<h2>PTCGPB Companion</h2>
               <p>Pokémon Card Identification Tool</p>
               <p>Version 1.0.0</p>
               <p>© 2026 itsthejoker</p>
               <p>Built with PyQt6 and OpenCV</p>"""
        )
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(info_label)

        # Close button
        close_btn = QPushButton("Close")
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

    def __init__(self, image_path: str, card_name: str = "Card Image", parent=None):
        super().__init__(parent)
        self.setWindowTitle(card_name)

        # Load pixmap
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            # If image failed to load, show an error and close
            QMessageBox.critical(self, "Error", f"Could not load image: {image_path}")
            # Use QTimer to close after the event loop starts if needed,
            # but reject() here might be fine if called after super().__init__
            self.reject()
            return

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


class AccountCardListDialog(QDialog):
    """Dialog showing a filterable list of accounts that have a specific card"""

    def __init__(self, card_name: str, card_code: str, account_data: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Accounts owning {card_name}")
        self.setMinimumSize(400, 500)

        self.card_name = card_name
        self.card_code = card_code
        self.all_data = account_data  # List of (account_name, count)

        self._setup_ui()
        self._populate_table(self.all_data)

    def _setup_ui(self):
        """Set up the user interface"""
        layout = QVBoxLayout(self)

        # Header info
        info_label = QLabel(
            f"Showing account distribution for: <b>{self.card_name}</b>"
        )
        layout.addWidget(info_label)

        # Search/Filter bar
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Filter:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search account name...")
        self.search_input.textChanged.connect(self._filter_data)
        filter_layout.addWidget(self.search_input)
        layout.addLayout(filter_layout)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Account Name", "Quantity"])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

        # Close button
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _populate_table(self, data):
        """Populate table with data"""
        self.table.setRowCount(len(data))
        for i, (account, count) in enumerate(data):
            self.table.setItem(i, 0, QTableWidgetItem(str(account)))
            count_item = QTableWidgetItem(str(count))
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(i, 1, count_item)

    def _filter_data(self, text):
        """Filter table data based on search text"""
        search_text = text.lower()
        filtered_data = [
            item for item in self.all_data if search_text in str(item[0]).lower()
        ]
        self._populate_table(filtered_data)

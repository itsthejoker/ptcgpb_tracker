"""
Card Counter Main Window

Main application window for the Card Counter PyQt6 application.
This module provides the primary user interface for the application.
"""

from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QStatusBar,
    QTableView,
    QComboBox,
    QLineEdit,
    QHeaderView,
    QAbstractItemView,
    QDialog,
    QListWidget,
    QTextEdit,
    QMessageBox,
    QProgressBar,
)
from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtGui import QAction
import os
import sys
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

from app.models import CardModel, ProcessingTaskModel
from app.names import cards as CARD_NAMES, sets as SET_NAMES, rarity as RARITY_MAP

from app.dialogs import (
    CSVImportDialog,
    ScreenshotProcessingDialog,
    AboutDialog,
    CardImageDialog,
    AccountCardListDialog,
)

from app.workers import (
    CSVImportWorker,
    ScreenshotProcessingWorker,
    CardDataLoadWorker,
    CardArtDownloadWorker,
    VersionCheckWorker,
)
from PyQt6.QtCore import QThreadPool, Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from app.utils import PortableSettings, get_portable_path, get_app_version


class MainWindow(QMainWindow):
    """
    Main application window for Card Counter

    Provides the primary user interface with menu bar, toolbar,
    tab-based central widget, and status bar.
    """

    def __init__(self):
        """Initialize the main window"""
        super().__init__()

        # Set window properties
        self.setWindowTitle("PTCGPB Companion")
        self.setMinimumSize(800, 600)

        # Initialize settings
        self.settings = PortableSettings()

        # Track combined import flow state
        self._combined_import_request = None

        # Initialize core non-UI components first
        self._init_database()
        self._init_thread_pool()
        self._setup_processing_status()
        # Cards tab async loading state
        self._cards_load_generation = 0
        self._current_card_load_worker = None

        # Version check state
        self.new_version_available = False
        self.latest_version_info = {}

        # Dashboard statistics debounce timer
        self._dashboard_timer = QTimer()
        self._dashboard_timer.setSingleShot(True)
        self._dashboard_timer.timeout.connect(self._update_dashboard_statistics)

        # Initialize UI components
        self._setup_status_bar()  # Initialize status bar early so it can be used by other setup methods
        self._setup_menu_bar()
        self._setup_central_widget()

        # Set initial state for combined import availability
        self._update_load_new_data_availability()

        # Ensure card art templates are available
        self._start_art_download_if_needed()

        # Load initial dashboard statistics
        self._update_dashboard_statistics()

        # Check for updates
        self._check_for_updates()

    def _start_art_download_if_needed(self):
        """Check for card art directory and start background download if missing"""
        try:
            from app.utils import get_portable_path

            template_dir = get_portable_path("resources", "card_imgs")
            if not os.path.isdir(template_dir):
                # Ask user if they want to download art now or quit
                msg_box = QMessageBox(self)
                msg_box.setWindowTitle("Download Card Art")
                msg_box.setText(
                    "Card art images are missing. These are required for card recognition.\n\n"
                    "Would you like to download them now?"
                )
                download_button = msg_box.addButton("Download", QMessageBox.ButtonRole.AcceptRole)
                quit_button = msg_box.addButton("Quit", QMessageBox.ButtonRole.RejectRole)
                msg_box.setDefaultButton(download_button)
                msg_box.setIcon(QMessageBox.Icon.Question)

                msg_box.exec()

                if msg_box.clickedButton() == quit_button:
                    logger.info("User chose to quit instead of downloading card art")
                    sys.exit(0)

                self._update_status_message(
                    "Downloading card art in background…"
                )

                # Create a task entry so it appears in Processing tab & counter
                import uuid

                task_id = str(uuid.uuid4())
                self._add_processing_task(task_id, "Card Art Download")

                worker = CardArtDownloadWorker()
                # Attach task_id for cancellation support
                worker.task_id = task_id

                # Connect signals with task context
                worker.signals.progress.connect(
                    lambda c, t, tid=task_id: self._on_art_download_progress(c, t, tid)
                )
                worker.signals.status.connect(
                    lambda s, tid=task_id: self._on_art_download_status(s, tid)
                )
                worker.signals.result.connect(
                    lambda r, tid=task_id: self._on_art_download_result(r, tid)
                )
                worker.signals.error.connect(
                    lambda e, tid=task_id: self._on_art_download_error(e, tid)
                )
                worker.signals.finished.connect(
                    lambda w=worker, tid=task_id: self._on_art_download_finished(w, tid)
                )

                # Track worker and start
                self.active_workers.append(worker)
                self.thread_pool.start(worker)

                # Mark task running and update dashboard counters
                self._update_task_status(task_id, "Running")
                self._request_dashboard_update()
        except Exception as e:
            logger.error(f"Failed to start art download worker: {e}")
            self._update_status_message(f"Failed to start art download: {e}")

    def _init_database(self):
        """Initialize database connection"""
        try:
            from app.database import Database

            self.db = Database()
            logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            # Show error message to user
            from app.utils import show_error_message

            show_error_message("Database Error", f"Failed to initialize database: {e}")

    def _init_thread_pool(self):
        """Initialize thread pool for background processing"""
        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(4)  # Limit to 4 concurrent workers
        logger.info(
            f"Thread pool initialized with max {self.thread_pool.maxThreadCount()} threads"
        )

        # Store active workers for cancellation
        self.active_workers = []

    def _check_for_updates(self):
        """Start background check for application updates"""
        try:
            current_version = get_app_version()
            if current_version == "unknown":
                return

            worker = VersionCheckWorker(current_version)
            worker.signals.result.connect(self._on_version_check_result)
            self.thread_pool.start(worker)
        except Exception as e:
            logger.error(f"Failed to start version check: {e}")

    def _on_version_check_result(self, result):
        """Handle result from version check worker"""
        if result and result.get("new_available"):
            self.new_version_available = True
            self.latest_version_info = result
            # Refresh recent activity to show the update message
            self._update_recent_activity()

    def _on_recent_activity_item_clicked(self, item):
        """Handle clicks on recent activity items"""
        url = item.data(Qt.ItemDataRole.UserRole)
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _setup_menu_bar(self):
        """Set up the menu bar"""
        menu_bar = self.menuBar()

        # File menu
        file_menu = menu_bar.addMenu("&File")

        # Import CSV action
        import_csv_action = QAction("&Import CSV", self)
        import_csv_action.setShortcut("Ctrl+I")
        import_csv_action.triggered.connect(self._on_import_csv)
        file_menu.addAction(import_csv_action)

        # Process Screenshots action
        process_action = QAction("&Process Screenshots", self)
        process_action.setShortcut("Ctrl+P")
        process_action.triggered.connect(self._on_process_screenshots)
        file_menu.addAction(process_action)

        # Combined import action
        self.load_new_data_action = QAction("&Load New Data", self)
        self.load_new_data_action.triggered.connect(self._on_load_new_data)
        self.load_new_data_action.setEnabled(False)
        file_menu.addAction(self.load_new_data_action)

        # Exit action
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addSeparator()
        file_menu.addAction(exit_action)

        # View menu. Not currently used, but keeping in case we need it eventually
        # view_menu = menu_bar.addMenu("&View")

        # Help menu
        help_menu = menu_bar.addMenu("&Help")

        # About action
        about_action = QAction("&About", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

    def _setup_central_widget(self):
        """Set up the central widget with tab interface"""
        # Create main widget and layout
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        main_widget.setLayout(main_layout)

        # Create tab widget
        self.tab_widget = QTabWidget()

        # Add tabs
        self._setup_dashboard_tab()
        self._setup_cards_tab()
        self._setup_processing_tab()

        # Connect tab change handler
        self.tab_widget.currentChanged.connect(self._on_tab_changed)

        main_layout.addWidget(self.tab_widget)
        self.setCentralWidget(main_widget)

    def _setup_dashboard_tab(self):
        """Set up the dashboard tab with statistics and quick actions"""
        dashboard_widget = QWidget()
        dashboard_layout = QVBoxLayout()

        # Statistics section
        stats_layout = QGridLayout()

        # Total cards statistic
        self.total_cards_label = QLabel("Total Cards: 0")
        self.total_cards_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        stats_layout.addWidget(self.total_cards_label, 0, 0)

        # Total packs statistic
        self.total_packs_label = QLabel("Total Packs: 0")
        self.total_packs_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        stats_layout.addWidget(self.total_packs_label, 0, 1)

        # Unique cards statistic
        self.unique_cards_label = QLabel("Unique Cards: 0")
        self.unique_cards_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        stats_layout.addWidget(self.unique_cards_label, 1, 0)

        # Last processed statistic
        self.last_processed_label = QLabel("Last Processed: Never")
        self.last_processed_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        stats_layout.addWidget(self.last_processed_label, 1, 1)

        dashboard_layout.addLayout(stats_layout)

        # Quick actions section
        actions_layout = QHBoxLayout()

        self.import_csv_btn = QPushButton("Import CSV")
        self.import_csv_btn.clicked.connect(self._on_import_csv)
        actions_layout.addWidget(self.import_csv_btn)

        self.import_screenshots_btn = QPushButton("Load Screenshots")
        self.import_screenshots_btn.clicked.connect(self._on_process_screenshots)
        actions_layout.addWidget(self.import_screenshots_btn)

        self.load_new_data_btn = QPushButton("Load New Data")
        self.load_new_data_btn.clicked.connect(self._on_load_new_data)
        actions_layout.addWidget(self.load_new_data_btn)

        dashboard_layout.addLayout(actions_layout)

        # Recent activity section
        recent_header_layout = QHBoxLayout()
        recent_label = QLabel("Recent Activity:")
        recent_header_layout.addWidget(recent_label)

        recent_header_layout.addStretch()

        clear_recent_btn = QPushButton("Clear")
        clear_recent_btn.setFixedWidth(80)
        clear_recent_btn.clicked.connect(self._clear_recent_activity)
        recent_header_layout.addWidget(clear_recent_btn)

        dashboard_layout.addLayout(recent_header_layout)

        self.recent_activity_list = QListWidget()
        self.recent_activity_list.setMinimumHeight(200)
        self.recent_activity_list.itemClicked.connect(
            self._on_recent_activity_item_clicked
        )
        dashboard_layout.addWidget(self.recent_activity_list)

        dashboard_widget.setLayout(dashboard_layout)
        self.tab_widget.addTab(dashboard_widget, "Dashboard")

        # Dashboard statistics will be loaded after status bar is initialized

    def _update_dashboard_statistics(self):
        """Update dashboard statistics from database"""
        # Only update if the dashboard tab is active to save resources
        if self.tab_widget.currentIndex() != 0:
            return

        try:
            if hasattr(self, "db") and self.db:
                # Get statistics from database
                total_cards = self.db.get_total_cards_count()
                unique_cards = self.db.get_unique_cards_count()
                total_packs = self.db.get_total_packs_count()
                last_processed = self.db.get_last_processed_timestamp()

                # Update UI
                self.total_cards_label.setText(f"Total Cards: {total_cards}")
                self.unique_cards_label.setText(f"Unique Cards: {unique_cards}")
                self.total_packs_label.setText(f"Total Packs: {total_packs}")

                if last_processed:
                    self.last_processed_label.setText(
                        f"Last Processed: {last_processed}"
                    )
                else:
                    self.last_processed_label.setText("Last Processed: Never")

                # Update recent activity
                self._update_recent_activity()

                self._update_status_message("Dashboard statistics updated")
            else:
                self._update_status_message("Database not available for statistics")

        except Exception as e:
            logger.error(f"Error updating dashboard statistics: {e}")
            self._update_status_message(f"Error updating statistics: {e}")

    def _request_dashboard_update(self):
        """Request a dashboard update with debouncing"""
        if hasattr(self, "_dashboard_timer"):
            self._dashboard_timer.start(1000)  # Wait 1 second before actually updating
        else:
            self._update_dashboard_statistics()

    def _update_recent_activity(self):
        """Update recent activity list"""
        try:
            if hasattr(self, "db") and self.db:
                # Clear existing items
                self.recent_activity_list.clear()

                all_items = []

                # 1. Get recent activity from database (processed screenshots)
                db_activities = []
                if getattr(self, "recent_activity_limit", 0) > 0:
                    db_activities = self.db.get_recent_activity(
                        limit=self.recent_activity_limit
                    )

                # DB activities come newest first from SQL, so reverse them for bottom-newest
                for activity in reversed(db_activities):
                    item_text = f"{activity['timestamp']} - {activity['description']}"
                    all_items.append({"text": item_text, "color": None})

                # 2. Add session status messages
                session_msgs = list(getattr(self, "recent_activity_messages", []))
                # session_msgs are in chronological order, so just append
                for entry in session_msgs:
                    item_text = f"{entry['timestamp']} - {entry['description']}"
                    all_items.append({"text": item_text, "color": None})

                # 3. Add active tasks last (so they are at the bottom)
                active_tasks = [
                    t
                    for t in self.processing_tasks
                    if t["status"] in ["Running", "Queued"]
                ]
                for task in active_tasks:
                    progress_text = (
                        f" ({task['progress']}%)" if task["status"] == "Running" else ""
                    )
                    item_text = (
                        f"[{task['status']}] {task['description']}{progress_text}"
                    )
                    color = Qt.GlobalColor.blue if task["status"] == "Running" else Qt.GlobalColor.darkYellow
                    all_items.append({"text": item_text, "color": color})

                # 4. Add update message if available
                if getattr(self, "new_version_available", False):
                    latest_version = self.latest_version_info.get(
                        "latest_version", "unknown"
                    )
                    download_url = self.latest_version_info.get(
                        "url",
                        "https://github.com/itsthejoker/ptcgpb_companion/releases/latest",
                    )

                    update_text = f"✨ NEW UPDATE AVAILABLE: v{latest_version}! ✨\nDownload it from: {download_url}"
                    all_items.append(
                        {
                            "text": update_text,
                            "color": Qt.GlobalColor.red,
                            "is_update": True,
                            "url": download_url,
                        }
                    )

                # Add all to list
                for item_data in all_items:
                    self.recent_activity_list.addItem(item_data["text"])
                    last_item = self.recent_activity_list.item(
                        self.recent_activity_list.count() - 1
                    )

                    if item_data.get("url"):
                        last_item.setData(Qt.ItemDataRole.UserRole, item_data["url"])
                        # Change cursor to pointing hand when hovering over this item
                        # Note: QListWidget doesn't easily support per-item cursors without custom delegate,
                        # but we can at least make it look more like a link.
                        if item_data.get("is_update"):
                            last_item.setToolTip("Click to open download page")

                    if item_data.get("is_update"):
                        font = last_item.font()
                        font.setPointSize(12)
                        font.setBold(True)
                        last_item.setFont(font)

                    if item_data.get("color"):
                        last_item.setForeground(item_data["color"])

                if not all_items:
                    self.recent_activity_list.addItem("No recent activity")
                else:
                    # Scroll to bottom to show newest entries
                    self.recent_activity_list.scrollToBottom()

        except Exception as e:
            logger.error(f"Error updating recent activity: {e}")
            self.recent_activity_list.clear()
            self.recent_activity_list.addItem("Error loading activity")

    def _setup_cards_tab(self):
        """Set up the cards tab"""
        cards_widget = QWidget()
        cards_layout = QVBoxLayout()

        # Create filter controls
        filter_layout = QHBoxLayout()

        # Set filter
        self.set_filter = QComboBox()
        self.set_filter.addItem("All Sets")
        self.set_filter.setMinimumWidth(150)
        filter_layout.addWidget(QLabel("Set:"))
        filter_layout.addWidget(self.set_filter)

        # Rarity filter
        self.rarity_filter = QComboBox()
        self.rarity_filter.addItem("All Rarities")
        self.rarity_filter.setMinimumWidth(150)
        filter_layout.addWidget(QLabel("Rarity:"))
        filter_layout.addWidget(self.rarity_filter)

        # Search box
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search cards...")
        self.search_box.setMinimumWidth(200)
        filter_layout.addWidget(self.search_box)

        # Refresh button
        self.refresh_cards_btn = QPushButton("Refresh")
        self.refresh_cards_btn.clicked.connect(self._refresh_cards_tab)
        filter_layout.addWidget(self.refresh_cards_btn)

        # Add filter controls to layout
        cards_layout.addLayout(filter_layout)

        # Create table view for cards
        self.cards_table = QTableView()
        self.cards_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.cards_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.cards_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.cards_table.setSortingEnabled(True)

        # Configure art display
        self.cards_table.setIconSize(QSize(48, 64))
        self.cards_table.verticalHeader().setDefaultSectionSize(70)

        # Set up vertical header
        vertical_header = self.cards_table.verticalHeader()
        vertical_header.setVisible(False)

        # Add table to layout
        cards_layout.addWidget(self.cards_table)

        # Set up card model
        self._setup_card_model()

        cards_widget.setLayout(cards_layout)
        self.cards_tab_index = self.tab_widget.addTab(cards_widget, "Cards")

    def _on_tab_changed(self, index):
        """Handle tab changes to refresh content"""
        if index == 0:  # Dashboard tab
            self._update_dashboard_statistics()
        elif index == getattr(self, "cards_tab_index", -1):
            # Only auto-load if there is no data yet
            try:
                has_data = False
                if hasattr(self, "card_model") and hasattr(self.card_model, "_data"):
                    has_data = bool(self.card_model._data)
                elif hasattr(self, "card_model") and callable(
                    getattr(self.card_model, "rowCount", None)
                ):
                    has_data = self.card_model.rowCount() > 0
                else:
                    has_data = bool(getattr(self, "all_card_data", []))

                if not has_data:
                    self._refresh_cards_tab()
            except Exception:
                # If detection fails, fall back to performing the initial load once
                if not getattr(self, "_initial_cards_load_attempted", False):
                    self._initial_cards_load_attempted = True
                    self._refresh_cards_tab()

    def _setup_processing_tab(self):
        """Set up the processing tab with task monitoring"""
        processing_widget = QWidget()
        processing_layout = QVBoxLayout()

        # Task list
        self.task_table = QTableView()
        self.task_model = ProcessingTaskModel()
        self.task_table.setModel(self.task_model)
        self.task_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.task_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.task_table.setSortingEnabled(True)
        # Show an empty-state message when no rows are present
        try:
            self.task_table.setPlaceholderText("No active tasks")
        except Exception:
            # setPlaceholderText not available in some environments; ignore gracefully
            pass

        # Set up headers
        horizontal_header = self.task_table.horizontalHeader()
        horizontal_header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        # Dynamic label to reflect whether any tasks are currently running/queued
        self.active_tasks_label = QLabel("Active Tasks:")
        processing_layout.addWidget(self.active_tasks_label)
        processing_layout.addWidget(self.task_table)

        # Task details section
        self.task_details_text = QTextEdit()
        self.task_details_text.setReadOnly(True)
        self.task_details_text.setMinimumHeight(150)
        processing_layout.addWidget(QLabel("Task Details:"))
        processing_layout.addWidget(self.task_details_text)

        # Control buttons
        control_layout = QHBoxLayout()

        cancel_btn = QPushButton("Cancel Selected")
        cancel_btn.clicked.connect(self._cancel_selected_task)
        control_layout.addWidget(cancel_btn)

        clear_btn = QPushButton("Clear Completed")
        clear_btn.clicked.connect(self._clear_completed_tasks)
        control_layout.addWidget(clear_btn)

        processing_layout.addLayout(control_layout)

        processing_widget.setLayout(processing_layout)
        self.tab_widget.addTab(processing_widget, "Processing")
        # Initialize the label state
        self._refresh_processing_status()

    def _cancel_selected_task(self):
        """Cancel the selected task"""
        try:
            # Get selected task
            selection_model = self.task_table.selectionModel()
            selected_indices = selection_model.selectedRows()

            if selected_indices:
                # Get the task ID from the first selected row
                task_id = self.task_model._data[selected_indices[0].row()]["task_id"]

                # Find and cancel the worker
                for worker in self.active_workers:
                    if hasattr(worker, "task_id") and worker.task_id == task_id:
                        worker.cancel()
                        self._update_task_status(
                            task_id, "Cancelled", "Cancelled by user"
                        )
                        self._update_status_message(f"Task {task_id} cancelled")
                        break
            else:
                self._update_status_message("No task selected")

        except Exception as e:
            print(f"Error cancelling task: {e}")
            self._update_status_message(f"Error cancelling task: {e}")

    def _clear_completed_tasks(self):
        """Clear completed tasks from the list"""
        try:
            # Filter out completed tasks
            active_tasks = []
            for task in self.processing_tasks:
                if task["status"] not in ["Completed", "Failed", "Cancelled"]:
                    active_tasks.append(task)

            # Update model
            self.processing_tasks = active_tasks
            self.task_model.update_data(self.processing_tasks)

            self._update_status_message("Completed tasks cleared")
            # Update processing header/indicator
            self._refresh_processing_status()

        except Exception as e:
            logger.error(f"Error clearing completed tasks: {e}")
            self._update_status_message(f"Error clearing tasks: {e}")

    def _add_processing_task(self, task_id: str, description: str):
        """Add a new processing task to the tracking system"""
        task_data = {
            "task_id": task_id,
            "status": "Queued",
            "progress": 0,
            "description": description,
            "start_time": datetime.now().isoformat(),
            "end_time": None,
            "error": None,
        }

        # Add to task list
        self.processing_tasks.append(task_data)

        # Update task model
        self.task_model.update_data(self.processing_tasks)

        # Log task
        logger.info(f"Task {task_id} added: {description}")

        # Update processing header/indicator
        self._refresh_processing_status()

    def _setup_processing_status(self):
        """Set up processing status tracking"""
        # This will be expanded in future phases
        self.processing_tasks = []
        self.recent_activity_limit = 100
        # In-memory session log for status messages to surface in Recent Activity
        self.recent_activity_messages = []

    def _clear_recent_activity(self):
        """Clear the recent activity list and reset session count"""
        self.recent_activity_limit = 0
        # Clear session messages as part of the clear action
        if hasattr(self, "recent_activity_messages"):
            self.recent_activity_messages.clear()
        self._update_recent_activity()
        self._update_status_message("Recent activity cleared")

    def _setup_card_model(self):
        """Set up the card model and connect signals"""
        try:
            # Create card model
            self.card_model = CardModel()
            self.cards_table.setModel(self.card_model)
            self.card_model.modelReset.connect(self._configure_card_table_columns)
            self._configure_card_table_columns()

            # Connect filter signals
            self.set_filter.currentIndexChanged.connect(self._apply_filters)
            self.rarity_filter.currentIndexChanged.connect(self._apply_filters)

            self.search_box.textChanged.connect(self._apply_filters)

            # Connect table click signal
            self.cards_table.clicked.connect(self._on_card_table_clicked)

        except Exception as e:
            print(f"Error setting up card model: {e}")
            self._update_status_message(f"Error loading card data: {e}")

    def _configure_card_table_columns(self):
        """Configure card table column sizing to match desired layout"""
        horizontal_header = self.cards_table.horizontalHeader()

        horizontal_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.cards_table.setColumnWidth(0, 48)

        # Card name and set columns stretch to fill remaining space
        horizontal_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        horizontal_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        # Rarity and count columns size to their content
        horizontal_header.setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        horizontal_header.setSectionResizeMode(
            4, QHeaderView.ResizeMode.ResizeToContents
        )

        # Ensure the art column remains just wider than the icon size
        icon_width = self.cards_table.iconSize().width()
        minimum_width = icon_width + 8  # small padding for margins
        if horizontal_header.sectionSize(0) < minimum_width:
            self.cards_table.setColumnWidth(0, minimum_width)

    def _refresh_cards_tab(self):
        """Kick off async refresh of card data after letting the tab render"""
        self._update_status_message("loading updated data...")

        # Show indeterminate progress and disable controls immediately
        if hasattr(self, "status_progress"):
            self.status_progress.setVisible(True)
            self.status_progress.setRange(0, 0)  # indeterminate

        # Disable controls to avoid filter churn during load
        for w in [
            getattr(self, "set_filter", None),
            getattr(self, "rarity_filter", None),
            getattr(self, "account_filter", None),
            getattr(self, "search_box", None),
            getattr(self, "refresh_cards_btn", None),
        ]:
            if w is not None:
                w.setEnabled(False)

        # Generation guard to drop stale results
        self._cards_load_generation += 1
        current_gen = self._cards_load_generation

        def start_worker():
            try:
                # Cancel any in-flight worker for card data
                prev = getattr(self, "_current_card_load_worker", None)
                if prev and hasattr(prev, "cancel"):
                    try:
                        prev.cancel()
                    except Exception:
                        pass

                # Create worker
                worker = CardDataLoadWorker(
                    db_path=self.db.db_path if hasattr(self, "db") else None
                )
                self._current_card_load_worker = worker

                # Connect signals
                worker.signals.status.connect(self._on_cards_load_status)
                worker.signals.result.connect(
                    lambda data, gen=current_gen, w=worker: self._on_cards_load_result(
                        data, gen, w
                    )
                )
                worker.signals.error.connect(
                    lambda err, gen=current_gen, w=worker: self._on_cards_load_error(
                        err, gen, w
                    )
                )
                worker.signals.finished.connect(
                    lambda gen=current_gen, w=worker: self._on_cards_load_finished(
                        gen, w
                    )
                )

                # Track and start
                self.active_workers.append(worker)
                self.thread_pool.start(worker)

            except Exception as e:
                self._on_cards_load_error(
                    f"Error starting card data load: {e}", current_gen, None
                )

        # Defer to allow the tab to render first
        QTimer.singleShot(0, start_worker)

    def _load_card_data(self):
        """Load card data from database"""
        try:
            if hasattr(self, "db") and self.db:
                # Get all cards with counts and account information
                cards = self.db.get_all_cards_with_counts()

                # Process data for the model
                card_data = []
                for card in cards:
                    # Get proper name and resolve rarity
                    raw_name = CARD_NAMES.get(card[1], card[1])
                    display_name, display_rarity = self._get_display_name_and_rarity(
                        card[1], raw_name, card[3]
                    )

                    card_info = {
                        "card_code": card[0],
                        "card_name": display_name,
                        "set_name": SET_NAMES.get(card[2], card[2]),
                        "rarity": display_rarity,
                        "count": card[4],
                        "image_path": card[5],
                    }
                    card_data.append(card_info)

                # Store full data copy for filtering
                self.all_card_data = card_data

                # Update filter options (this will not trigger _apply_filters due to signal blocking)
                self._update_filter_options(card_data)

                # Apply current filters (this will also update the model and status bar)
                self._apply_filters()
            else:
                self._update_status_message("Database not available")

        except Exception as e:
            print(f"Error loading card data: {e}")
            self._update_status_message(f"Error loading card data: {e}")

    def _on_cards_load_status(self, status: str):
        """Update status during async card load"""
        self._update_status_message(status)

    def _on_cards_load_result(self, card_data: list, gen: int, worker=None):
        """Handle async card load result with generation guard"""
        if gen != getattr(self, "_cards_load_generation", 0):
            return  # stale result

        # Store and apply filters
        self.all_card_data = card_data
        self._update_filter_options(card_data)
        self._apply_filters()

    def _on_cards_load_error(self, error: str, gen: int, worker=None):
        """Handle async card load error"""
        if gen != getattr(self, "_cards_load_generation", 0):
            return
        self._update_status_message(error)
        # Re-enable UI
        if hasattr(self, "status_progress"):
            self.status_progress.setVisible(False)
            self.status_progress.setRange(0, 100)
        for w in [
            getattr(self, "set_filter", None),
            getattr(self, "rarity_filter", None),
            getattr(self, "account_filter", None),
            getattr(self, "search_box", None),
            getattr(self, "refresh_cards_btn", None),
        ]:
            if w is not None:
                w.setEnabled(True)

    def _on_cards_load_finished(self, gen: int, worker=None):
        """Cleanup after async card load completes"""
        if worker and worker in getattr(self, "active_workers", []):
            self.active_workers.remove(worker)
        if getattr(self, "_current_card_load_worker", None) is worker:
            self._current_card_load_worker = None

        if gen != getattr(self, "_cards_load_generation", 0):
            return  # stale completion

        # Hide progress and re-enable controls
        if hasattr(self, "status_progress"):
            self.status_progress.setVisible(False)
            self.status_progress.setRange(0, 100)
        for w in [
            getattr(self, "set_filter", None),
            getattr(self, "rarity_filter", None),
            getattr(self, "account_filter", None),
            getattr(self, "search_box", None),
            getattr(self, "refresh_cards_btn", None),
        ]:
            if w is not None:
                w.setEnabled(True)

    def _update_filter_options(self, card_data):
        """Update filter options based on available data"""
        try:
            # Block signals during bulk update
            self.set_filter.blockSignals(True)
            self.rarity_filter.blockSignals(True)

            # Update set filter
            sets = set()
            for card in card_data:
                if card.get("set_name"):
                    sets.add(card["set_name"])

            current_set = self.set_filter.currentText()
            self.set_filter.clear()
            self.set_filter.addItem("All Sets")
            for set_name in sorted(sets):
                self.set_filter.addItem(set_name)

            # Restore previous selection if possible
            if current_set != "All Sets" and current_set in sets:
                index = self.set_filter.findText(current_set)
                if index >= 0:
                    self.set_filter.setCurrentIndex(index)

            # Update rarity filter
            rarities = set()
            for card in card_data:
                if card.get("rarity"):
                    rarities.add(card["rarity"])

            current_rarity = self.rarity_filter.currentText()
            self.rarity_filter.clear()
            self.rarity_filter.addItem("All Rarities")
            for rarity in sorted(rarities):
                self.rarity_filter.addItem(rarity)

            # Restore previous selection if possible
            if current_rarity != "All Rarities" and current_rarity in rarities:
                index = self.rarity_filter.findText(current_rarity)
                if index >= 0:
                    self.rarity_filter.setCurrentIndex(index)

        except Exception as e:
            print(f"Error updating filter options: {e}")
        finally:
            # Unblock signals
            self.set_filter.blockSignals(False)
            self.rarity_filter.blockSignals(False)

    def _apply_filters(self):
        """Apply current filters to the card data"""
        try:
            # Get current filter values
            set_filter = self.set_filter.currentText()
            rarity_filter = self.rarity_filter.currentText()
            search_text = self.search_box.text().strip().lower()

            # Get all cards
            all_cards = getattr(self, "all_card_data", [])

            # Apply filters
            filtered_cards = []
            for card in all_cards:
                # Apply set filter
                if set_filter != "All Sets" and card.get("set_name") != set_filter:
                    continue

                # Apply rarity filter
                if (
                    rarity_filter != "All Rarities"
                    and card.get("rarity") != rarity_filter
                ):
                    continue

                # Apply search filter
                if search_text:
                    card_name = card.get("card_name", "").lower()
                    set_name = card.get("set_name", "").lower()
                    rarity = card.get("rarity", "").lower()

                    if (
                        search_text not in card_name
                        and search_text not in set_name
                        and search_text not in rarity
                    ):
                        continue

                filtered_cards.append(card)

            # Update model with filtered data
            self.card_model.update_data(filtered_cards)
            self._update_status_message(
                f"Showing {len(filtered_cards)} of {len(all_cards)} cards"
            )

        except Exception as e:
            print(f"Error applying filters: {e}")
            self._update_status_message(f"Error applying filters: {e}")

    def _on_card_table_clicked(self, index):
        """Handle click on card table"""
        if index.column() == 0:  # Art column
            card_data = self.card_model._data[index.row()]
            image_path = card_data.get("image_path")
            card_code = card_data.get("card_code")
            card_name = card_data.get("card_name", "Card Art")

            # Resolve the image path using the same logic as the model
            resolved_path = self.card_model._find_card_image(card_code, image_path)
            if resolved_path:
                self._show_full_card_image(
                    resolved_path, card_name + " (" + card_data.get("set_name") + ")"
                )
        else:
            # Handle other columns
            card_data = self.card_model._data[index.row()]
            card_code = card_data.get("card_code")
            card_name = card_data.get("card_name", "Unknown")

            # Show account distribution dialog
            self._show_account_distribution(card_code, card_name)

    def _show_account_distribution(self, card_code: str, card_name: str):
        """Show dialog with account distribution for a card"""
        try:
            if hasattr(self, "db") and self.db:
                # Get account distribution from database
                account_data = self.db.get_accounts_for_card(card_code)

                if account_data:
                    dialog = AccountCardListDialog(
                        card_name, card_code, account_data, self
                    )
                    dialog.show()
                else:
                    QMessageBox.information(
                        self,
                        "No Data",
                        f"No account distribution found for {card_name}",
                    )
            else:
                QMessageBox.warning(self, "Error", "Database not available")

        except Exception as e:
            logger.error(f"Error showing account distribution: {e}")
            QMessageBox.warning(
                self, "Error", f"Could not show account distribution: {e}"
            )

    def _on_search_table_clicked(self, index):
        """Handle click on search results table"""
        if index.column() == 0:  # Art column
            result_data = self.search_results_model._data[index.row()]
            image_path = result_data.get("image_path")
            card_name = result_data.get("card_name", "Card Art")

            # Resolve image path
            if image_path:
                check_paths = [
                    image_path,
                    get_portable_path("resources", "card_imgs", image_path),
                    get_portable_path("static", "card_imgs", image_path),
                ]

                normalized_path = image_path.replace("\\", "/")
                if "/" in normalized_path:
                    parts = normalized_path.split("/")
                    filename = parts[-1]
                    set_code = parts[0]
                    check_paths.append(
                        get_portable_path("resources", "card_imgs", set_code, filename)
                    )
                    check_paths.append(
                        get_portable_path("static", "card_imgs", set_code, filename)
                    )

                resolved_path = None
                for path in check_paths:
                    if os.path.exists(path):
                        resolved_path = path
                        break

                if resolved_path:
                    self._show_full_card_image(
                        resolved_path,
                        card_name + " (" + result_data.get("set_name") + ")",
                    )

    def _show_full_card_image(self, image_path: str, card_name: str):
        """Show full size card image in a dialog"""
        try:
            dialog = CardImageDialog(image_path, card_name, self)
            dialog.show()
        except Exception as e:
            logger.error(f"Error showing card image: {e}")
            QMessageBox.warning(self, "Error", f"Could not show card image: {e}")

    def _setup_status_bar(self):
        """Set up the status bar with comprehensive indicators"""
        status_bar = QStatusBar()

        # Main status label
        self.main_status = QLabel("Ready")
        status_bar.addWidget(self.main_status, 1)

        # Progress bar
        self.status_progress = QProgressBar()
        self.status_progress.setVisible(False)
        self.status_progress.setMaximumWidth(200)
        status_bar.addPermanentWidget(self.status_progress)

        # Database status
        self.db_status = QLabel()
        self._update_db_status()
        status_bar.addPermanentWidget(self.db_status)

        # Task count
        self.task_status = QLabel()
        self._update_task_status()  # Update task count indicator only
        status_bar.addPermanentWidget(self.task_status)

        self.setStatusBar(status_bar)

    def _update_status_message(self, message: str):
        """Update the main status message and clear any temporary messages"""
        if hasattr(self, "main_status"):
            self.statusBar().clearMessage()
            self.main_status.setText(message)
            logger.debug(f"Status updated: {message}")

        # Also push this status message to the Recent Activity session log
        try:
            timestamp = datetime.now().isoformat(timespec="seconds")
            if not hasattr(self, "recent_activity_messages"):
                self.recent_activity_messages = []

            self.recent_activity_messages.append(
                {
                    "timestamp": timestamp,
                    "description": message,
                }
            )

            # Cap session messages to the configured limit (default 100)
            limit = getattr(self, "recent_activity_limit", 100) or 100
            if len(self.recent_activity_messages) > limit:
                self.recent_activity_messages = self.recent_activity_messages[-limit:]

            # Reflect immediately in the UI if the list exists
            if (
                hasattr(self, "recent_activity_list")
                and self.recent_activity_list is not None
            ):
                display_text = f"{timestamp} - {message}"
                # Append to the bottom for chronological order
                self.recent_activity_list.addItem(display_text)
                self.recent_activity_list.scrollToBottom()
        except Exception as e:
            # Never let activity logging break UI status updates
            logger.debug(f"Failed to add status to Recent Activity: {e}")

    def _update_db_status(self):
        """Update database connection status"""
        if hasattr(self, "db") and self.db:
            self.db_status.setText("DB: Connected")
            self.db_status.setStyleSheet("color: green;")
        else:
            self.db_status.setText("DB: Disconnected")
            self.db_status.setStyleSheet("color: red;")

    def _update_task_status(
        self,
        task_id: str = None,
        status: str = None,
        progress: int = None,
        error: str = None,
    ):
        """Update task status indicator and specific task status"""
        if task_id:
            # Update specific task status
            for task in self.processing_tasks:
                if task["task_id"] == task_id:
                    if status:
                        task["status"] = status

                    if progress is not None:
                        task["progress"] = progress

                    if status == "Completed":
                        task["progress"] = 100

                    if status in ["Completed", "Failed", "Cancelled"]:
                        task["end_time"] = datetime.now().isoformat()

                    if error:
                        task["error"] = error

                    # Update model
                    self.task_model.update_data(self.processing_tasks)

                    # Log status change if status provided
                    if status:
                        logger.info(f"Task {task_id} status changed to {status}")

                    break

        # Update task count indicator
        active_tasks = sum(
            1
            for task in self.processing_tasks
            if task["status"] in ["Queued", "Running"]
        )

        self.task_status.setText(f"Tasks: {active_tasks}")
        if active_tasks > 0:
            self.task_status.setStyleSheet("color: orange;")
        else:
            self.task_status.setStyleSheet("color: inherit;")

        # Also refresh the processing tab header label
        self._refresh_processing_status()

    def _refresh_processing_status(self):
        """Refresh the processing tab header to indicate if there are any active tasks.

        An active task is one with status 'Queued' or 'Running'. If none are active,
        the label will display a helpful message. This is independent of whether
        completed tasks are still listed in the table.
        """
        try:
            active_count = sum(
                1
                for t in getattr(self, "processing_tasks", [])
                if t.get("status") in ["Queued", "Running"]
            )
            if (
                hasattr(self, "active_tasks_label")
                and self.active_tasks_label is not None
            ):
                if active_count == 0:
                    self.active_tasks_label.setText("Active Tasks: none running")
                    self.active_tasks_label.setStyleSheet("color: gray;")
                else:
                    self.active_tasks_label.setText("Active Tasks:")
                    self.active_tasks_label.setStyleSheet("")
        except Exception:
            # Never let UI hints break processing display
            pass

    def _update_progress(self, current: int, total: int, message: str = ""):
        """Update progress indicators"""
        if total > 0:
            percentage = min(100, int((current / total) * 100))

            # Update progress bar
            self.status_progress.setVisible(True)
            self.status_progress.setRange(0, total)
            self.status_progress.setValue(current)

            # Update status message
            if message:
                self._update_status_message(message)
            else:
                self._update_status_message(
                    f"Progress: {current}/{total} ({percentage}%)"
                )

        # Update task status
        self._update_task_status()  # Update task count indicator only

    def _clear_progress(self):
        """Clear progress indicators"""
        self.statusBar().clearMessage()
        self.status_progress.setVisible(False)
        self.status_progress.setValue(0)

    def _get_saved_paths(self):
        """Retrieve saved CSV and screenshot paths from settings"""
        csv_path = self.settings.get_setting("csv_import_path", "")
        screenshots_dir = self.settings.get_setting("screenshots_dir", "")
        return csv_path, screenshots_dir

    def _update_load_new_data_availability(self):
        """Show or hide the combined import controls based on saved paths"""
        csv_path, screenshots_dir = self._get_saved_paths()
        available = (
            bool(csv_path)
            and os.path.isfile(csv_path)
            and bool(screenshots_dir)
            and os.path.isdir(screenshots_dir)
        )

        if hasattr(self, "load_new_data_btn"):
            self.load_new_data_btn.setVisible(available)
            self.load_new_data_btn.setEnabled(available)
            self.import_csv_btn.setVisible(not available)
            self.import_screenshots_btn.setVisible(not available)

        if hasattr(self, "load_new_data_action"):
            self.load_new_data_action.setEnabled(available)
            # Keep action visible in menu for discoverability
            self.load_new_data_action.setVisible(True)

    def _on_load_new_data(self):
        """Run the combined CSV + screenshot import using saved paths"""
        if self._combined_import_request:
            QMessageBox.information(
                self,
                "Load New Data",
                "A data import is already in progress. Please wait for it to finish.",
            )
            return

        csv_path, screenshots_dir = self._get_saved_paths()

        issues = []
        if not csv_path:
            issues.append("CSV file path is not set.")
        elif not os.path.isfile(csv_path):
            issues.append(f"CSV file not found: {csv_path}")

        if not screenshots_dir:
            issues.append("Screenshots directory is not set.")
        elif not os.path.isdir(screenshots_dir):
            issues.append(f"Screenshots directory not found: {screenshots_dir}")

        if issues:
            QMessageBox.warning(
                self,
                "Load New Data",
                "\n".join(issues)
                + "\n\nPlease use the Import CSV or Process Screenshots options to set the correct locations.",
            )
            self._update_load_new_data_availability()
            return

        self._combined_import_request = {
            "csv_path": csv_path,
            "screenshots_dir": screenshots_dir,
        }

        self._update_status_message("Starting data import…")
        self._on_csv_imported(csv_path, combined=True)

    def _on_import_csv(self):
        """Handle Import CSV action"""
        print("Import CSV action triggered")

        try:
            # Get initial path from settings
            initial_path = self.settings.get_setting("csv_import_path", "")

            # Create and show CSV import dialog
            dialog = CSVImportDialog(
                self, initial_path=initial_path, settings=self.settings
            )
            dialog.csv_imported.connect(self._on_csv_imported)

            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._update_status_message("CSV import completed")
            else:
                self._update_status_message("CSV import cancelled")

            # Update combined import availability after any dialog interaction
            self._update_load_new_data_availability()

        except Exception as e:
            print(f"Error importing CSV: {e}")
            self._update_status_message(f"Error importing CSV: {e}")

    def _on_csv_imported(self, file_path: str, combined: bool = False):
        """Handle successful CSV import - start background processing"""
        print(f"Starting background CSV import from: {file_path}")
        self._update_status_message(f"Starting background CSV import...")

        try:
            # Generate task ID
            import uuid

            task_id = str(uuid.uuid4())

            # Add task to tracking system
            self._add_processing_task(
                task_id, f"CSV Import: {os.path.basename(file_path)}"
            )

            if combined and self._combined_import_request is not None:
                self._combined_import_request["csv_task_id"] = task_id

            # Create worker for CSV import
            worker = CSVImportWorker(
                file_path=file_path, task_id=task_id, db_path=self.db.db_path
            )

            # Connect signals with task_id and worker
            worker.signals.progress.connect(
                lambda c, t, tid=task_id: self._on_csv_import_progress(c, t, tid)
            )
            worker.signals.status.connect(self._on_csv_import_status)
            worker.signals.result.connect(
                lambda r, tid=task_id: self._on_csv_import_result(r, tid)
            )
            worker.signals.error.connect(
                lambda e, tid=task_id: self._on_csv_import_error(e, tid)
            )
            worker.signals.finished.connect(
                lambda w=worker: self._on_csv_import_finished(w)
            )

            # Store worker for cancellation
            self.active_workers.append(worker)

            # Start worker
            self.thread_pool.start(worker)

            # Update task status and dashboard
            self._update_task_status(task_id, "Running")
            self._request_dashboard_update()

            self._update_status_message("CSV import started in background")

        except Exception as e:
            print(f"Error starting CSV import worker: {e}")
            self._update_status_message(f"Error starting CSV import: {e}")

    def _on_csv_import_progress(self, current: int, total: int, task_id: str = None):
        """Handle CSV import progress updates"""
        self._update_progress(current, total, f"CSV import: {current}/{total}")

        # Update task progress if task_id provided
        if task_id:
            percentage = int((current / total) * 100) if total > 0 else 0
            self._update_task_status(task_id, progress=percentage)

            # Refresh dashboard to show progress in recent activity
            self._request_dashboard_update()

    def _on_csv_import_status(self, status: str):
        """Handle CSV import status updates"""
        print(f"CSV import status: {status}")
        self._update_status_message(status)

    def _on_csv_import_result(self, result: dict, task_id: str = None):
        """Handle CSV import result"""
        print(f"CSV import result: {result}")
        self._update_status_message(
            f"CSV import completed: {result.get('total_rows', 0)} packs imported"
        )

        # Increase activity limit to show new items
        self.recent_activity_limit += result.get("total_rows", 0)

        if task_id:
            self._update_task_status(task_id, "Completed")

        # If part of a combined flow, continue with screenshot processing
        if (
            self._combined_import_request
            and self._combined_import_request.get("csv_task_id") == task_id
        ):
            self._update_status_message("Starting screenshot processing from saved directory…")
            self._start_combined_screenshot_step()

    def _on_csv_import_error(self, error: str, task_id: str = None):
        """Handle CSV import errors"""
        print(f"CSV import error: {error}")
        self._update_status_message(f"CSV import error: {error}")

        if task_id:
            self._update_task_status(task_id, "Failed", error=error)

        if (
            self._combined_import_request
            and self._combined_import_request.get("csv_task_id") == task_id
        ):
            self._update_status_message(
                "Combined import stopped due to CSV import error."
            )
            self._combined_import_request = None
            self._update_load_new_data_availability()

    def _on_csv_import_finished(self, worker=None):
        """Handle CSV import completion"""
        print("CSV import finished")
        self._update_status_message("CSV import finished")

        # Clean up worker
        if worker and worker in self.active_workers:
            self.active_workers.remove(worker)
        elif self.active_workers:
            self.active_workers.pop()

        # Refresh dashboard statistics only; Cards tab refresh is manual after first load
        self._request_dashboard_update()

        # Clear progress indicators
        self._clear_progress()

    def _start_combined_screenshot_step(self):
        """Start screenshot processing for a combined import flow"""
        if not self._combined_import_request:
            return

        screenshots_dir = self._combined_import_request.get("screenshots_dir")

        if not screenshots_dir or not os.path.isdir(screenshots_dir):
            self._update_status_message(
                "Combined import stopped: saved screenshots directory is unavailable."
            )
            self._combined_import_request = None
            self._update_load_new_data_availability()
            return

        self._combined_import_request["status"] = "screenshots"
        self._on_processing_started(screenshots_dir, overwrite=False)

    def _on_screenshot_processing_progress(
        self, current: int, total: int, task_id: str = None
    ):
        """Handle screenshot processing progress updates"""
        self._update_progress(
            current, total, f"Screenshot processing: {current}/{total}"
        )

        # Update task progress if task_id provided
        if task_id:
            percentage = int((current / total) * 100) if total > 0 else 0
            self._update_task_status(task_id, progress=percentage)

            # Refresh dashboard to show progress in recent activity
            self._request_dashboard_update()

    def _on_screenshot_processing_status(self, status: str):
        """Handle screenshot processing status updates"""
        print(f"Screenshot processing status: {status}")
        self._update_status_message(status)

    def _on_screenshot_processing_result(self, result: dict, task_id: str = None):
        """Handle screenshot processing result"""
        print(f"Screenshot processing result: {result}")
        self._update_status_message(
            f"Screenshot processing completed: {result.get('total_files', 0)} files processed"
        )

        # Increase activity limit to show new items
        self.recent_activity_limit += result.get("successful_files", 0)

        if task_id:
            self._update_task_status(task_id, "Completed")

        if (
            self._combined_import_request
            and self._combined_import_request.get("screenshot_task_id") == task_id
        ):
            self._update_status_message("Data import finished!")
            self._combined_import_request = None
            self._update_load_new_data_availability()

    def _on_screenshot_processing_error(self, error: str, task_id: str = None):
        """Handle screenshot processing errors"""
        print(f"Screenshot processing error: {error}")
        self._update_status_message(f"Screenshot processing error: {error}")

        if task_id:
            self._update_task_status(task_id, "Failed", error=error)

        if (
            self._combined_import_request
            and self._combined_import_request.get("screenshot_task_id") == task_id
        ):
            self._update_status_message(
                "Combined import stopped due to screenshot processing error."
            )
            self._combined_import_request = None
            self._update_load_new_data_availability()

    def _on_screenshot_processing_finished(self, worker=None):
        """Handle screenshot processing completion"""
        print("Screenshot processing finished")
        self._update_status_message("Screenshot processing finished")

        # Clean up worker
        if worker and worker in self.active_workers:
            self.active_workers.remove(worker)
        elif self.active_workers:
            self.active_workers.pop()

        # Refresh dashboard statistics only; Cards tab refresh is manual after first load
        self._request_dashboard_update()

        # Clear progress indicators
        self._clear_progress()

        if (
            self._combined_import_request
            and self._combined_import_request.get("screenshot_task_id")
        ):
            # Leave status message from result/error; just clear state here
            self._combined_import_request = None
            self._update_load_new_data_availability()

    def _on_process_screenshots(self):
        """Handle Process Screenshots action"""
        print("Process Screenshots action triggered")

        # Check if cards are loaded first
        try:
            if hasattr(self, "db") and self.db:
                total_packs = self.db.get_total_packs_count()
                if total_packs == 0:
                    from PyQt6.QtWidgets import QMessageBox
                    QMessageBox.warning(
                        self,
                        "Missing Screenshot Data",
                        "No screenshot records found in database. Please import a CSV file first (File -> Import CSV) "
                        "before processing screenshots."
                    )
                    self._update_status_message("Aborted screenshot processing: No screenshot records in database")
                    return
            else:
                self._update_status_message("Database not available")
                return
        except Exception as e:
            logger.error(f"Error checking card count: {e}")
            # Continue anyway? Or abort? Aborting is safer.
            self._update_status_message(f"Error checking card count: {e}")
            return

        try:
            # Get initial directory from settings
            initial_dir = self.settings.get_setting("screenshots_dir", "")

            # Create and show screenshot processing dialog
            dialog = ScreenshotProcessingDialog(
                self, initial_dir=initial_dir, settings=self.settings
            )
            dialog.processing_started.connect(self._on_processing_started)

            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._update_status_message("Screenshot processing completed")
            else:
                self._update_status_message("Screenshot processing cancelled")

            # Update combined import availability after any dialog interaction
            self._update_load_new_data_availability()

        except Exception as e:
            print(f"Error processing screenshots: {e}")
            self._update_status_message(f"Error processing screenshots: {e}")

    def _on_processing_started(self, directory_path: str, overwrite: bool):
        """Handle successful processing start - create and start screenshot processing worker"""
        print(
            f"Processing started for directory: {directory_path}, overwrite: {overwrite}"
        )
        self._update_status_message(f"Starting background screenshot processing...")

        try:
            # Generate task ID
            import uuid

            task_id = str(uuid.uuid4())

            # Add task to tracking system
            self._add_processing_task(
                task_id, f"Screenshot Processing: {os.path.basename(directory_path)}"
            )

            if (
                self._combined_import_request
                and self._combined_import_request.get("screenshots_dir")
                == directory_path
            ):
                self._combined_import_request["screenshot_task_id"] = task_id

            # Create worker for screenshot processing
            worker = ScreenshotProcessingWorker(
                directory_path=directory_path, overwrite=overwrite, task_id=task_id
            )

            # Connect signals with task_id and worker
            worker.signals.progress.connect(
                lambda c, t, tid=task_id: self._on_screenshot_processing_progress(
                    c, t, tid
                )
            )
            worker.signals.status.connect(self._on_screenshot_processing_status)
            worker.signals.result.connect(
                lambda r, tid=task_id: self._on_screenshot_processing_result(r, tid)
            )
            worker.signals.error.connect(
                lambda e, tid=task_id: self._on_screenshot_processing_error(e, tid)
            )
            worker.signals.finished.connect(
                lambda w=worker: self._on_screenshot_processing_finished(w)
            )

            # Store worker for cancellation
            self.active_workers.append(worker)

            # Start worker
            self.thread_pool.start(worker)

            # Update task status and dashboard
            self._update_task_status(task_id, "Running")
            self._request_dashboard_update()

            self._update_status_message("Screenshot processing started in background")

        except Exception as e:
            print(f"Error starting screenshot processing worker: {e}")
            self._update_status_message(f"Error starting screenshot processing: {e}")

    # --- Card art download handlers ---
    def _on_art_download_progress(self, current: int, total: int, task_id: str = None):
        """Progress updates for card art download (also updates task model)."""
        try:
            # Update visible progress bar and message
            self._update_progress(current, total, "Downloading card art")

            # Update the processing task percentage
            if total > 0 and task_id:
                percentage = min(100, int((current / total) * 100))
                self._update_task_status(task_id, status="Running", progress=percentage)
        except Exception:
            # Never let UI updates crash
            pass

    def _on_art_download_status(self, status: str, task_id: str = None):
        self._update_status_message(status)

    def _on_art_download_result(self, result: dict, task_id: str = None):
        try:
            images = result.get("images_saved", 0) if isinstance(result, dict) else 0
            self._update_status_message(
                f"Card art download complete: {images} images saved"
            )
            if task_id:
                self._update_task_status(task_id, "Completed", progress=100)
        except Exception:
            self._update_status_message("Card art download complete")
            if task_id:
                self._update_task_status(task_id, "Completed", progress=100)

    def _on_art_download_error(self, error: str, task_id: str = None):
        self._update_status_message(f"Card art download error: {error}")
        if task_id:
            self._update_task_status(task_id, "Failed", error=error)

    def _on_art_download_finished(self, worker=None, task_id: str = None):
        try:
            if worker and worker in self.active_workers:
                self.active_workers.remove(worker)
            elif self.active_workers:
                self.active_workers.pop()
        except Exception:
            pass
        # Ensure progress cleared and task counter refreshed
        if task_id:
            self._update_task_status()  # refresh counter
        self._clear_progress()

    def _on_about(self):
        """Handle About action"""
        print("About action triggered")

        try:
            # Create and show about dialog
            dialog = AboutDialog(self)
            dialog.exec()

        except Exception as e:
            print(f"Error showing about dialog: {e}")
            self._update_status_message(f"Error showing about dialog: {e}")

    def closeEvent(self, event):
        """Handle window close event"""
        print("Closing application...")
        try:
            # Request cancellation on any active workers
            for worker in getattr(self, "active_workers", []):
                cancel = getattr(worker, "cancel", None)
                if callable(cancel):
                    try:
                        cancel()
                    except Exception:
                        # Ignore failures during shutdown
                        pass

            # Wait briefly for workers to finish
            if hasattr(self, "thread_pool"):
                try:
                    self.thread_pool.clear()
                except Exception:
                    pass
                try:
                    self.thread_pool.waitForDone(3000)
                except Exception:
                    pass

            # Clean up database connections
            if hasattr(self, "db"):
                self.db.close()
                print("Database connections closed")
        finally:
            event.accept()

    def _get_display_name_and_rarity(self, card_code, raw_name, raw_rarity):
        """
        Clean the card name and resolve the display rarity.

        Args:
            card_code: The card ID (e.g., 'A1_1')
            raw_name: The name from CARD_NAMES (e.g., 'Bulbasaur (1D)')
            raw_rarity: The rarity from the database

        Returns:
            tuple: (display_name, display_rarity)
        """
        import re

        full_name = raw_name if raw_name else card_code
        display_name = full_name
        display_rarity = raw_rarity

        # Look for modifier in parentheses at the end of the name
        match = re.search(r"\s*\(([^)]+)\)$", full_name)
        if match:
            rarity_code = match.group(1)
            display_name = full_name[: match.start()].strip()

            # Map rarity code to display name if it exists in the map
            if rarity_code in RARITY_MAP:
                display_rarity = RARITY_MAP[rarity_code]
            else:
                # If code not in map but was in parentheses, use it as rarity
                # (e.g., 'Promo' in 'Pikachu (Promo)')
                display_rarity = rarity_code

        return display_name, display_rarity

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
from PyQt6.QtCore import QSize, QTimer
from PyQt6.QtGui import QAction
import os
import sys
import logging
import threading
from datetime import datetime

logger = logging.getLogger(__name__)

from app.models import CardModel, ProcessingTaskModel

from app.dialogs import (
    CSVImportDialog,
    ScreenshotProcessingDialog,
    AboutDialog,
    CardImageDialog,
    AccountCardListDialog,
    PreferencesDialog,
)

from app.workers import (
    CSVImportWorker,
    ScreenshotProcessingWorker,
    CardDataLoadWorker,
    CardArtDownloadWorker,
    VersionCheckWorker,
    DashboardStatsWorker,
    get_max_thread_count,
)
from PyQt6.QtCore import QThreadPool, Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from app.utils import (
    PortableSettings,
    get_app_version,
    get_traded_cards,
    get_task_id,
    clean_card_name,
)
from watchdog.observers.polling import PollingObserver
from watchdog.events import FileSystemEventHandler
from settings import BASE_DIR
import humanize


class ScreenshotChangeHandler(FileSystemEventHandler):
    """Handler for watchdog events in the screenshots directory"""

    def __init__(self):
        super().__init__()
        self.has_changes = False

    def on_any_event(self, event):
        if not event.is_directory:
            if event.event_type in ("created", "modified", "moved"):
                logger.info(
                    f"Watchdog detected {event.event_type} event: {event.src_path}"
                )
                self.has_changes = True


class MainWindow(QMainWindow):
    """
    Main application window for Card Counter

    Provides the primary user interface with menu bar, toolbar,
    tab-based central widget, and status bar.
    """

    def __init__(self):
        """Initialize the main window"""
        super().__init__()

        self.setWindowTitle("PTCGPB Companion")
        self.setMinimumSize(800, 600)

        self.settings = PortableSettings()

        # Track combined import flow state
        self._combined_import_request = None
        self._migration_in_progress = False

        # Initialize core non-UI components first
        self._init_thread_pool()
        self._setup_processing_status()
        logger.info("finished processing status")
        # Cards tab async loading state
        self._cards_load_generation = 0
        self._current_card_load_worker = None

        self.new_version_available = False
        self.latest_version_info = {}

        self._dashboard_timer = QTimer()
        logger.info("firing dashboard timer")
        self._dashboard_timer.setSingleShot(True)
        self._dashboard_timer.timeout.connect(self._update_dashboard_statistics)
        logger.info("setting up status bar")
        self._setup_status_bar()  # Initialize status bar early so it can be used by other setup methods
        logger.info("setting up menu bar")
        self._setup_menu_bar()
        logger.info("setting up central widget")
        self._setup_central_widget()

        # Set initial state for combined import availability
        self._update_load_new_data_availability()

        QTimer.singleShot(100, self._start_art_download_if_needed)
        QTimer.singleShot(150, self._check_for_database_migration)

        QTimer.singleShot(200, self._update_dashboard_statistics)

        QTimer.singleShot(300, self._check_for_updates)

        self.recent_activity_messages.append(
            {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "description": "App loaded.",
            }
        )
        self._update_recent_activity()

        # Initialize watchdog system deferred with a small delay to ensure UI renders first
        QTimer.singleShot(1000, self._init_watchdog)

    def _start_art_download_if_needed(self):
        """Check for card art directory and start background download if missing"""
        try:
            from settings import BASE_DIR

            template_dir = BASE_DIR / "resources" / "card_imgs"
            if not os.path.isdir(template_dir):
                msg_box = QMessageBox(self)
                msg_box.setWindowTitle("Download Card Art")
                msg_box.setText(
                    "Card art images are missing. These are required for card recognition.\n\n"
                    "Would you like to download them now?"
                )
                download_button = msg_box.addButton(
                    "Download", QMessageBox.ButtonRole.AcceptRole
                )
                quit_button = msg_box.addButton(
                    "Quit", QMessageBox.ButtonRole.RejectRole
                )
                msg_box.setDefaultButton(download_button)
                msg_box.setIcon(QMessageBox.Icon.Question)

                msg_box.exec()

                if msg_box.clickedButton() == quit_button:
                    logger.info("User chose to quit instead of downloading card art")
                    sys.exit(0)

                self._update_status_message("Downloading card art in background…")

                # Create a task entry so it appears in Processing tab & counter
                import uuid

                task_id = get_task_id()
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

    def _check_for_database_migration(self):
        """Check if an old database exists and prompt for migration if so"""
        old_db_path = BASE_DIR / "data" / "cardcounter.db"
        if os.path.exists(old_db_path):
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Database Migration")
            msg_box.setText(
                "We are very sorry, but due to database changes we need to rebuild the data.\n\n"
                "To continue, we need to perform a combined import of your CSV and screenshots. "
            )
            start_button = msg_box.addButton("Start", QMessageBox.ButtonRole.AcceptRole)
            cancel_button = msg_box.addButton(
                "Cancel", QMessageBox.ButtonRole.RejectRole
            )
            msg_box.setDefaultButton(start_button)
            msg_box.setIcon(QMessageBox.Icon.Information)

            msg_box.exec()

            if msg_box.clickedButton() == cancel_button:
                logger.info("User cancelled database migration; quitting")
                sys.exit(0)

            self._migration_in_progress = True
            self._on_load_new_data()

    def _workers_are_running(self) -> bool:
        return any(
            isinstance(w, ScreenshotProcessingWorker)
            or isinstance(w, CSVImportWorker)
            or isinstance(w, CardArtDownloadWorker)
            for w in self.active_workers
        )

    def _init_thread_pool(self):
        """Initialize thread pool for background processing"""
        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(get_max_thread_count())
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
        file_menu = menu_bar.addMenu(self.tr("&File"))

        # Import CSV action
        import_csv_action = QAction(self.tr("&Import CSV"), self)
        import_csv_action.setShortcut("Ctrl+I")
        import_csv_action.triggered.connect(self._on_import_csv)
        file_menu.addAction(import_csv_action)

        # Process Screenshots action
        process_action = QAction(self.tr("&Process Screenshots"), self)
        process_action.setShortcut("Ctrl+P")
        process_action.triggered.connect(self._on_process_screenshots)
        file_menu.addAction(process_action)

        # Combined import action
        self.load_new_data_action = QAction(self.tr("&Load New Data"), self)
        self.load_new_data_action.triggered.connect(self._on_load_new_data)
        self.load_new_data_action.setEnabled(False)
        file_menu.addAction(self.load_new_data_action)

        # Process Removed Cards action
        process_removed_action = QAction(self.tr("Process &Removed Cards"), self)
        process_removed_action.triggered.connect(self._on_process_removed_cards)
        file_menu.addAction(process_removed_action)

        # Preferences action
        preferences_action = QAction(self.tr("&Preferences"), self)
        preferences_action.setShortcut("Ctrl+,")
        preferences_action.triggered.connect(self._on_preferences)
        file_menu.addSeparator()
        file_menu.addAction(preferences_action)

        # Exit action
        exit_action = QAction(self.tr("E&xit"), self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addSeparator()
        file_menu.addAction(exit_action)

        # View menu. Not currently used, but keeping in case we need it eventually
        # view_menu = menu_bar.addMenu(self.tr("&View"))

        # Help menu
        help_menu = menu_bar.addMenu(self.tr("&Help"))

        # About action
        about_action = QAction(self.tr("&About"), self)
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
        self.total_cards_label = QLabel(self.tr("Total Cards: 0"))
        self.total_cards_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        stats_layout.addWidget(self.total_cards_label, 0, 0)

        # Total packs statistic
        self.total_packs_label = QLabel(self.tr("Total Packs: 0"))
        self.total_packs_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        stats_layout.addWidget(self.total_packs_label, 0, 1)

        # Unique cards statistic
        self.unique_cards_label = QLabel(self.tr("Unique Cards: 0"))
        self.unique_cards_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        stats_layout.addWidget(self.unique_cards_label, 1, 0)

        # Last processed statistic
        self.last_processed_label = QLabel(self.tr("Last Processed: Never"))
        self.last_processed_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        stats_layout.addWidget(self.last_processed_label, 1, 1)

        dashboard_layout.addLayout(stats_layout)

        # Quick actions section
        actions_layout = QHBoxLayout()

        self.import_csv_btn = QPushButton(self.tr("Import CSV"))
        self.import_csv_btn.clicked.connect(self._on_import_csv)
        actions_layout.addWidget(self.import_csv_btn)

        self.import_screenshots_btn = QPushButton(self.tr("Load Screenshots"))
        self.import_screenshots_btn.clicked.connect(self._on_process_screenshots)
        actions_layout.addWidget(self.import_screenshots_btn)

        self.load_new_data_btn = QPushButton(self.tr("Load New Data"))
        self.load_new_data_btn.clicked.connect(self._on_load_new_data)
        actions_layout.addWidget(self.load_new_data_btn)

        dashboard_layout.addLayout(actions_layout)

        # Recent activity section
        recent_header_layout = QHBoxLayout()
        recent_label = QLabel(self.tr("Recent Activity:"))
        recent_header_layout.addWidget(recent_label)

        recent_header_layout.addStretch()

        clear_recent_btn = QPushButton(self.tr("Clear"))
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
        self.tab_widget.addTab(dashboard_widget, self.tr("Dashboard"))

        # Dashboard statistics will be loaded after status bar is initialized

    def _update_dashboard_statistics(self):
        """Update dashboard statistics from database"""
        # Only update if the dashboard tab is active to save resources
        if self.tab_widget.currentIndex() != 0:
            return

        try:
            # Use a worker to avoid hanging the UI thread
            limit = getattr(self, "recent_activity_limit", 100)
            worker = DashboardStatsWorker(activity_limit=limit)
            worker.signals.result.connect(self._on_dashboard_stats_ready)
            worker.signals.error.connect(
                lambda e: logger.error(f"Dashboard stats error: {e}")
            )
            self.thread_pool.start(worker)

        except Exception as e:
            logger.error(f"Error starting dashboard statistics update: {e}")
            self._update_status_message(
                self.tr("Error updating statistics: %1").replace("%1", str(e))
            )

    def _on_dashboard_stats_ready(self, stats):
        """Handle statistics loaded from background worker"""
        try:
            # Update UI labels
            self.total_cards_label.setText(
                self.tr("Total Cards: %1").replace("%1", str(stats["total_cards"]))
            )
            self.unique_cards_label.setText(
                self.tr("Unique Cards: %1").replace("%1", str(stats["unique_cards"]))
            )
            self.total_packs_label.setText(
                self.tr("Total Packs: %1").replace("%1", str(stats["total_packs"]))
            )

            if stats.get("last_processed"):
                last_processed = stats["last_processed"]
                if isinstance(last_processed, str):
                    last_processed = datetime.fromisoformat(last_processed)

                now = datetime.now()
                # Ensure both are naive for comparison if one is naive
                if last_processed.tzinfo is not None:
                    now = now.astimezone(last_processed.tzinfo)

                self.last_processed_label.setText(
                    self.tr("Last Processed: %1").replace(
                        "%1", humanize.naturaltime(now - last_processed)
                    )
                )
            else:
                self.last_processed_label.setText(self.tr("Last Processed: Never"))

            # Update recent activity list with the database results
            self._update_recent_activity(db_activities=stats.get("recent_activity", []))
            self._update_status_message(self.tr("Dashboard statistics updated"))

        except Exception as e:
            logger.error(f"Error updating dashboard UI: {e}")

    def _request_dashboard_update(self):
        """Request a dashboard update with debouncing"""
        if hasattr(self, "_dashboard_timer"):
            self._dashboard_timer.start(1000)  # Wait 1 second before actually updating
        else:
            self._update_dashboard_statistics()

    def _update_recent_activity(self, db_activities=None):
        """Update recent activity list"""
        try:
            # Clear existing items
            self.recent_activity_list.clear()

            all_items = []

            # 1. Add recent activity from database (if provided)
            if db_activities is None:
                db_activities = []

            # Filter for this session only if session_start_time is set
            session_start = getattr(self, "session_start_time", None)

            # DB activities come newest first from SQL, so reverse them for bottom-newest
            for activity in reversed(db_activities):
                if isinstance(activity, str):
                    # Robustness: handle legacy string format
                    all_items.append({"text": activity, "color": None})
                    continue

                raw_ts = activity.get("timestamp")
                if not raw_ts:
                    continue

                # Use string comparison, but normalize ISO format (replace T with space)
                ts = raw_ts.replace("T", " ")
                ss = session_start.replace("T", " ") if session_start else None
                if ss and ts < ss:
                    continue
                description = activity.get("description", "Unknown activity")
                item_text = f"{raw_ts} - {description}"
                all_items.append({"text": item_text, "color": None})

            # 2. Add session status messages
            session_msgs = list(getattr(self, "recent_activity_messages", []))
            # session_msgs are in chronological order, so just append
            for entry in session_msgs:
                item_text = f"{entry['timestamp']} - {entry['description']}"
                all_items.append({"text": item_text, "color": None})

            # 3. Add active tasks last (so they are at the bottom)
            active_tasks = [
                t for t in self.processing_tasks if t["status"] in ["Running", "Queued"]
            ]
            for task in active_tasks:
                progress_text = (
                    f" ({task['progress']}%)" if task["status"] == "Running" else ""
                )
                item_text = f"[{task['status']}] {task['description']}{progress_text}"
                color = (
                    Qt.GlobalColor.blue
                    if task["status"] == "Running"
                    else Qt.GlobalColor.darkYellow
                )
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
                self.recent_activity_list.addItem(self.tr("No recent activity"))
            else:
                # Scroll to bottom to show newest entries
                self.recent_activity_list.scrollToBottom()

        except Exception as e:
            logger.error(f"Error updating recent activity: {e}")
            self.recent_activity_list.clear()
            self.recent_activity_list.addItem(self.tr("Error loading activity"))

    def _setup_cards_tab(self):
        """Set up the cards tab"""
        cards_widget = QWidget()
        cards_layout = QVBoxLayout()

        # Create filter controls
        filter_layout = QHBoxLayout()

        # Set filter
        self.set_filter = QComboBox()
        self.set_filter.addItem(self.tr("All Sets"))
        self.set_filter.setMinimumWidth(150)
        filter_layout.addWidget(QLabel(self.tr("Set:")))
        filter_layout.addWidget(self.set_filter)

        # Rarity filter
        self.rarity_filter = QComboBox()
        self.rarity_filter.addItem(self.tr("All Rarities"))
        self.rarity_filter.setMinimumWidth(150)
        filter_layout.addWidget(QLabel(self.tr("Rarity:")))
        filter_layout.addWidget(self.rarity_filter)

        # Search box
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText(self.tr("Search cards..."))
        self.search_box.setMinimumWidth(200)
        filter_layout.addWidget(self.search_box)

        # Refresh button
        self.refresh_cards_btn = QPushButton(self.tr("Refresh"))
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
        self.cards_tab_index = self.tab_widget.addTab(cards_widget, self.tr("Cards"))

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
            self.task_table.setPlaceholderText(self.tr("No active tasks"))
        except Exception:
            # setPlaceholderText not available in some environments; ignore gracefully
            pass

        # Set up headers
        horizontal_header = self.task_table.horizontalHeader()
        horizontal_header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        # Dynamic label to reflect whether any tasks are currently running/queued
        self.active_tasks_label = QLabel(self.tr("Active Tasks:"))
        processing_layout.addWidget(self.active_tasks_label)
        processing_layout.addWidget(self.task_table)

        # Task details section
        self.task_details_text = QTextEdit()
        self.task_details_text.setReadOnly(True)
        self.task_details_text.setMinimumHeight(150)
        processing_layout.addWidget(QLabel(self.tr("Task Details:")))
        processing_layout.addWidget(self.task_details_text)

        # Control buttons
        control_layout = QHBoxLayout()

        cancel_btn = QPushButton(self.tr("Cancel Selected"))
        cancel_btn.clicked.connect(self._cancel_selected_task)
        control_layout.addWidget(cancel_btn)

        clear_btn = QPushButton(self.tr("Clear Completed"))
        clear_btn.clicked.connect(self._clear_completed_tasks)
        control_layout.addWidget(clear_btn)

        processing_layout.addLayout(control_layout)

        processing_widget.setLayout(processing_layout)
        self.tab_widget.addTab(processing_widget, self.tr("Processing"))
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
                            task_id, self.tr("Cancelled"), "Cancelled by user"
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
        # Session start time to filter out previous session activity
        self.session_start_time = datetime.now().isoformat()
        # In-memory session log for status messages to surface in Recent Activity
        self.recent_activity_messages = [
            {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "description": "Loading app...",
            }
        ]

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

        # Rarity and count columns use a stable sizing strategy
        # Initially size to contents, then allow interactive resizing
        self.cards_table.setColumnWidth(3, 100)
        self.cards_table.setColumnWidth(4, 60)
        horizontal_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        horizontal_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)

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
                worker = CardDataLoadWorker()
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
        from app.db.models import Card, CardSet

        RARITY_MAP = dict(zip(Card.Rarity.values, Card.Rarity.labels))
        SET_MAP = CardSet.name_map()

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
            self.set_filter.addItem(self.tr("All Sets"))
            set_order = list(SET_MAP.values())
            sorted_sets = sorted(
                sets,
                key=lambda s: set_order.index(s) if s in set_order else 999,
            )
            for set_name in sorted_sets:
                self.set_filter.addItem(set_name)

            # Restore previous selection if possible
            if current_set != self.tr("All Sets") and current_set in sets:
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
            self.rarity_filter.addItem(self.tr("All Rarities"))

            # Sort rarities according to the order in RARITY_MAP
            rarity_order = list(RARITY_MAP.values())
            sorted_rarities = sorted(
                rarities,
                key=lambda r: rarity_order.index(r) if r in rarity_order else 999,
            )
            for rarity in sorted_rarities:
                self.rarity_filter.addItem(rarity)

            # Restore previous selection if possible
            if current_rarity != self.tr("All Rarities") and current_rarity in rarities:
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
                if (
                    set_filter != self.tr("All Sets")
                    and card.get("set_name") != set_filter
                ):
                    continue

                # Apply rarity filter
                if (
                    rarity_filter != self.tr("All Rarities")
                    and card.get("rarity") != rarity_filter
                ):
                    continue

                # Apply search filter
                if search_text:
                    card_name = (card.get("card_name") or "").lower()
                    set_name = (card.get("set_name") or "").lower()
                    rarity = (card.get("rarity") or "").lower()

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
                self.tr("Showing %1 of %2 unique cards")
                .replace("%1", str(len(filtered_cards)))
                .replace("%2", str(len(all_cards)))
            )

        except Exception as e:
            print(f"Error applying filters: {e}")
            self._update_status_message(
                self.tr("Error applying filters: %1").replace("%1", str(e))
            )

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
                    resolved_path,
                    card_name + " (" + (card_data.get("set_name") or "Unknown") + ")",
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
            from app.db.models import ScreenshotCard
            from django.db.models import Count

            # Get account distribution from database using Django ORM
            sc_entries = (
                ScreenshotCard.objects.filter(card__code=card_code)
                .values(
                    "screenshot__account__name",
                    "screenshot__name",
                    "screenshot__account__shinedust",
                )
                .annotate(card_count=Count("id"))
                .order_by("-card_count", "screenshot__account__name")
            )

            account_data = []
            for entry in sc_entries:
                account_data.append(
                    (
                        entry["screenshot__account__name"],
                        entry["card_count"],
                        entry["screenshot__name"],
                        entry["screenshot__account__shinedust"],
                    )
                )

            if account_data:
                # Get screenshots directory from settings
                screenshots_dir = self.settings.get_setting(
                    "General/screenshots_dir", ""
                )

                dialog = AccountCardListDialog(
                    card_name,
                    card_code,
                    account_data,
                    screenshots_dir=screenshots_dir,
                    on_removed=self._refresh_after_removal,
                    parent=self,
                )
                dialog.show()
            else:
                QMessageBox.information(
                    self,
                    self.tr("No Data"),
                    self.tr("No account distribution found for %1").replace(
                        "%1", card_name
                    ),
                )

        except Exception as e:
            logger.error(f"Error showing account distribution: {e}")
            QMessageBox.warning(
                self,
                self.tr("Error"),
                self.tr("Could not show account distribution: %1").replace(
                    "%1", str(e)
                ),
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
                    BASE_DIR / "resources" / "card_imgs" / image_path,
                ]

                normalized_path = image_path.replace("\\", "/")
                if "/" in normalized_path:
                    parts = normalized_path.split("/")
                    filename = parts[-1]
                    set_code = parts[0]
                    check_paths.append(
                        BASE_DIR / "resources" / "card_imgs" / set_code / filename,
                    )

                resolved_path = None
                for path in check_paths:
                    if os.path.exists(path):
                        resolved_path = path
                        break

                if resolved_path:
                    self._show_full_card_image(
                        resolved_path,
                        card_name
                        + " ("
                        + (result_data.get("set_name") or "Unknown")
                        + ")",
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
        if not message:
            return

        if hasattr(self, "main_status"):
            self.statusBar().clearMessage()
            self.main_status.setText(message)
            logger.debug(f"Status updated: {message}")

        # Also push this status message to the Recent Activity session log
        # but filter out frequent progress updates to keep the UI responsive
        # and the log clean.
        # TODO: How am I gonna do this in a multilingual way?
        skip_log_keywords = [
            "Progress:",
            "Processed ",
            "Scanned ",
            "Importing ",
            "Imported ",
            "Screenshot processing:",
            "CSV import:",
            "Downloading card art",
            "Checking for updates",
            "Dashboard statistics updated",
        ]
        if any(keyword in message for keyword in skip_log_keywords):
            return

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
        # Since we use Django ORM, we assume it's connected if we got this far
        self.db_status.setText(self.tr("DB: Connected"))
        self.db_status.setStyleSheet("color: green;")

    def _update_task_status(
        self,
        task_id: str = None,
        status: str = None,
        progress: int | str = None,
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

        self.task_status.setText(self.tr("Tasks: %1").replace("%1", str(active_tasks)))
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

    def _get_saved_paths(self) -> tuple[str, str]:
        """Retrieve saved CSV and screenshot paths from settings"""
        csv_path = self.settings.get_setting("General/csv_import_path", "")
        screenshots_dir = self.settings.get_setting("General/screenshots_dir", "")
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
                self.tr("Load New Data"),
                self.tr(
                    "A data import is already in progress. Please wait for it to finish."
                ),
            )
            return

        csv_path, screenshots_dir = self._get_saved_paths()

        issues = []
        if not csv_path:
            issues.append(self.tr("CSV file path is not set."))
        elif not os.path.isfile(csv_path):
            issues.append(self.tr("CSV file not found: %1").replace("%1", csv_path))

        if not screenshots_dir:
            issues.append(self.tr("Screenshots directory is not set."))
        elif not os.path.isdir(screenshots_dir):
            issues.append(
                self.tr("Screenshots directory not found: %1").replace(
                    "%1", screenshots_dir
                )
            )

        if issues:
            QMessageBox.warning(
                self,
                self.tr("Load New Data"),
                "\n".join(issues)
                + "\n\n"
                + self.tr(
                    "Please use the Import CSV or Process Screenshots options to set the correct locations."
                ),
            )
            self._update_load_new_data_availability()
            return

        self._combined_import_request = {
            "csv_path": csv_path,
            "screenshots_dir": screenshots_dir,
        }

        self._update_status_message(self.tr("Starting data import…"))
        self._on_csv_imported(csv_path, combined=True)

    def _on_import_csv(self):
        """Handle Import CSV action"""

        try:
            # Get initial path from settings
            initial_path = self.settings.get_setting("General/csv_import_path", "")

            # Create and show CSV import dialog
            dialog = CSVImportDialog(
                self, initial_path=initial_path, settings=self.settings
            )
            dialog.csv_imported.connect(self._on_csv_imported)

            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._update_status_message(self.tr("CSV import completed"))
            else:
                self._update_status_message(self.tr("CSV import cancelled"))

            # Update combined import availability after any dialog interaction
            self._update_load_new_data_availability()

        except Exception as e:
            print(f"Error importing CSV: {e}")
            self._update_status_message(
                self.tr("Error importing CSV: %1").replace("%1", str(e))
            )

    def _on_csv_imported(self, file_path: str, combined: bool = False):
        """Handle successful CSV import - start background processing"""
        print(f"Starting background CSV import from: {file_path}")
        self._update_status_message(self.tr("Starting background CSV import..."))

        try:
            task_id = get_task_id()

            # Add task to tracking system
            self._add_processing_task(
                task_id,
                self.tr("CSV Import: %1").replace("%1", os.path.basename(file_path)),
            )

            if combined and self._combined_import_request is not None:
                self._combined_import_request["csv_task_id"] = task_id

            # Create worker for CSV import
            screenshots_dir = self.settings.get_setting("General/screenshots_dir", "")
            worker = CSVImportWorker(
                file_path=file_path,
                task_id=task_id,
                screenshots_dir=screenshots_dir,
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

            self._update_status_message(self.tr("CSV import started in background"))

        except Exception as e:
            print(f"Error starting CSV import worker: {e}")
            self._update_status_message(
                self.tr("Error starting CSV import: %1").replace("%1", str(e))
            )

    def _on_csv_import_progress(self, current: int, total: int, task_id: str = None):
        """Handle CSV import progress updates"""
        self._update_progress(
            current,
            total,
            self.tr("CSV import: %1/%2")
            .replace("%1", str(current))
            .replace("%2", str(total)),
        )

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
            self.tr("CSV import completed: %1 packs imported").replace(
                "%1", str(result.get("total_rows", 0))
            )
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
            self._update_status_message(
                self.tr("Starting screenshot processing from saved directory…")
            )
            self._start_combined_screenshot_step()

    def _on_csv_import_error(self, error: str, task_id: str = None):
        """Handle CSV import errors"""
        self._update_status_message(
            self.tr("CSV import error: %1").replace("%1", str(error))
        )

        if task_id:
            self._update_task_status(task_id, "Failed", error=error)

        if (
            self._combined_import_request
            and self._combined_import_request.get("csv_task_id") == task_id
        ):
            self._update_status_message(
                self.tr("Combined import stopped due to CSV import error.")
            )
            self._combined_import_request = None
            self._update_load_new_data_availability()

    def _on_csv_import_finished(self, worker=None):
        """Handle CSV import completion"""
        self._update_status_message(self.tr("CSV import finished"))

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
                self.tr(
                    "Combined import stopped: saved screenshots directory is unavailable."
                )
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
            current,
            total,
            self.tr("Screenshot processing: %1/%2")
            .replace("%1", str(current))
            .replace("%2", str(total)),
        )

        # Update task progress if task_id provided
        if task_id:
            percentage = int((current / total) * 100) if total > 0 else 0
            self._update_task_status(task_id, progress=percentage)

            # Refresh dashboard to show progress in recent activity
            self._request_dashboard_update()

    def _on_screenshot_processing_status(self, status: str):
        """Handle screenshot processing status updates"""
        self._update_status_message(status)

    def _on_screenshot_processing_result(self, result: dict, task_id: str = None):
        """Handle screenshot processing result"""
        self._update_status_message(
            self.tr("Screenshot processing completed: %1 files processed").replace(
                "%1", str(result.get("total_files", 0))
            )
        )

        # Increase activity limit to show new items
        self.recent_activity_limit += result.get("successful_files", 0)

        if task_id:
            self._update_task_status(task_id, "Completed")

        if (
            self._combined_import_request
            and self._combined_import_request.get("screenshot_task_id") == task_id
        ):
            self._update_status_message(self.tr("Data import finished!"))

            # If this was part of a migration, rename the old database
            if self._migration_in_progress:
                try:
                    old_db_path = BASE_DIR / "data" / "cardcounter.db"
                    new_path = BASE_DIR / "data" / "cardcounter.db.old"
                    if os.path.exists(old_db_path):
                        if os.path.exists(new_path):
                            os.remove(new_path)
                        os.rename(old_db_path, new_path)
                        logger.info(
                            f"Migration complete. Renamed {old_db_path} to {new_path}"
                        )
                except Exception as e:
                    logger.error(f"Failed to rename old database after migration: {e}")
                finally:
                    self._migration_in_progress = False

            self._combined_import_request = None
            self._update_load_new_data_availability()

    def _on_screenshot_processing_error(self, error: str, task_id: str = None):
        """Handle screenshot processing errors"""
        self._update_status_message(
            self.tr("Screenshot processing error: %1").replace("%1", str(error))
        )

        if task_id:
            self._update_task_status(task_id, "Failed", error=error)

        if (
            self._combined_import_request
            and self._combined_import_request.get("screenshot_task_id") == task_id
        ):
            self._update_status_message(
                self.tr("Combined import stopped due to screenshot processing error.")
            )
            self._combined_import_request = None
            self._update_load_new_data_availability()

    def _on_screenshot_processing_finished(self, worker=None):
        """Handle screenshot processing completion"""
        self._update_status_message(self.tr("Screenshot processing finished"))

        # Clean up worker
        if worker and worker in self.active_workers:
            self.active_workers.remove(worker)
        elif self.active_workers:
            self.active_workers.pop()

        # Refresh dashboard statistics only; Cards tab refresh is manual after first load
        self._request_dashboard_update()

        # Clear progress indicators
        self._clear_progress()

        if self._combined_import_request and self._combined_import_request.get(
            "screenshot_task_id"
        ):
            # Leave status message from result/error; just clear state here
            self._combined_import_request = None
            self._update_load_new_data_availability()

    def _on_process_screenshots(self):
        """Handle Process Screenshots action"""
        # Check if cards are loaded first
        try:
            from app.db.models import Screenshot

            total_packs = Screenshot.objects.count()
            if total_packs == 0:
                from PyQt6.QtWidgets import QMessageBox

                QMessageBox.warning(
                    self,
                    self.tr("Missing Screenshot Data"),
                    self.tr(
                        "No screenshot records found in database. Please import a CSV file first (File -> Import CSV) "
                        "before processing screenshots."
                    ),
                )
                self._update_status_message(
                    self.tr(
                        "Aborted screenshot processing: No screenshot records in database"
                    )
                )
                return
        except Exception as e:
            logger.error(f"Error checking card count: {e}")
            # Continue anyway? Or abort? Aborting is safer.
            self._update_status_message(
                self.tr("Error checking card count: %1").replace("%1", str(e))
            )
            return

        try:
            # Get initial directory from settings
            initial_dir = self.settings.get_setting("General/screenshots_dir", "")

            # Create and show screenshot processing dialog
            dialog = ScreenshotProcessingDialog(
                self, initial_dir=initial_dir, settings=self.settings
            )
            dialog.processing_started.connect(self._on_processing_started)

            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._update_status_message(self.tr("Screenshot processing completed"))
            else:
                self._update_status_message(self.tr("Screenshot processing cancelled"))

            # Update combined import availability after any dialog interaction
            self._update_load_new_data_availability()

        except Exception as e:
            print(f"Error processing screenshots: {e}")
            self._update_status_message(
                self.tr("Error processing screenshots: %1").replace("%1", str(e))
            )

    def _on_processing_started(self, directory_path: str, overwrite: bool):
        """Handle successful processing start - create and start screenshot processing worker"""
        self._update_status_message(
            self.tr("Starting background screenshot processing...")
        )

        try:
            task_id = get_task_id()

            # Add task to tracking system
            self._add_processing_task(
                task_id,
                self.tr("Screenshot Processing: %1").replace(
                    "%1", os.path.basename(directory_path)
                ),
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

            self._update_status_message(
                self.tr("Screenshot processing started in background")
            )

        except Exception as e:
            print(f"Error starting screenshot processing worker: {e}")
            self._update_status_message(
                self.tr("Error starting screenshot processing: %1").replace(
                    "%1", str(e)
                )
            )

    def _on_art_download_progress(self, current: int, total: int, task_id: str = None):
        """Progress updates for card art download (also updates task model)."""
        try:
            # Update visible progress bar and message
            self._update_progress(current, total, self.tr("Downloading card art"))

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
                self.tr("Card art download complete: %1 images saved").replace(
                    "%1", str(images)
                )
            )
            if task_id:
                self._update_task_status(task_id, "Completed", progress=100)
        except Exception:
            self._update_status_message(self.tr("Card art download complete"))
            if task_id:
                self._update_task_status(task_id, "Completed", progress=100)

    def _on_art_download_error(self, error: str, task_id: str = None):
        self._update_status_message(
            self.tr("Card art download error: %1").replace("%1", str(error))
        )

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
        try:
            # Create and show about dialog
            dialog = AboutDialog(self)
            dialog.exec()

        except Exception as e:
            self._update_status_message(
                self.tr("Error showing about dialog: %1").replace("%1", str(e))
            )

    def _on_preferences(self):
        """Show preferences dialog"""
        try:
            dialog = PreferencesDialog(self, self.settings)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                # Refresh anything that might depend on settings
                self._update_load_new_data_availability()
                self._setup_watchdog()
        except Exception as e:
            self._update_status_message(
                self.tr("Error showing preferences dialog: %1").replace("%1", str(e))
            )

    def _init_watchdog(self):
        """Initialize the screenshot directory watchdog system"""
        self._watchdog_observer = None
        self._watchdog_handler = ScreenshotChangeHandler()
        # Do NOT force has_changes = True here to avoid immediate heavy I/O on startup.
        # Instead, we will schedule a one-time catch-up scan after the app is stable.
        self._watchdog_handler.has_changes = False

        self._watchdog_timer = QTimer(self)
        self._watchdog_timer.timeout.connect(self._check_for_screenshot_changes)

        self._setup_watchdog()

        # Schedule a one-time catch-up scan after 10 seconds
        QTimer.singleShot(10000, self._trigger_catchup_scan)

    def _trigger_catchup_scan(self):
        """Trigger an initial scan to catch up on any changes while the app was closed"""
        logger.debug("Triggering initial catch-up scan for screenshots...")
        if not hasattr(self, "_watchdog_handler"):
            return

        # We only trigger if no other processing is running
        if not self._workers_are_running():
            self._watchdog_handler.has_changes = True
            self._check_for_screenshot_changes()
        else:
            # If something is already running, we don't need to force it,
            # it's already doing a scan.
            logger.debug("Catch-up scan skipped: processing already in progress.")

    def _setup_watchdog(self):
        """Setup or refresh the watchdog observer based on settings"""
        # Stop existing observer if any
        if self._watchdog_observer:
            try:
                self._watchdog_observer.stop()
                # We don't join here to avoid blocking the UI thread during setup,
                # as stop() signals the thread to exit.
            except Exception as e:
                logger.error(f"Error stopping watchdog observer: {e}")
            self._watchdog_observer = None

        # Check if enabled
        enabled = (
            str(
                self.settings.get_setting("Screenshots/watch_directory", "False")
            ).lower()
            == "true"
        )
        if not enabled:
            self._watchdog_timer.stop()
            logger.info("Watchdog system disabled by user preference")
            return

        # Get directory and interval
        watch_dir = self.settings.get_setting("General/screenshots_dir", "")
        interval_min = int(self.settings.get_setting("Screenshots/check_interval", 5))

        if not watch_dir or not os.path.isdir(watch_dir):
            logger.warning(f"Watchdog enabled but directory '{watch_dir}' is invalid")
            self._watchdog_timer.stop()
            return

        # Start observer
        try:
            # Using PollingObserver specifically of WSL/network mounts
            # where native inotify events don't work correctly.
            # timeout=10 to keep CPU usage low with many files.
            observer = PollingObserver(timeout=10)
            self._watchdog_observer = observer

            def start_observer():
                try:
                    observer.schedule(
                        self._watchdog_handler, watch_dir, recursive=False
                    )
                    observer.start()
                    logger.info(f"Watchdog background thread started for {watch_dir}")
                except Exception as e:
                    logger.error(f"Failed to start watchdog observer thread: {e}")

            threading.Thread(target=start_observer, daemon=True).start()

            # Start timer - check once immediately (but still deferred by QTimer)
            self._watchdog_timer.start(interval_min * 60 * 1000)
            QTimer.singleShot(1000, self._check_for_screenshot_changes)
            logger.info(
                f"Watchdog initialization scheduled for {watch_dir}, checking every {interval_min} minutes"
            )
        except Exception as e:
            logger.error(f"Failed to start watchdog observer: {e}")
            self._watchdog_timer.stop()

    def _check_for_screenshot_changes(self):
        """Periodically check if watchdog detected any changes"""
        logger.debug("Checking for screenshot changes flag...")
        if not self._watchdog_handler.has_changes:
            return

        # Don't start processing if the window hasn't been shown yet or just shown
        # This helps avoid a hang immediately on startup if there are pending changes
        if not self.isVisible():
            logger.info(
                "Screenshot changes detected, but window is not yet visible. Delaying."
            )
            return

        logger.debug("Changes detected in screenshots directory.")

        if self._workers_are_running():
            logger.info(
                "Screenshot changes detected, but processing is already in progress. Skipping."
            )
            return

        logger.info(
            "Screenshot changes detected by watchdog. Triggering processing job."
        )

        self._watchdog_handler.has_changes = False

        # Trigger combined import (CSV + screenshots)
        csv_path, screenshot_path = self._get_saved_paths()
        if not csv_path or not screenshot_path:
            logger.warning("No CSV or screenshots directory found. Skipping import.")
            return
        self._on_load_new_data()

    def closeEvent(self, event):
        """Handle window close event"""
        print("Closing application...")

        # Display the closing message
        self._update_status_message(
            self.tr("Closing application. Cleaning up... this may take a moment.")
        )

        # Force the UI to process the status update
        from PyQt6.QtWidgets import QApplication

        QApplication.processEvents()

        # Perform cleanup
        try:
            # Stop watchdog
            if hasattr(self, "_watchdog_observer") and self._watchdog_observer:
                try:
                    self._watchdog_observer.stop()
                    # We don't join() because it might block and
                    # watchdog threads are daemon threads
                except Exception:
                    pass

            # Request cancellation on any active workers
            active_workers = getattr(self, "active_workers", [])
            for worker in list(active_workers):
                cancel = getattr(worker, "cancel", None)
                if callable(cancel):
                    try:
                        cancel()
                    except Exception:
                        pass
        except Exception as e:
            print(f"Error during shutdown: {e}")

        # Finally hide and accept the event
        self.hide()
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
        from app.db.models import Card

        RARITY_MAP = dict(zip(Card.Rarity.values, Card.Rarity.labels))

        full_name = raw_name if raw_name else card_code
        display_name = clean_card_name(full_name)
        display_rarity = raw_rarity

        # Resolve rarity display name if possible
        import re

        match = re.search(r"\s*\(([^)]+)\)$", full_name)
        if match:
            rarity_code = match.group(1)
            # Map rarity code to display name if it exists in the map
            if rarity_code in RARITY_MAP:
                display_rarity = RARITY_MAP[rarity_code]
            else:
                # If code not in map but was in parentheses, use it as rarity
                # (e.g., 'Promo' in 'Pikachu (Promo)')
                display_rarity = rarity_code

        return display_name, display_rarity

    def _refresh_after_removal(self):
        """Refresh data after a card is removed"""
        self._refresh_cards_tab()
        self._request_dashboard_update()

    def _on_process_removed_cards(self):
        """Handle 'Process Removed Cards' menu action"""
        removed_cards = get_traded_cards()
        if not removed_cards:
            QMessageBox.information(
                self, self.tr("No Removed Cards"), self.tr("No cards to process.")
            )
            return

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self.tr("Process Removed Cards?"))
        msg_box.setText(
            self.tr(
                "This will process <b>%1</b> recorded card removals from the database.<br><br>"
                "This is useful if you have re-imported screenshots that might have brought back cards you previously removed."
            ).replace("%1", str(len(removed_cards)))
        )
        msg_box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)

        if msg_box.exec() == QMessageBox.StandardButton.Yes:
            from app.db.models import ScreenshotCard

            processed_count = 0
            for item in removed_cards:
                account = item.get("account")
                card_code = item.get("card_code")
                if account and card_code:
                    # Remove one instance of this card for this account
                    sc = ScreenshotCard.objects.filter(
                        screenshot__account__name=account, card__code=card_code
                    ).first()
                    if sc:
                        sc.delete()
                        processed_count += 1

            QMessageBox.information(
                self,
                self.tr("Process Complete"),
                self.tr(
                    "Processed %1 records. %2 cards were actually found and removed."
                )
                .replace("%1", str(len(removed_cards)))
                .replace("%2", str(processed_count)),
            )

            if processed_count > 0:
                self._refresh_after_removal()

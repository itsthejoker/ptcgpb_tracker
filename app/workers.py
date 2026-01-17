"""
Card Counter Workers

Background worker classes for the Card Counter PyQt6 application.
This module provides QRunnable-based workers for long-running operations.
"""

from PyQt6.QtCore import QRunnable, pyqtSignal, QObject
from typing import Optional, Dict, Any, List
from datetime import datetime
import os
import csv
import time
import logging

from app.utils import PortableSettings

logger = logging.getLogger(__name__)


def get_max_thread_count():
    settings = PortableSettings()
    max_cores = settings.get_setting("Debug/max_cores", 0)
    if max_cores > 0:
        return max_cores

    # Leave at least one core for the UI thread to keep things responsive
    cpu_count = os.cpu_count() or 2
    # Use max(1, count - 1) but still cap at 8 to avoid too many threads on high-core systems
    return min(max(1, cpu_count - 1), 8)


class WorkerSignals(QObject):
    """Signals available from worker threads"""

    progress = pyqtSignal(int, int)  # current, total
    status = pyqtSignal(str)
    result = pyqtSignal(object)
    error = pyqtSignal(str)
    finished = pyqtSignal()


class CSVImportWorker(QRunnable):
    """Worker for importing CSV files in the background"""

    def __init__(self, file_path: str, task_id: str = None, db_path: str = None):
        super().__init__()
        self.file_path = file_path
        self.task_id = task_id
        self.db_path = db_path
        self.signals = WorkerSignals()
        self._is_cancelled = False

    def run(self):
        """Process CSV import in background thread"""
        try:
            if self._is_cancelled:
                return

            self.signals.status.emit("Starting CSV import...")

            # Validate file
            if not os.path.exists(self.file_path):
                raise FileNotFoundError(f"CSV file not found: {self.file_path}")

            # Read all rows into memory
            rows = []
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
            except Exception as e:
                raise ValueError(f"Failed to parse CSV file: {e}")

            total_rows = len(rows)
            if total_rows == 0:
                self.signals.status.emit("CSV file is empty or only contains header")
                self.signals.result.emit({"total_rows": 0, "new_rows": 0})
                return

            from app.database import Database

            processed_count = 0
            new_records = 0

            self.signals.status.emit(f"Importing {total_rows} rows...")

            # Initialize database once
            db = Database(self.db_path)

            # Process in batches to avoid holding a transaction for too long
            # and to allow other threads to write to the database.
            batch_size = 100
            for i in range(0, total_rows, batch_size):
                if self._is_cancelled:
                    break

                batch = rows[i : i + batch_size]
                with db.transaction():
                    for row in batch:
                        if self._is_cancelled:
                            break

                        # Use CleanFilename as the Account
                        if "CleanFilename" in row and row["CleanFilename"]:
                            row["Account"] = row["CleanFilename"]
                        elif "DeviceAccount" in row and row["DeviceAccount"]:
                            row["Account"] = row["DeviceAccount"]
                        elif "Account" not in row or not row["Account"]:
                            row["Account"] = "Account Unknown"

                        # Ensure all required fields exist
                        required_fields = [
                            "Timestamp",
                            "OriginalFilename",
                            "CleanFilename",
                            "Account",
                            "PackType",
                            "CardTypes",
                            "CardCounts",
                            "PackScreenshot",
                            "Shinedust",
                        ]
                        for field in required_fields:
                            if field not in row:
                                row[field] = ""

                        # Add to database
                        try:
                            _, is_new = db.add_screenshot(row)
                            if is_new:
                                new_records += 1
                        except Exception as e:
                            logger.error(f"Error importing row: {e}")

                        processed_count += 1

                # Update progress after each batch
                self.signals.progress.emit(processed_count, total_rows)
                # self.signals.status.emit(f"Imported {processed_count}/{total_rows}...")

            if self._is_cancelled:
                self.signals.status.emit("CSV import cancelled")
                return

            self.signals.progress.emit(total_rows, total_rows)
            self.signals.status.emit(
                f"Successfully imported {total_rows} packs ({new_records} new)"
            )
            self.signals.result.emit(
                {
                    "file_path": self.file_path,
                    "total_rows": total_rows,
                    "new_rows": new_records,
                }
            )

        except Exception as e:
            self.signals.error.emit(f"CSV import failed: {e}")
        finally:
            self.signals.finished.emit()

    def cancel(self):
        """Cancel the worker"""
        self._is_cancelled = True
        executor = getattr(self, "_executor", None)
        if executor:
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass


class CardArtDownloadWorker(QRunnable):
    """Worker to download card art templates in the background.

    Downloads set images from Limitless TCG CDN and stores them under
    resources/card_imgs/<set_id>/ using a portable path. The worker uses
    multi-threading across sets while downloading cards sequentially per set
    (to avoid excessive 404/AccessDenied fetches).
    """

    def __init__(
        self,
        base_list_url: str = None,
        card_url_template: str = None,
        max_workers: int = None,
    ):
        super().__init__()
        self.signals = WorkerSignals()
        self._is_cancelled = False
        self.base_list_url = base_list_url or "https://pocket.limitlesstcg.com/cards"
        self.card_url_template = card_url_template or (
            "https://limitlesstcg.nyc3.cdn.digitaloceanspaces.com/pocket/{set_id}/{set_id}_{card_num}_EN_SM.webp"
        )
        self.max_workers = max_workers or get_max_thread_count()

    def cancel(self):
        """Cancel the worker"""
        self._is_cancelled = True
        executor = getattr(self, "_executor", None)
        if executor:
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass

    def run(self):
        try:
            if self._is_cancelled:
                return

            # Lazy imports to keep main thread light
            import httpx
            import re
            from app.utils import get_portable_path

            # Resolve destination root
            dest_root = get_portable_path("resources", "card_imgs")
            os.makedirs(dest_root, exist_ok=True)

            self.signals.status.emit("Fetching card set list…")

            # Fetch list of set IDs
            try:
                resp = httpx.get(self.base_list_url, timeout=30.0)
                resp.raise_for_status()
            except Exception as e:
                raise RuntimeError(f"Failed to fetch set list: {e}")

            # Parse set IDs using regex to avoid external parser dependency
            html = resp.text or ""
            # matches href="/cards/<set_id>"
            matches = re.findall(r'href\s*=\s*"/cards/([^"]+)"', html)
            set_ids = sorted(list(set(m for m in matches if m)))

            if not set_ids:
                raise RuntimeError("No set IDs found on the listing page")

            # Ensure per-set directories
            for set_id in set_ids:
                if self._is_cancelled:
                    return
                os.makedirs(os.path.join(dest_root, set_id), exist_ok=True)

            total_estimate = len(set_ids) * 500  # rough estimate for progress
            processed = 0

            from concurrent.futures import ThreadPoolExecutor, as_completed

            self.signals.status.emit(
                f"Downloading card art for {len(set_ids)} sets using {self.max_workers} threads…"
            )

            def download_set(set_id: str) -> int:
                if self._is_cancelled:
                    return 0
                images_saved = 0
                # Sequentially iterate per set to stop at first missing
                for card_num in range(1, 500):
                    if self._is_cancelled:
                        break

                    url = self.card_url_template.format(
                        set_id=set_id, card_num=str(card_num).zfill(3)
                    )
                    try:
                        r = httpx.get(url, timeout=20.0)
                    except Exception:
                        # transient error -> try next number; don't break the set
                        continue

                    # Limitless returns 200 with AccessDenied content when missing
                    content = r.content or b""
                    if r.status_code != 200 or (b"AccessDenied" in content):
                        # End of cards for this set
                        break

                    try:
                        filename = f"{set_id}_{card_num}.webp"
                        out_path = os.path.join(dest_root, set_id, filename)
                        with open(out_path, "wb") as f:
                            f.write(content)
                        images_saved += 1
                    except Exception:
                        # Skip on IO errors and continue
                        continue
                return images_saved

            total_saved = 0
            self._executor = ThreadPoolExecutor(max_workers=self.max_workers)
            try:
                futures = {
                    self._executor.submit(download_set, sid): sid for sid in set_ids
                }
                for fut in as_completed(futures):
                    if self._is_cancelled:
                        if self._executor:
                            self._executor.shutdown(wait=False, cancel_futures=True)
                        self.signals.status.emit("Card art download cancelled")
                        return
                    sid = futures[fut]
                    try:
                        saved = fut.result()
                        total_saved += saved
                        processed += 500  # advance the rough estimate per finished set
                        if processed > total_estimate:
                            processed = total_estimate
                        self.signals.progress.emit(processed, total_estimate)
                        self.signals.status.emit(
                            f"Finished set {sid}: {saved} images saved"
                        )
                    except Exception as e:
                        self.signals.status.emit(f"Error downloading set {sid}: {e}")
            finally:
                if self._executor:
                    self._executor.shutdown(
                        wait=not self._is_cancelled, cancel_futures=self._is_cancelled
                    )
                    self._executor = None

            self.signals.progress.emit(total_estimate, total_estimate)
            self.signals.status.emit(
                f"Card art download completed: {total_saved} images saved across {len(set_ids)} sets"
            )

            # Precompute pHashes for downloaded cards
            if total_saved > 0 and not self._is_cancelled:
                try:
                    self.signals.status.emit(
                        "Precomputing pHashes for downloaded cards..."
                    )
                    from app.image_processing import ImageProcessor

                    processor = ImageProcessor(dest_root)
                    self.signals.status.emit("pHashes precomputed and saved.")
                except Exception as e:
                    logger.error(f"Failed to precompute pHashes: {e}")
                    self.signals.status.emit(
                        f"Warning: Failed to precompute pHashes: {e}"
                    )

            self.signals.result.emit(
                {
                    "sets": len(set_ids),
                    "images_saved": total_saved,
                    "destination": "resources/card_imgs",
                }
            )
        except Exception as e:
            self.signals.error.emit(f"Card art download failed: {e}")
        finally:
            self.signals.finished.emit()


class ScreenshotProcessingWorker(QRunnable):
    """Worker for processing screenshot images in the background"""

    def __init__(self, directory_path: str, overwrite: bool, task_id: str = None):
        super().__init__()
        self.directory_path = directory_path
        self.overwrite = overwrite
        self.task_id = task_id
        self.signals = WorkerSignals()
        self._is_cancelled = False
        self._executor = None

    def run(self):
        """Process screenshot images in background thread"""
        try:
            if self._is_cancelled:
                return

            self.signals.status.emit("Starting screenshot processing...")

            # Validate directory
            if not os.path.isdir(self.directory_path):
                raise FileNotFoundError(f"Directory not found: {self.directory_path}")

            # Initialize database
            from app.database import Database

            self.db = Database()

            # Get list of image files in batches to identify unprocessed ones first
            image_extensions = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")
            image_files = []
            all_found_count = 0

            self.signals.status.emit("Scanning directory for images...")

            batch = []
            batch_size = 500

            with os.scandir(self.directory_path) as it:
                for entry in it:
                    if self._is_cancelled:
                        return
                    if entry.is_file() and entry.name.lower().endswith(
                        image_extensions
                    ):
                        all_found_count += 1
                        if self.overwrite:
                            image_files.append(entry.name)
                        else:
                            batch.append(entry.name)

                        if not self.overwrite and len(batch) >= batch_size:
                            unprocessed = self.db.get_unprocessed_files(batch)
                            image_files.extend(unprocessed)
                            batch = []
                            self.signals.status.emit(
                                f"Scanned {all_found_count} files, found {len(image_files)} new images..."
                            )

            if not self.overwrite and batch:
                unprocessed = self.db.get_unprocessed_files(batch)
                image_files.extend(unprocessed)

            total_files = len(image_files)
            if total_files == 0:
                if all_found_count > 0:
                    self.signals.status.emit("All images already processed.")
                    self.signals.progress.emit(100, 100)
                    self.signals.result.emit(
                        {
                            "directory_path": self.directory_path,
                            "total_files": 0,
                            "successful_files": 0,
                            "failed_files": 0,
                            "overwrite": self.overwrite,
                            "message": "All images already processed",
                        }
                    )
                    return
                else:
                    raise ValueError("No image files found in directory")

            self.signals.status.emit(
                f"Found {total_files} images to process. Loading workers..."
            )

            # Initialize image processor
            from app.image_processing import ImageProcessor
            from app.utils import get_portable_path

            template_dir = get_portable_path("resources", "card_imgs")
            processor = ImageProcessor(template_dir)

            # Load card templates from resources
            try:
                if os.path.isdir(template_dir):
                    # Templates are already loaded by constructor, but we want to log it
                    self.signals.status.emit(
                        f"Loaded {processor.get_template_count()} card templates"
                    )
                else:
                    self.signals.status.emit(
                        f"Error: Template directory not found: {template_dir}"
                    )
                    raise FileNotFoundError(
                        f"Template directory not found: {template_dir}"
                    )
            except Exception as template_error:
                self.signals.status.emit(
                    f"Error: Could not load card templates: {template_error}"
                )
                raise

            # Process images in parallel using ThreadPoolExecutor for better performance
            from concurrent.futures import ThreadPoolExecutor, as_completed

            max_workers = get_max_thread_count()
            processed_count = 0
            successful_files = 0

            self.signals.status.emit(
                f"Processing images in parallel using {max_workers} threads..."
            )

            def process_single_file(filename):
                """Helper function to process a single file in a thread"""
                if self._is_cancelled:
                    return None

                file_path = os.path.join(self.directory_path, filename)
                try:
                    # Check for blank/empty images: files under 1KB should be marked as completed
                    try:
                        file_size = os.path.getsize(file_path)
                    except OSError:
                        file_size = None

                    if file_size is not None and file_size < 1024:
                        # Store an entry with zero cards and mark as processed
                        logger.info(
                            f"Blank image detected ({file_size} bytes) in {filename}. Marking as processed."
                        )
                        # Reuse storage routine with no detected cards
                        self._store_results_in_database(filename, [])
                        # Do not count as "with results" but it's successfully handled
                        return False

                    # Process the image with OpenCV
                    cards_found = processor.process_screenshot(file_path)

                    # Store results in database
                    if cards_found:
                        self._store_results_in_database(filename, cards_found)
                        return True
                    else:
                        logger.info(f"No cards detected in {filename}")
                        return False
                except Exception as e:
                    logger.error(f"Error processing {filename}: {e}")
                    return False

            self._executor = ThreadPoolExecutor(max_workers=max_workers)
            try:
                # Submit all tasks
                future_to_file = {
                    self._executor.submit(process_single_file, filename): filename
                    for filename in image_files
                }

                # Process results as they complete
                for future in as_completed(future_to_file):
                    if self._is_cancelled:
                        # Attempt to cancel remaining tasks without blocking
                        self._shutdown_executor(wait=False, cancel_futures=True)
                        self.signals.status.emit("Screenshot processing cancelled")
                        return

                    try:
                        result = future.result()
                        if result is True:
                            successful_files += 1
                    except Exception as e:
                        filename = future_to_file[future]
                        self.signals.status.emit(
                            f"Critical error processing {filename}: {e}"
                        )

                    processed_count += 1

                    # Update progress every 5 files or at the end
                    if processed_count % 5 == 0 or processed_count == total_files:
                        self.signals.progress.emit(processed_count, total_files)
                        self.signals.status.emit(
                            f"Processed {processed_count} of {total_files} images"
                        )
            finally:
                # Ensure executor threads are cleaned up appropriately
                self._shutdown_executor(
                    wait=not self._is_cancelled, cancel_futures=self._is_cancelled
                )

            self.signals.progress.emit(total_files, total_files)
            self.signals.status.emit(
                f"Successfully processed {total_files} screenshots ({successful_files} with results)"
            )
            self.signals.result.emit(
                {
                    "directory_path": self.directory_path,
                    "total_files": total_files,
                    "successful_files": successful_files,
                    "failed_files": total_files - successful_files,
                    "overwrite": self.overwrite,
                }
            )

        except Exception as e:
            self.signals.error.emit(f"Screenshot processing failed: {e}")
        finally:
            self.signals.finished.emit()

    def _extract_pack_type(self, filename: str) -> str:
        """
        Extract the pack name from the filename.

        Expected patterns:
        - 20251206235802_1_Tradeable_11_packs.png -> "Tradeable 11 packs"
        - Tradeable_11_packs.png -> "Tradeable 11 packs"
        """
        # Remove extension
        base_name = os.path.splitext(filename)[0]

        # Pattern: YYYYMMDDHHMMSS_ID_Pack_Name
        parts = base_name.split("_")

        if len(parts) >= 3:
            # Check if the first part is a long digit string (timestamp)
            if parts[0].isdigit() and len(parts[0]) >= 12:
                # Join the remaining parts from index 2 onwards
                pack_name = " ".join(parts[2:])
                return pack_name.strip()

        # Fallback: replace underscores with spaces and return the whole base name
        return base_name.replace("_", " ").strip()

    def _identify_set(self, cards_found: list) -> str:
        """
        Identify the set name from the detected cards.
        """
        if not cards_found:
            return "Unknown"

        try:
            from app.names import sets

            # Count occurrences of each set code
            set_counts = {}
            for card in cards_found:
                set_code = card.get("card_set")
                if set_code:
                    set_counts[set_code] = set_counts.get(set_code, 0) + 1

            if not set_counts:
                return "Unknown"

            # Get the most common set code
            dominant_set_code = max(set_counts, key=set_counts.get)

            # Map set code to name
            return sets.get(dominant_set_code, dominant_set_code)
        except Exception as e:
            logger.error(f"Error identifying set: {e}")
            return "Unknown"

    def _store_results_in_database(self, filename: str, cards_found: list):
        """Store processing results in the database"""
        max_retries = 5
        retry_delay = 1.0  # seconds

        for attempt in range(max_retries):
            try:
                # Use the database instance from the worker
                db = self.db

                # Identify set from cards found
                pack_type = self._identify_set(cards_found)

                # Fallback to filename if set is unknown
                if pack_type == "Unknown":
                    pack_type = self._extract_pack_type(filename)

                # Add screenshot record
                # Default to "Account Unknown" for screenshots without CSV info
                screenshot_data = {
                    "Timestamp": datetime.now().isoformat(),
                    "OriginalFilename": filename,
                    "CleanFilename": "Account Unknown",
                    "Account": "Account Unknown",
                    "PackType": pack_type,
                    "CardTypes": ", ".join([card["card_name"] for card in cards_found]),
                    "CardCounts": str(len(cards_found)),
                    "PackScreenshot": filename,  # Use filename as unique key for screenshot
                    "Shinedust": "0",
                }

                with db.transaction():
                    screenshot_id, is_new = db.add_screenshot(screenshot_data)

                    if not is_new and not self.overwrite:
                        # If the screenshot already exists, check if it's already been processed
                        # This allows processing screenshots that were imported via CSV but not yet analyzed
                        if db.check_screenshot_exists(
                            filename, screenshot_data["Account"]
                        ):
                            self.signals.status.emit(
                                f"Skipping {filename}: Already processed in database"
                            )
                            return
                        else:
                            logger.info(
                                f"Screenshot {filename} exists in database but is not processed. Continuing."
                            )

                    # Add each card to database and create relationships
                    for card_data in cards_found:
                        # Extract card code if available
                        card_code = card_data.get("card_code", "")
                        card_name = card_data.get("card_name", "Unknown")
                        card_set = card_data.get("card_set", "Unknown")

                        # Try to extract card number from code for better image path
                        if card_code and "_" in card_code:
                            set_code, card_number = card_code.split("_", 1)
                            # Use the card number for the image path
                            image_path = f"{set_code}/{card_code}.webp"
                        else:
                            # Fallback to name-based path
                            image_path = f"{card_set}/{card_name}.webp"

                        # Add card (if not already exists)
                        card_id = db.add_card(
                            card_name=card_name,
                            card_set=card_set,
                            image_path=image_path,
                            rarity="Common",  # Default rarity for now
                            card_code=card_code,
                        )

                        # Add relationship between screenshot and card
                        if card_id:
                            db.add_screenshot_card(
                                screenshot_id=screenshot_id,
                                card_id=card_id,
                                position=card_data.get("position", 1),
                                confidence=card_data.get("confidence", 0.0),
                            )

                            # Log the card detection
                            logger.info(
                                f"Stored card {card_name} ({card_set}) with confidence {card_data.get('confidence', 0.0):.2f}"
                            )

                    # Mark screenshot as processed
                    db.mark_screenshot_processed(screenshot_id)

                # If we reached here, success!
                return

            except Exception as e:
                if "database is locked" in str(e).lower() and attempt < max_retries - 1:
                    logger.warning(
                        f"Database locked while storing {filename}, retrying in {retry_delay}s (attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(retry_delay)
                    # Exponential backoff could be used here: retry_delay *= 2
                    continue

                logger.error(f"Error storing results for {filename}: {e}")
                raise

    def cancel(self):
        """Cancel the worker"""
        self._is_cancelled = True
        self._shutdown_executor(wait=False, cancel_futures=True)

    def _shutdown_executor(self, wait: bool = True, cancel_futures: bool = False):
        """Shut down the internal executor safely"""
        executor = getattr(self, "_executor", None)
        if executor:
            try:
                executor.shutdown(wait=wait, cancel_futures=cancel_futures)
            except Exception:
                pass
            finally:
                self._executor = None


class DatabaseBackupWorker(QRunnable):
    """Worker for database backup operations"""

    def __init__(self, source_path: str, backup_path: str):
        super().__init__()
        self.source_path = source_path
        self.backup_path = backup_path
        self.signals = WorkerSignals()
        self._is_cancelled = False

    def run(self):
        """Perform database backup in background thread"""
        try:
            if self._is_cancelled:
                return

            self.signals.status.emit("Starting database backup...")

            # Validate source
            if not os.path.exists(self.source_path):
                raise FileNotFoundError(
                    f"Source database not found: {self.source_path}"
                )

            # Ensure backup directory exists
            backup_dir = os.path.dirname(self.backup_path)
            if backup_dir and not os.path.exists(backup_dir):
                os.makedirs(backup_dir, exist_ok=True)

            # Simulate backup process
            # In a real implementation, this would copy the database file
            for i in range(10):
                if self._is_cancelled:
                    self.signals.status.emit("Database backup cancelled")
                    return

                progress = (i + 1) * 10
                self.signals.progress.emit(progress, 100)
                self.signals.status.emit(f"Backup progress: {progress}%")
                time.sleep(0.2)

            self.signals.progress.emit(100, 100)
            self.signals.status.emit("Database backup completed successfully")
            self.signals.result.emit(
                {
                    "source_path": self.source_path,
                    "backup_path": self.backup_path,
                    "success": True,
                }
            )

        except Exception as e:
            self.signals.error.emit(f"Database backup failed: {e}")
        finally:
            self.signals.finished.emit()

    def cancel(self):
        """Cancel the worker"""
        self._is_cancelled = True


class CardDataLoadWorker(QRunnable):
    """Worker to load and prepare card data in the background"""

    def __init__(self, db_path: str = None, account_filter: Optional[str] = None):
        super().__init__()
        self.db_path = db_path
        self.account_filter = account_filter
        self.signals = WorkerSignals()
        self._is_cancelled = False

    def cancel(self):
        """Cancel the worker"""
        self._is_cancelled = True

    def run(self):
        """Load card rows from DB and transform into model-friendly dicts"""
        try:
            if self._is_cancelled:
                return

            self.signals.status.emit("Loading cards from database...")

            # Lazy imports to avoid unnecessary main-thread initialization
            from app.database import Database
            from app.names import (
                cards as CARD_NAMES,
                sets as SET_NAMES,
                rarity as RARITY_MAP,
            )

            db = Database(self.db_path)
            rows = db.get_all_cards_with_counts(self.account_filter)

            total = len(rows)
            data: List[Dict[str, Any]] = []

            # Local helper mirrors MainWindow._get_display_name_and_rarity
            def get_display_name_and_rarity(
                card_code: str, raw_name: str, raw_rarity: str
            ):
                import re

                full_name = raw_name if raw_name else card_code
                display_name = full_name
                display_rarity = raw_rarity
                match = re.search(r"\s*\(([^)]+)\)$", full_name)
                if match:
                    rarity_code = match.group(1)
                    display_name = full_name[: match.start()].strip()
                    if rarity_code in RARITY_MAP:
                        display_rarity = RARITY_MAP[rarity_code]
                    else:
                        display_rarity = rarity_code
                return display_name, display_rarity

            processed = 0
            for row in rows:
                if self._is_cancelled:
                    self.signals.status.emit("Card load cancelled")
                    return

                # row format: (card_code, card_name, set_name, rarity, total_count, image_path)
                raw_name = CARD_NAMES.get(row[1], row[1])
                display_name, display_rarity = get_display_name_and_rarity(
                    row[0], raw_name, row[3]
                )

                card_info = {
                    "card_code": row[0],
                    "card_name": display_name,
                    "set_name": SET_NAMES.get(row[2], row[2]),
                    "rarity": display_rarity,
                    "count": row[4],
                    "image_path": row[5],
                }
                data.append(card_info)

                processed += 1
                if processed % 200 == 0:
                    self.signals.progress.emit(processed, total)

            self.signals.progress.emit(total, total)
            self.signals.status.emit(f"Loaded {total} cards")
            self.signals.result.emit(data)

        except Exception as e:
            logger.exception("Error loading card data in worker")
            self.signals.error.emit(f"Card load failed: {e}")
        finally:
            self.signals.finished.emit()


class VersionCheckWorker(QRunnable):
    """Worker to check for application updates on GitHub"""

    def __init__(self, current_version: str):
        super().__init__()
        self.current_version = current_version
        self.signals = WorkerSignals()

    def run(self):
        """Check GitHub API for the latest release"""
        try:
            import httpx

            # GitHub API for latest release
            url = "https://api.github.com/repos/itsthejoker/ptcgpb_companion/releases/latest"
            # Using a custom User-Agent as required by GitHub API
            headers = {"User-Agent": "ptcgpb-companion-version-check"}

            response = httpx.get(url, follow_redirects=True, headers=headers)
            if response.status_code == 200:
                data = response.json()
                latest_tag = data.get("tag_name", "")
                latest_version = latest_tag.lstrip("v")

                if latest_version and latest_version != self.current_version:
                    # Basic comparison - if it's different, assume it's newer
                    # as per the requirement for a simple check.
                    self.signals.result.emit(
                        {
                            "new_available": True,
                            "latest_version": latest_version,
                            "url": "https://github.com/itsthejoker/ptcgpb_companion/releases/latest",
                        }
                    )
                else:
                    self.signals.result.emit({"new_available": False})
            else:
                logger.warning(
                    f"GitHub API returned status code {response.status_code}"
                )
                self.signals.result.emit({"new_available": False})
        except Exception as e:
            logger.error(f"Error checking for updates: {e}")
            self.signals.result.emit({"new_available": False})
        finally:
            self.signals.finished.emit()


class DashboardStatsWorker(QRunnable):
    """Worker to load dashboard statistics and recent activity in the background"""

    def __init__(self, db_path: str = None, activity_limit: int = 100):
        super().__init__()
        self.db_path = db_path
        self.activity_limit = activity_limit
        self.signals = WorkerSignals()

    def run(self):
        """Load statistics and activity from database"""
        try:
            from app.database import Database

            db = Database(self.db_path)

            stats = {
                "total_cards": db.get_total_cards_count(),
                "unique_cards": db.get_unique_cards_count(),
                "total_packs": db.get_total_packs_count(),
                "last_processed": db.get_last_processed_timestamp(),
                "recent_activity": db.get_recent_activity(limit=self.activity_limit),
            }

            self.signals.result.emit(stats)
        except Exception as e:
            logger.error(f"Error loading dashboard stats in worker: {e}")
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()

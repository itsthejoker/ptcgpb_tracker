"""
Card Counter Workers

Background worker classes for the Card Counter PyQt6 application.
This module provides QRunnable-based workers for long-running operations.
"""

from PyQt6.QtCore import QRunnable, pyqtSignal, QObject, QCoreApplication
from typing import Optional, Dict, Any, List
from datetime import datetime
import os
import csv
import time
import logging
import threading

from django.db.models import Count

from app.utils import PortableSettings, clean_card_name

from django.db import transaction


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

    def __init__(
        self,
        file_path: str,
        task_id: str = None,
        screenshots_dir: str = None,
    ):
        super().__init__()
        self.file_path = file_path
        self.task_id = task_id
        self.screenshots_dir = screenshots_dir
        self.signals = WorkerSignals()
        self._is_cancelled = False

        logger_name = f"{__name__}.{self.__class__.__name__}"
        if self.task_id:
            logger_name += f".{self.task_id}"
        self.logger = logging.getLogger(logger_name)

    def run(self):
        """Process CSV import in background thread"""
        from app.db.models import Screenshot, Account, translate_set_name, CardSet

        try:
            if self._is_cancelled:
                return

            self.signals.status.emit(
                QCoreApplication.translate("CSVImportWorker", "Starting CSV import...")
            )

            # Validate file
            if not os.path.exists(self.file_path):
                raise FileNotFoundError(
                    QCoreApplication.translate(
                        "CSVImportWorker", "CSV file not found: %1"
                    ).replace("%1", self.file_path)
                )

            # Read all rows into memory
            rows = []
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
            except Exception as e:
                raise ValueError(
                    QCoreApplication.translate(
                        "CSVImportWorker", "Failed to parse CSV file: %1"
                    ).replace("%1", str(e))
                )

            total_rows = len(rows)
            if total_rows == 0:
                self.signals.status.emit(
                    QCoreApplication.translate(
                        "CSVImportWorker", "CSV file is empty or only contains header"
                    )
                )
                self.signals.result.emit({"total_rows": 0, "new_rows": 0})
                return

            processed_count = 0
            new_records = 0
            accounts_cache = {}

            self.signals.status.emit(
                QCoreApplication.translate(
                    "CSVImportWorker", "Importing %1 rows..."
                ).replace("%1", str(total_rows))
            )

            # Process in batches to avoid holding a transaction for too long
            # and to allow other threads to write to the database.
            batch_size = 100
            for i in range(0, total_rows, batch_size):
                if self._is_cancelled:
                    break

                batch = rows[i : i + batch_size]
                with transaction.atomic():
                    # Pre-fetch accounts for this batch to reduce queries
                    batch_account_names = {
                        row.get("CleanFilename")
                        for row in batch
                        if row.get("CleanFilename")
                    }
                    missing_account_names = batch_account_names - set(
                        accounts_cache.keys()
                    )
                    if missing_account_names:
                        for acc in Account.objects.filter(
                            name__in=missing_account_names
                        ):
                            accounts_cache[acc.name] = acc

                        still_missing = missing_account_names - set(
                            accounts_cache.keys()
                        )
                        for name in still_missing:
                            acc, _ = Account.objects.get_or_create(name=name)
                            accounts_cache[name] = acc

                    # Pre-fetch existing screenshots for this batch
                    batch_screenshot_names = {
                        row.get("PackScreenshot")
                        for row in batch
                        if row.get("PackScreenshot")
                    }
                    existing_screenshots = {
                        s.name: s
                        for s in Screenshot.objects.filter(
                            name__in=batch_screenshot_names
                        )
                    }

                    to_create = []
                    to_update = []
                    seen_in_batch = set()

                    for row in batch:
                        if self._is_cancelled:
                            break
                        processed_count += 1

                        # Normalize keys to handle case-insensitivity
                        row = {k: v for k, v in row.items() if k is not None}

                        account_name = row.get("CleanFilename")
                        if not account_name:
                            continue

                        account_obj = accounts_cache.get(account_name)

                        if not row.get("PackScreenshot"):
                            # This is a summary row (Shinedust only)
                            if row.get("Shinedust") and account_obj:
                                # Only update if it actually changed to save a query
                                if account_obj.shinedust != str(row["Shinedust"]):
                                    account_obj.shinedust = str(row["Shinedust"])
                                    account_obj.save(update_fields=["shinedust"])
                            continue

                        try:
                            screen_name = row["PackScreenshot"]
                            if screen_name in seen_in_batch:
                                continue
                            seen_in_batch.add(screen_name)

                            # Use only name for get_or_create to avoid unique constraint issues
                            # when other metadata (like timestamp) differs.
                            set_code = translate_set_name(row.get("PackType"))
                            pack_set = None
                            if set_code:
                                try:
                                    pack_set = CardSet(set_code)
                                except ValueError:
                                    pass

                            if screen_name in existing_screenshots:
                                screenshot_obj = existing_screenshots[screen_name]
                                changed = False
                                if screenshot_obj.timestamp != row.get("Timestamp"):
                                    screenshot_obj.timestamp = row.get("Timestamp")
                                    changed = True
                                if screenshot_obj.account_id != account_obj.pk:
                                    screenshot_obj.account = account_obj
                                    changed = True
                                if pack_set and screenshot_obj.set != pack_set:
                                    screenshot_obj.set = pack_set
                                    changed = True

                                if changed:
                                    to_update.append(screenshot_obj)
                            else:
                                to_create.append(
                                    Screenshot(
                                        name=screen_name,
                                        timestamp=row.get("Timestamp"),
                                        account=account_obj,
                                        set=pack_set,
                                    )
                                )
                                new_records += 1
                        except Exception as e:
                            self.signals.status.emit(
                                QCoreApplication.translate(
                                    "CSVImportWorker",
                                    "Error processing screenshot %1: %2",
                                )
                                .replace("%1", row.get("PackScreenshot", "unknown"))
                                .replace("%2", str(e))
                            )
                            self.logger.error(
                                f"Error processing screenshot {row.get('PackScreenshot')}: {e}"
                            )

                    if to_create:
                        Screenshot.objects.bulk_create(to_create)
                    if to_update:
                        Screenshot.objects.bulk_update(
                            to_update, ["timestamp", "account", "set"]
                        )

                # Update progress after each batch
                self.signals.progress.emit(processed_count, total_rows)
                # self.signals.status.emit(f"Imported {processed_count}/{total_rows}...")

            if self._is_cancelled:
                self.signals.status.emit(
                    QCoreApplication.translate(
                        "CSVImportWorker", "CSV import cancelled"
                    )
                )
                return

            self.signals.progress.emit(total_rows, total_rows)
            self.signals.status.emit(
                QCoreApplication.translate(
                    "CSVImportWorker", "Successfully imported %1 packs (%2 new)"
                )
                .replace("%1", str(total_rows))
                .replace("%2", str(new_records))
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
        task_id: str = None,
    ):
        super().__init__()
        self.signals = WorkerSignals()
        self._is_cancelled = False
        self.base_list_url = base_list_url or "https://pocket.limitlesstcg.com/cards"
        self.card_url_template = card_url_template or (
            "https://limitlesstcg.nyc3.cdn.digitaloceanspaces.com/pocket/{set_id}/{set_id}_{card_num}_EN_SM.webp"
        )
        self.max_workers = max_workers or get_max_thread_count()
        self.task_id = task_id

        logger_name = f"{__name__}.{self.__class__.__name__}"
        if self.task_id:
            logger_name += f".{self.task_id}"
        self.logger = logging.getLogger(logger_name)

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
            from settings import BASE_DIR

            # Resolve destination root
            dest_root = BASE_DIR / "resources" / "card_imgs"
            os.makedirs(dest_root, exist_ok=True)

            from app.db.models import Card, CardSet
            from app.names import (
                cards as CARD_NAMES_MAP,
            )
            from app.db.models import Card

            rarity = dict(zip(Card.Rarity.values, Card.Rarity.labels))

            self.signals.status.emit(
                QCoreApplication.translate(
                    "CardArtDownloadWorker", "Fetching card set list…"
                )
            )

            # Fetch list of set IDs
            try:
                resp = httpx.get(self.base_list_url, timeout=30.0)
                resp.raise_for_status()
            except Exception as e:
                raise RuntimeError(
                    QCoreApplication.translate(
                        "CardArtDownloadWorker", "Failed to fetch set list: %1"
                    ).replace("%1", str(e))
                )

            # Parse set IDs using regex to avoid external parser dependency
            html = resp.text or ""
            # matches href="/cards/<set_id>"
            matches = re.findall(r'href\s*=\s*"/cards/([^"]+)"', html)
            set_ids = sorted(list(set(m for m in matches if m)))

            if not set_ids:
                raise RuntimeError(
                    QCoreApplication.translate(
                        "CardArtDownloadWorker", "No set IDs found on the listing page"
                    )
                )

            # Ensure per-set directories
            for set_id in set_ids:
                if self._is_cancelled:
                    return
                os.makedirs(os.path.join(dest_root, set_id), exist_ok=True)

            total_estimate = len(set_ids) * 500  # rough estimate for progress
            processed = 0

            from concurrent.futures import ThreadPoolExecutor, as_completed

            self.signals.status.emit(
                QCoreApplication.translate(
                    "CardArtDownloadWorker",
                    "Downloading card art for %1 sets using %2 threads…",
                )
                .replace("%1", str(len(set_ids)))
                .replace("%2", str(self.max_workers))
            )

            def download_set(set_id: str) -> int:
                from app.db.models import Card

                RARITY_MAP = dict(zip(Card.Rarity.values, Card.Rarity.labels))

                # Use a child logger that includes the thread name
                logger = self.logger.getChild(threading.current_thread().name)

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

                        card_code = f"{set_id}_{card_num}"
                        raw_name = CARD_NAMES_MAP.get(card_code, card_code)

                        display_name = raw_name
                        display_rarity = None

                        # Match rarity from name, e.g. "Bulbasaur (1D)"
                        rarity_match = re.search(r"\s*\(([^)]+)\)$", raw_name)
                        if rarity_match:
                            rarity_code = rarity_match.group(1)
                            display_name = raw_name[: rarity_match.start()].strip()
                            if rarity_code in RARITY_MAP:
                                display_rarity = rarity_code

                        try:
                            valid_set = CardSet(set_id)
                        except ValueError:
                            valid_set = None

                        Card.objects.update_or_create(
                            code=card_code,
                            set=valid_set.value if valid_set else set_id,
                            defaults={
                                "name": display_name,
                                "image_path": f"{set_id}/{filename}",
                                "rarity": display_rarity,
                            },
                        )

                        images_saved += 1
                    except Exception as e:
                        logger.error(f"Error saving card {set_id}_{card_num}: {e}")
                        continue
                return images_saved

            total_saved = 0
            self._executor = ThreadPoolExecutor(
                max_workers=self.max_workers,
                thread_name_prefix=f"ArtDL-{self.task_id or 'pool'}",
            )
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

                    # Also update image_path for cards that might have been downloaded but not in DB
                    # (though update_or_create above should handle most cases during the download)

                    self.signals.status.emit("pHashes precomputed and saved.")
                except Exception as e:
                    self.logger.error(f"Failed to precompute pHashes: {e}")
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
        self._db_lock = threading.Lock()

        logger_name = f"{__name__}.{self.__class__.__name__}"
        if self.task_id:
            logger_name += f".{self.task_id}"
        self.logger = logging.getLogger(logger_name)

    def run(self):
        """Process screenshot images in background thread"""
        from app.db.models import (
            Screenshot,
            Card,
            ScreenshotCard,
            Account,
            CardSet,
            translate_set_name,
        )

        try:
            if self._is_cancelled:
                return

            self.signals.status.emit(
                QCoreApplication.translate(
                    "ScreenshotProcessingWorker", "Starting screenshot processing..."
                )
            )

            # Validate directory
            if not os.path.isdir(self.directory_path):
                raise FileNotFoundError(
                    QCoreApplication.translate(
                        "ScreenshotProcessingWorker", "Directory not found: %1"
                    ).replace("%1", self.directory_path)
                )

            # Get list of image files in batches to identify unprocessed ones first
            image_extensions = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")
            image_files = []
            all_found_count = 0

            self.signals.status.emit(
                QCoreApplication.translate(
                    "ScreenshotProcessingWorker", "Scanning directory for images..."
                )
            )

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
                            unprocessed_names = Screenshot.objects.filter(
                                name__in=batch, processed=True
                            ).values_list("name", flat=True)
                            unprocessed = [
                                f for f in batch if f not in unprocessed_names
                            ]
                            image_files.extend(unprocessed)
                            batch = []
                            self.signals.status.emit(
                                QCoreApplication.translate(
                                    "ScreenshotProcessingWorker",
                                    "Scanned %1 files, found %2 new images...",
                                )
                                .replace("%1", str(all_found_count))
                                .replace("%2", str(len(image_files)))
                            )

            if not self.overwrite and batch:
                unprocessed_names = Screenshot.objects.filter(
                    name__in=batch, processed=True
                ).values_list("name", flat=True)
                unprocessed = [f for f in batch if f not in unprocessed_names]
                image_files.extend(unprocessed)

            total_files = len(image_files)
            if total_files == 0:
                if all_found_count > 0:
                    self.signals.status.emit(
                        QCoreApplication.translate(
                            "ScreenshotProcessingWorker",
                            "All images already processed.",
                        )
                    )
                    self.signals.progress.emit(100, 100)
                    self.signals.result.emit(
                        {
                            "directory_path": self.directory_path,
                            "total_files": 0,
                            "successful_files": 0,
                            "failed_files": 0,
                            "overwrite": self.overwrite,
                            "message": QCoreApplication.translate(
                                "ScreenshotProcessingWorker",
                                "All images already processed",
                            ),
                        }
                    )
                    return
                else:
                    raise ValueError(
                        QCoreApplication.translate(
                            "ScreenshotProcessingWorker",
                            "No image files found in directory",
                        )
                    )

            self.signals.status.emit(
                QCoreApplication.translate(
                    "ScreenshotProcessingWorker",
                    "Found %1 images to process. Loading workers...",
                ).replace("%1", str(total_files))
            )

            # Initialize image processor
            from app.image_processing import ImageProcessor
            from settings import BASE_DIR

            template_dir = BASE_DIR / "resources" / "card_imgs"
            processor = ImageProcessor(template_dir)

            # Load card templates from resources
            try:
                if os.path.isdir(template_dir):
                    # Templates are already loaded by constructor, but we want to log it
                    self.signals.status.emit(
                        QCoreApplication.translate(
                            "ScreenshotProcessingWorker", "Loaded %1 card templates"
                        ).replace("%1", str(processor.get_template_count()))
                    )
                else:
                    self.signals.status.emit(
                        QCoreApplication.translate(
                            "ScreenshotProcessingWorker",
                            "Error: Template directory not found: %1",
                        ).replace("%1", str(template_dir))
                    )
                    raise FileNotFoundError(
                        QCoreApplication.translate(
                            "ScreenshotProcessingWorker",
                            "Template directory not found: %1",
                        ).replace("%1", str(template_dir))
                    )
            except Exception as template_error:
                self.signals.status.emit(
                    QCoreApplication.translate(
                        "ScreenshotProcessingWorker",
                        "Error: Could not load card templates: %1",
                    ).replace("%1", str(template_error))
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
                # Use a child logger that includes the thread name to distinguish parallel workers
                logger = self.logger.getChild(threading.current_thread().name)

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
                        logger.debug(
                            f"Blank image detected ({file_size} bytes) in {filename}. Marking as processed."
                        )
                        # Reuse storage routine with no detected cards
                        self._store_results_in_database(
                            filename, [], full_path=file_path, logger=logger
                        )
                        # Do not count as "with results" but it's successfully handled
                        return False

                    # Try to get existing set if any (e.g. from CSV import)
                    existing_set = (
                        Screenshot.objects.filter(name=filename)
                        .values_list("set", flat=True)
                        .first()
                    )

                    # Process the image with OpenCV
                    cards_found = processor.process_screenshot(
                        file_path, force_set=existing_set
                    )

                    # Store results in database
                    if cards_found:
                        self._store_results_in_database(
                            filename, cards_found, full_path=file_path, logger=logger
                        )
                        return True
                    else:
                        logger.info(f"No cards detected in {filename}")
                        return False
                except Exception as e:
                    logger.error(f"Error processing {filename}: {e}")
                    return False

            self._executor = ThreadPoolExecutor(
                max_workers=max_workers,
                thread_name_prefix=f"ImgProc-{self.task_id or 'pool'}",
            )
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
                        self.signals.status.emit(
                            QCoreApplication.translate(
                                "ScreenshotProcessingWorker",
                                "Screenshot processing cancelled",
                            )
                        )
                        return

                    try:
                        result = future.result()
                        if result is True:
                            successful_files += 1
                    except Exception as e:
                        filename = future_to_file[future]
                        self.signals.status.emit(
                            QCoreApplication.translate(
                                "ScreenshotProcessingWorker",
                                "Critical error processing %1: %2",
                            )
                            .replace("%1", filename)
                            .replace("%2", str(e))
                        )

                    processed_count += 1

                    # Update progress every 5 files or at the end
                    if processed_count % 5 == 0 or processed_count == total_files:
                        self.signals.progress.emit(processed_count, total_files)
                        self.signals.status.emit(
                            QCoreApplication.translate(
                                "ScreenshotProcessingWorker",
                                "Processed %1 of %2 images",
                            )
                            .replace("%1", str(processed_count))
                            .replace("%2", str(total_files))
                        )
            finally:
                # Ensure executor threads are cleaned up appropriately
                self._shutdown_executor(
                    wait=not self._is_cancelled, cancel_futures=self._is_cancelled
                )

            self.signals.progress.emit(total_files, total_files)
            self.signals.status.emit(
                QCoreApplication.translate(
                    "ScreenshotProcessingWorker",
                    "Successfully processed %1 screenshots (%2 with results)",
                )
                .replace("%1", str(total_files))
                .replace("%2", str(successful_files))
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
            self.signals.error.emit(
                QCoreApplication.translate(
                    "ScreenshotProcessingWorker", "Screenshot processing failed: %1"
                ).replace("%1", str(e))
            )
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

    def _identify_set(self, cards_found: list, logger: logging.Logger = None) -> str:
        """
        Identify the set name from the detected cards.
        """
        if logger is None:
            logger = self.logger

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

    def _store_results_in_database(
        self,
        filename: str,
        cards_found: list,
        full_path: str = None,
        logger: logging.Logger = None,
    ):
        """Store processing results in the database"""
        from app.db.models import (
            Screenshot,
            Card,
            ScreenshotCard,
            Account,
            CardSet,
            translate_set_name,
        )

        if logger is None:
            logger = self.logger

        with self._db_lock:
            # Identify set from cards found
            pack_type = self._identify_set(cards_found, logger=logger)

            # Fallback to filename if set is unknown
            if pack_type == "Unknown":
                pack_type = self._extract_pack_type(filename)

            try:
                with transaction.atomic():
                    # Check if screenshot already exists (might have been created by CSVImportWorker)
                    screenshot_obj, created = Screenshot.objects.get_or_create(
                        name=filename,
                        defaults={
                            "timestamp": datetime.now().isoformat(),
                            "set": (
                                CardSet(translate_set_name(pack_type))
                                if translate_set_name(pack_type)
                                else None
                            ),
                        },
                    )

                    if not created and not self.overwrite and screenshot_obj.processed:
                        self.signals.status.emit(
                            f"Skipping {filename}: Already processed in database"
                        )
                        return

                    # If we are here, we are either newly processing or overwriting.
                    # Clear existing cards to ensure we only have the latest detection results.
                    ScreenshotCard.objects.filter(screenshot=screenshot_obj).delete()

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

                        # Extract rarity from name if possible
                        rarity = "1D"
                        if "(" in card_name:
                            import re

                            match = re.search(r"\(([^)]+)\)", card_name)
                            if match:
                                rarity = match.group(1)

                        # Add card (if not already exists)
                        # Note: Card table has unique_together = (("code", "set"),)
                        card_obj, created = Card.objects.get_or_create(
                            code=card_code,
                            set=card_set,
                            defaults={
                                "name": card_name,
                                "image_path": image_path,
                                "rarity": rarity,
                            },
                        )

                        # If card already exists but has default rarity, update it
                        if not created and card_obj.rarity == "1D" and rarity != "1D":
                            card_obj.rarity = rarity
                            card_obj.save()

                        # Add relationship between screenshot and card
                        ScreenshotCard.objects.create(
                            screenshot=screenshot_obj,
                            card=card_obj,
                            position=card_data.get("position", 1),
                            confidence=card_data.get("confidence", 0.0),
                        )

                        # Log the card detection
                        logger.info(
                            f"Stored card {card_name} ({card_set}) with confidence {card_data.get('confidence', 0.0):.2f}"
                        )

                    # Mark screenshot as processed
                    screenshot_obj.processed = True
                    screenshot_obj.save()

            except Exception as e:
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

    def __init__(self, source_path: str, backup_path: str, task_id: str = None):
        super().__init__()
        self.source_path = source_path
        self.backup_path = backup_path
        self.task_id = task_id
        self.signals = WorkerSignals()
        self._is_cancelled = False

        logger_name = f"{__name__}.{self.__class__.__name__}"
        if self.task_id:
            logger_name += f".{self.task_id}"
        self.logger = logging.getLogger(logger_name)

    def run(self):
        """Perform database backup in background thread"""
        try:
            if self._is_cancelled:
                return

            self.signals.status.emit(
                QCoreApplication.translate(
                    "DatabaseBackupWorker", "Starting database backup..."
                )
            )

            # Validate source
            if not os.path.exists(self.source_path):
                raise FileNotFoundError(
                    QCoreApplication.translate(
                        "DatabaseBackupWorker", "Source database not found: %1"
                    ).replace("%1", self.source_path)
                )

            # Ensure backup directory exists
            backup_dir = os.path.dirname(self.backup_path)
            if backup_dir and not os.path.exists(backup_dir):
                os.makedirs(backup_dir, exist_ok=True)

            # Simulate backup process
            # In a real implementation, this would copy the database file
            for i in range(10):
                if self._is_cancelled:
                    self.signals.status.emit(
                        QCoreApplication.translate(
                            "DatabaseBackupWorker", "Database backup cancelled"
                        )
                    )
                    return

                progress = (i + 1) * 10
                self.signals.progress.emit(progress, 100)
                self.signals.status.emit(
                    QCoreApplication.translate(
                        "DatabaseBackupWorker", "Backup progress: %1%"
                    ).replace("%1", str(progress))
                )
                time.sleep(0.2)

            self.signals.progress.emit(100, 100)
            self.signals.status.emit(
                QCoreApplication.translate(
                    "DatabaseBackupWorker", "Database backup completed successfully"
                )
            )
            self.signals.result.emit(
                {
                    "source_path": self.source_path,
                    "backup_path": self.backup_path,
                    "success": True,
                }
            )

        except Exception as e:
            self.signals.error.emit(
                QCoreApplication.translate(
                    "DatabaseBackupWorker", "Database backup failed: %1"
                ).replace("%1", str(e))
            )
        finally:
            self.signals.finished.emit()

    def cancel(self):
        """Cancel the worker"""
        self._is_cancelled = True


class CardDataLoadWorker(QRunnable):
    """Worker to load and prepare card data in the background"""

    def __init__(
        self,
        account_filter: Optional[str] = None,
        task_id: str = None,
    ):
        super().__init__()
        self.account_filter = account_filter
        self.task_id = task_id
        self.signals = WorkerSignals()
        self._is_cancelled = False

        logger_name = f"{__name__}.{self.__class__.__name__}"
        if self.task_id:
            logger_name += f".{self.task_id}"
        self.logger = logging.getLogger(logger_name)

    def cancel(self):
        """Cancel the worker"""
        self._is_cancelled = True

    def run(self):
        """Load card rows from DB and transform into model-friendly dicts"""
        try:
            if self._is_cancelled:
                return

            self.signals.status.emit(
                QCoreApplication.translate(
                    "CardDataLoadWorker", "Loading cards from database..."
                )
            )

            # Lazy imports to avoid unnecessary main-thread initialization
            from app.db.models import Card, CardSet

            rarity_map = Card.Rarity.rarity_map()
            set_names = CardSet.name_map()

            query = Card.objects.all()
            if self.account_filter:
                query = query.filter(
                    screenshotcard__screenshot__account__name=self.account_filter
                )

            query = query.annotate(total_count=Count("screenshotcard"))

            total = query.count()
            data: List[Dict[str, Any]] = []

            processed = 0
            for card in query:
                if self._is_cancelled:
                    self.signals.status.emit(
                        QCoreApplication.translate(
                            "CardDataLoadWorker", "Card load cancelled"
                        )
                    )
                    return

                # card.rarity is the code (e.g. "1D"), we want the display name
                display_rarity = (
                    rarity_map.get(card.rarity, card.rarity) if card.rarity else ""
                )

                card_info = {
                    "card_code": card.code,
                    "card_name": clean_card_name(card.name),
                    "set_name": set_names.get(card.set, card.set) or "",
                    "rarity": display_rarity,
                    "count": getattr(card, "total_count", 0),
                    "image_path": card.image_path,
                }
                data.append(card_info)

                processed += 1
                if processed % 200 == 0:
                    self.signals.progress.emit(processed, total)

            self.signals.progress.emit(total, total)
            self.signals.status.emit(
                QCoreApplication.translate(
                    "CardDataLoadWorker", "Loaded %1 cards"
                ).replace("%1", str(total))
            )
            self.signals.result.emit(data)

        except Exception as e:
            self.logger.exception("Error loading card data in worker")
            self.signals.error.emit(
                QCoreApplication.translate(
                    "CardDataLoadWorker", "Card load failed: %1"
                ).replace("%1", str(e))
            )
        finally:
            self.signals.finished.emit()


class VersionCheckWorker(QRunnable):
    """Worker to check for application updates on GitHub"""

    def __init__(self, current_version: str, task_id: str = None):
        super().__init__()
        self.current_version = current_version
        self.task_id = task_id
        self.signals = WorkerSignals()

        logger_name = f"{__name__}.{self.__class__.__name__}"
        if self.task_id:
            logger_name += f".{self.task_id}"
        self.logger = logging.getLogger(logger_name)

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
                self.logger.warning(
                    f"GitHub API returned status code {response.status_code}"
                )
                self.signals.result.emit({"new_available": False})
        except Exception as e:
            self.logger.error(f"Error checking for updates: {e}")
            self.signals.result.emit({"new_available": False})
        finally:
            self.signals.finished.emit()


class DashboardStatsWorker(QRunnable):
    """Worker to load dashboard statistics and recent activity in the background"""

    def __init__(self, activity_limit: int = 100, task_id: str = None):
        super().__init__()
        self.activity_limit = activity_limit
        self.task_id = task_id
        self.signals = WorkerSignals()

        logger_name = f"{__name__}.{self.__class__.__name__}"
        if self.task_id:
            logger_name += f".{self.task_id}"
        self.logger = logging.getLogger(logger_name)

    def run(self):
        """Load statistics and activity from database"""
        try:
            from app.db.models import Account, Screenshot, ScreenshotCard
            from django.utils.timezone import now

            # Use aggregate for basic stats
            total_cards = ScreenshotCard.objects.count()
            unique_cards = (
                ScreenshotCard.objects.values("card__code").distinct().count()
            )
            total_packs = Screenshot.objects.count()

            try:
                last_processed = (
                    Screenshot.objects.filter(processed=True)
                    .latest("created_at")
                    .created_at
                )
            except Screenshot.DoesNotExist:
                last_processed = None

            # Get recent activity
            recent_screenshots = Screenshot.objects.filter(processed=True).order_by(
                "-created_at"
            )[: self.activity_limit]
            recent_activity = []
            for ss in recent_screenshots:
                # Get card names as a list to avoid issues with QuerySet evaluation in join
                card_names = list(
                    ss.screenshotcard_set.values_list("card__name", flat=True)
                )

                # Format timestamp consistently with what main_window expects (naive ISO string)
                if ss.created_at:
                    ts = ss.created_at
                    # Ensure it's naive for consistent string comparison in the UI
                    if ts.tzinfo is not None:
                        ts = ts.astimezone().replace(tzinfo=None)
                    ts_str = ts.isoformat(timespec="seconds")
                else:
                    ts_str = datetime.now().isoformat(timespec="seconds")

                recent_activity.append(
                    {
                        "timestamp": ts_str,
                        "description": QCoreApplication.translate(
                            "DashboardStatsWorker", "Processed %1 (%2)"
                        )
                        .replace("%1", ss.name)
                        .replace("%2", ", ".join(card_names)),
                    }
                )

            stats = {
                "total_cards": total_cards,
                "unique_cards": unique_cards,
                "total_packs": total_packs,
                "last_processed": last_processed,
                "recent_activity": recent_activity,
            }

            self.signals.result.emit(stats)
        except Exception as e:
            self.logger.error(f"Error loading dashboard stats in worker: {e}")
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()

"""
Card Counter Image Processing Module

Image processing functionality for the Card Counter application.
This module provides card identification from screenshots using OpenCV.
"""

import cv2
import numpy as np
import os
import json
import imagehash
from typing import List, Dict, Any, Tuple
from PIL import Image
import logging

logger = logging.getLogger(__name__)


class ImageProcessor:
    """
    Image processing class for Card Counter application

    Provides functionality for identifying cards in screenshot images.
    """

    def __init__(self, card_imgs_dir: str = "card_imgs"):
        """Initialize the image processor"""
        self.card_imgs_dir = card_imgs_dir
        self.card_database = self._load_card_database()
        self.card_names = self._load_card_names()

        # Pre-calculated templates for performance
        self.color_templates = {}
        self.phash_templates = {}

        # Vectorized data structures for performance
        self.phash_matrix = None
        self.phash_metadata = []
        self.template_vectors = {}  # {set_name: {'matrix': np.array, 'metadata': list}}
        self.match_width, self.match_height = 92, 128

        if self.card_database:
            self._prepare_templates()

    def _load_phashes(self) -> bool:
        """Load pHashes from phashes.json if it exists"""
        hash_file = os.path.join(self.card_imgs_dir, "phashes.json")
        if not os.path.exists(hash_file):
            return False

        try:
            with open(hash_file, "r") as f:
                data = json.load(f)
                for set_name, cards in data.items():
                    if set_name not in self.phash_templates:
                        self.phash_templates[set_name] = {}
                    for card_name, hex_hash in cards.items():
                        self.phash_templates[set_name][card_name] = imagehash.hex_to_hash(
                            hex_hash
                        )
            logger.info(f"Loaded pHashes from {hash_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to load pHashes from {hash_file}: {e}")
            return False

    def _save_phashes(self):
        """Save pHashes to phashes.json"""
        hash_file = os.path.join(self.card_imgs_dir, "phashes.json")
        try:
            data = {}
            for set_name, cards in self.phash_templates.items():
                data[set_name] = {}
                for card_name, h in cards.items():
                    data[set_name][card_name] = str(h)

            with open(hash_file, "w") as f:
                json.dump(data, f, indent=4)
            logger.info(f"Saved pHashes to {hash_file}")
        except Exception as e:
            logger.error(f"Failed to save pHashes to {hash_file}: {e}")

    def _load_card_database(self) -> Dict[str, Dict[str, np.ndarray]]:
        """Load all card images from the card_imgs directory"""
        card_db = {}

        if not os.path.exists(self.card_imgs_dir):
            print(f"Card images directory not found: {self.card_imgs_dir}")
            return card_db

        # Walk through all subdirectories (sets)
        for set_name in os.listdir(self.card_imgs_dir):
            set_path = os.path.join(self.card_imgs_dir, set_name)

            if not os.path.isdir(set_path):
                continue

            # Initialize set in database
            if set_name not in card_db:
                card_db[set_name] = {}

            # Load all card images in this set
            for card_file in os.listdir(set_path):
                if card_file.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                    card_name = os.path.splitext(card_file)[0]
                    card_path = os.path.join(set_path, card_file)

                    try:
                        # Load and preprocess the card image
                        card_image = self._load_and_preprocess_card(card_path)
                        if card_image is not None:
                            card_db[set_name][card_name] = card_image
                    except Exception as e:
                        print(f"Error loading card {card_name} from {set_name}: {e}")

        return card_db

    def _load_card_names(self) -> Dict[str, str]:
        """Load card names mapping from names.py"""
        try:
            from app import names

            return names.cards
        except ImportError:
            print("names.py not found, using original card names")
            return {}

    def _get_display_name(self, card_name: str, set_name: str) -> str:
        """Get the display name for a card using the names mapping"""
        # Try to find the card in the names mapping

        # 1. Try the card_name directly (if it already includes the set prefix)
        if card_name in self.card_names:
            return self.card_names[card_name]

        # 2. Try set_name + "_" + card_name
        # The format in names.py is like "A1_1" for set A1, card 1
        mapping_key = f"{set_name}_{card_name}"

        if mapping_key in self.card_names:
            return self.card_names[mapping_key]
        else:
            # Fallback to original name if not found
            return card_name

    def _load_and_preprocess_card(self, card_path: str) -> np.ndarray:
        """Load and preprocess a single card image at full resolution"""
        try:
            # Load image using PIL and convert to RGB
            pil_image = Image.open(card_path)

            # Convert to numpy array
            image = np.array(pil_image)

            # Convert to RGB if needed (from RGBA or grayscale)
            if len(image.shape) == 3 and image.shape[2] == 4:  # RGBA
                image = cv2.cvtColor(image, cv2.COLOR_RGBA2RGB)
            elif len(image.shape) == 2:  # Grayscale
                image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)

            # Keep the card at its original resolution for better matching accuracy
            # Full-size cards are typically 367x512 pixels
            return image
        except Exception as e:
            print(f"Error processing card image {card_path}: {e}")
            return None

    def _preprocess_screenshot(self, screenshot_path: str) -> np.ndarray:
        """Load and preprocess a screenshot image"""
        try:
            # Load image
            pil_image = Image.open(screenshot_path)
            image = np.array(pil_image)

            # Convert to RGB if needed (from RGBA)
            if len(image.shape) == 3 and image.shape[2] == 4:  # RGBA
                image = cv2.cvtColor(image, cv2.COLOR_RGBA2RGB)
            elif len(image.shape) == 2:  # Grayscale
                image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)

            return image
        except Exception as e:
            print(f"Error processing screenshot {screenshot_path}: {e}")
            return None

    def load_card_templates(self, template_dir: str):
        """
        Load card templates from directory

        Args:
            template_dir: Directory containing card template images
        """
        try:
            logger.info(f"Loading card templates from {template_dir}")

            # Check if directory exists
            if not os.path.isdir(template_dir):
                raise FileNotFoundError(f"Template directory not found: {template_dir}")

            # Update card_imgs_dir and reload database
            self.card_imgs_dir = template_dir
            self.card_database = self._load_card_database()

            if self.card_database:
                self._prepare_templates()  # Optimization: Pre-calculate versions
                template_count = self.get_template_count()
                logger.info(f"Successfully loaded {template_count} card templates")
                self.loaded = True
            else:
                raise ValueError(f"No valid card templates found in {template_dir}")

        except Exception as e:
            logger.error(f"Failed to load card templates: {e}")
            raise

    def _prepare_templates(self):
        """Pre-calculate versions of all templates and compute pHashes"""
        self.color_templates = {}
        self.phash_templates = {}

        logger.info("Preparing templates and computing pHashes")

        # Try to load existing hashes
        self._load_phashes()
        new_hashes_computed = False

        for set_name, cards in self.card_database.items():
            self.color_templates[set_name] = {}
            if set_name not in self.phash_templates:
                self.phash_templates[set_name] = {}

            for card_name, template in cards.items():
                # 1. Matching resolution color template
                small = cv2.resize(template, (self.match_width, self.match_height))
                self.color_templates[set_name][card_name] = small

                # 2. pHash (computed from full image for better accuracy)
                if card_name not in self.phash_templates[set_name]:
                    template_pil = Image.fromarray(template)
                    self.phash_templates[set_name][card_name] = imagehash.phash(
                        template_pil
                    )
                    new_hashes_computed = True

        if new_hashes_computed:
            self._save_phashes()

        self._rebuild_vectorized_data()

        # Clear large full-size caches to save memory
        self.card_database = {}
        self.color_templates = {}

    def _rebuild_vectorized_data(self):
        """Build vectorized data structures for faster matching"""
        # 1. Rebuild pHash matrix
        phash_list = []
        self.phash_metadata = []

        for set_name, cards in self.phash_templates.items():
            for card_name, h in cards.items():
                phash_list.append(h.hash.flatten())
                self.phash_metadata.append((set_name, card_name))

        if phash_list:
            self.phash_matrix = np.array(phash_list)
        else:
            self.phash_matrix = None

        # 2. Rebuild template matrices for detailed search
        self.template_vectors = {}

        logger.info(
            f"Vectorizing templates at {self.match_width}x{self.match_height}..."
        )
        for set_name, cards in self.color_templates.items():
            vectors = []
            metadata = []
            for card_name, color_img in cards.items():
                # Normalize (already resized in _prepare_templates)
                vec = color_img.astype(np.float32).flatten()
                vec -= np.mean(vec)
                norm = np.linalg.norm(vec)
                if norm > 0:
                    vec /= norm
                vectors.append(vec)
                metadata.append(card_name)

            if vectors:
                self.template_vectors[set_name] = {
                    "matrix": np.array(vectors),
                    "metadata": metadata,
                }

    def process_screenshot(self, image_path: str) -> List[Dict[str, Any]]:
        """
        Process a screenshot to identify cards using fixed position detection

        Args:
            image_path: Path to screenshot image

        Returns:
            List[Dict]: List of identified cards with positions and confidence scores
        """
        if not self.phash_templates:
            raise RuntimeError(
                "Card templates not loaded. Call load_card_templates() first."
            )

        try:
            logger.info(f"Processing screenshot: {image_path}")

            # Load and preprocess screenshot
            screenshot = self._preprocess_screenshot(image_path)

            if screenshot is None:
                logger.warning(f"Failed to load screenshot: {image_path}")
                return []

            logger.info(f"Screenshot loaded: {screenshot.shape}")

            # Detect card positions using fixed layout
            card_positions = self._detect_card_positions(screenshot)

            num_cards = len(card_positions)
            logger.info(f"Detected {num_cards} card positions")

            # If 4 cards, it's always A4b / Deluxe Pack Ex
            # If 5 or 6 cards, it's guaranteed NOT to be A4b
            forced_set = "A4b" if num_cards == 4 else None
            excluded_sets = ["A4b"] if num_cards in (5, 6) else []

            if forced_set:
                logger.info(f"Four-card pack detected, forcing set to {forced_set}")
            if excluded_sets:
                logger.info(f"{num_cards}-card pack detected, excluding sets: {excluded_sets}")

            # Stage 1: Initial identification for all cards
            initial_results = []
            set_counts = {}

            for i, (x, y, w, h) in enumerate(card_positions):
                logger.info(f"Initial scan: card {i+1} at position ({x}, {y})")
                card_region = screenshot[y : y + h, x : x + w]
                best_match = self._find_best_card_match(
                    card_region, force_set=forced_set, exclude_sets=excluded_sets
                )

                initial_results.append(
                    {
                        "position": i + 1,
                        "best_match": best_match,
                        "x": x,
                        "y": y,
                        "w": w,
                        "h": h,
                        "card_region": card_region,
                    }
                )

                # Use slightly lower threshold for majority set identification
                if best_match and best_match["confidence"] > 0.2:
                    card_set = best_match["card_set"]
                    set_counts[card_set] = set_counts.get(card_set, 0) + 1

            # Determine majority set by weighted confidence
            majority_set = forced_set
            if not majority_set and set_counts:
                # Sum up confidence for each set to find the most likely set for the whole pack
                set_weights = {}
                for result in initial_results:
                    bm = result["best_match"]
                    if bm and bm["confidence"] > 0.2:
                        s = bm["card_set"]
                        set_weights[s] = set_weights.get(s, 0.0) + bm["confidence"]
                
                if set_weights:
                    majority_set = max(set_weights.items(), key=lambda x: x[1])[0]
                    logger.info(f"Majority set identified (weighted): {majority_set}")

            # Stage 2: Re-process outliers if a majority set exists
            detected_cards = []
            for result in initial_results:
                best_match = result["best_match"]
                i = result["position"]

                is_outlier = False
                if not best_match:
                    is_outlier = True
                elif majority_set and best_match["card_set"] != majority_set:
                    # All cards in a single screenshot are guaranteed to be from a single set.
                    # So if it doesn't match the majority set, it's an outlier.
                    is_outlier = True
                    logger.info(
                        f"Card at position {i} belongs to different set ({best_match['card_set']}) but we are guaranteed a single set, forcing to {majority_set}"
                    )

                if is_outlier and majority_set:
                    logger.info(
                        f"Re-scanning outlier card {i} in majority set {majority_set} with detailed search"
                    )
                    new_match = self._find_best_card_match(
                        result["card_region"],
                        force_set=majority_set,
                        force_detailed=True,
                    )

                    # Only update if the new match is at least somewhat decent
                    if new_match and new_match["confidence"] > 0.2:
                        best_match = new_match
                    elif not best_match:
                        best_match = new_match

                # Final check with lower threshold
                if best_match and best_match["confidence"] > 0.2:
                    # Get the display name for this card
                    display_name = self._get_display_name(
                        best_match["card_name"], best_match["card_set"]
                    )
                    logger.info(
                        f"Final result card {i}: {display_name} (confidence: {best_match['confidence']:.2f})"
                    )

                    detected_cards.append(
                        {
                            "position": i,
                            "card_code": best_match["card_name"],
                            "card_name": display_name,
                            "card_set": best_match["card_set"],
                            "confidence": best_match["confidence"],
                            "x": result["x"],
                            "y": result["y"],
                            "width": result["w"],
                            "height": result["h"],
                        }
                    )
                else:
                    logger.info(f"No card match found for position {i}")

            logger.info(f"Found {len(detected_cards)} cards in {image_path}")
            return detected_cards

        except Exception as e:
            logger.error(f"Failed to process screenshot {image_path}: {e}")
            raise

    def _detect_card_positions(
        self, screenshot: np.ndarray
    ) -> List[Tuple[int, int, int, int]]:
        """
        Detect card positions in a screenshot using the exact pixel placements

        Args:
            screenshot: Screenshot image as numpy array

        Returns:
            List[Tuple]: List of (x, y, width, height) tuples for card positions
        """
        height, width = screenshot.shape[:2]

        # Base resolution that the original coordinates were designed for (240x227)
        base_w, base_h = 240, 227

        # Calculate scaling factors
        scale_x = width / base_w
        scale_y = height / base_h

        def scale_pos(pos):
            x, y, w, h = pos
            return (
                int(round(x * scale_x)),
                int(round(y * scale_y)),
                int(round(w * scale_x)),
                int(round(h * scale_y)),
            )

        # #e7f0f7 in grayscale ≈ 239
        background_threshold = 235

        # Detect layout: check if there are 2 or 3 cards on top row
        det_top_x, det_top_y, det_top_w, det_top_h = scale_pos((0, 8, 30, 50))

        if det_top_y + det_top_h <= height and det_top_x + det_top_w <= width:
            detection_region_top = screenshot[
                det_top_y : det_top_y + det_top_h, det_top_x : det_top_x + det_top_w
            ]
            avg_color_top = np.mean(detection_region_top)

            if avg_color_top > background_threshold:
                # 2 cards on top row
                top_base = [
                    (39, 5, 75, 106),  # position 1
                    (124, 5, 75, 106),  # position 2
                ]
            else:
                # 3 cards on top row
                top_base = [
                    (0, 5, 75, 106),  # position 1
                    (81, 5, 75, 106),  # position 2
                    (164, 5, 75, 106),  # position 3
                ]
        else:
            # Fallback to 3-card layout
            top_base = [
                (0, 5, 75, 106),
                (81, 5, 75, 106),
                (164, 5, 75, 106),
            ]

        top_row_positions = [scale_pos(p) for p in top_base]

        # Detect layout: check if there are 2 or 3 cards on bottom row
        # Scale the detection rectangle: (x=0, y=124, w=30, h=50)
        det_x, det_y, det_w, det_h = scale_pos((0, 124, 30, 50))

        if det_y + det_h <= height and det_x + det_w <= width:
            detection_region = screenshot[det_y : det_y + det_h, det_x : det_x + det_w]
            avg_color = np.mean(detection_region)

            if avg_color > background_threshold:
                # 2 cards on bottom row
                bottom_base = [
                    (39, 121, 75, 106),  # position 4
                    (124, 121, 75, 106),  # position 5
                ]
            else:
                # 3 cards on bottom row
                bottom_base = [
                    (0, 121, 75, 106),  # position 4
                    (81, 121, 75, 106),  # position 5
                    (164, 121, 75, 106),  # position 6
                ]
        else:
            # Fallback to 2-card layout
            bottom_base = [(39, 121, 75, 106), (124, 121, 75, 106)]

        bottom_positions = [scale_pos(p) for p in bottom_base]

        return top_row_positions + bottom_positions

    def _find_best_card_match(
        self,
        card_region: np.ndarray,
        force_set: str = None,
        force_detailed: bool = False,
        exclude_sets: List[str] = None,
    ) -> Dict[str, Any]:
        """
        Find the best matching card in the database for a card region

        Args:
            card_region: Card image region as numpy array
            force_set: If provided, only search within this set
            force_detailed: If True, always perform detailed search regardless of quick search confidence
            exclude_sets: If provided, do not search within these sets

        Returns:
            Dict: Best match result with card_name, card_set, and confidence
        """
        best_match = None
        best_score = -1

        # Ensure templates are prepared
        if not hasattr(self, "phash_templates") or not self.phash_templates:
            self._prepare_templates()

        # Multi-stage matching for better performance:
        # 1. Quick search using pHash and Hamming distance to identify likely sets
        # 2. Detailed search at full resolution within the candidate sets

        # Stage 1: Quick search using pHash
        # Compute pHash for the region directly from the provided region
        region_pil = Image.fromarray(card_region)
        region_hash = imagehash.phash(region_pil)

        # Quick search to identify candidate sets and best card match
        set_scores = {}
        quick_best_match = None
        quick_best_score = -1

        if self.phash_matrix is not None:
            # Filter indices based on force_set / exclude_sets
            if force_set:
                indices = [
                    i
                    for i, m in enumerate(self.phash_metadata)
                    if m[0] == force_set
                ]
            elif exclude_sets:
                indices = [
                    i
                    for i, m in enumerate(self.phash_metadata)
                    if m[0] not in exclude_sets
                ]
            else:
                indices = range(len(self.phash_metadata))

            if indices:
                sub_matrix = self.phash_matrix[indices]
                q_hash = region_hash.hash.flatten()
                # Hamming distance: count non-matching bits
                distances = np.count_nonzero(sub_matrix != q_hash, axis=1)
                scores = 1.0 - (distances / 64.0)

                for i, score in enumerate(scores):
                    meta_idx = indices[i]
                    s_name, c_name = self.phash_metadata[meta_idx]

                    if score > set_scores.get(s_name, 0):
                        set_scores[s_name] = score

                    if score > quick_best_score:
                        quick_best_score = score
                        quick_best_match = {
                            "card_name": c_name,
                            "card_set": s_name,
                            "confidence": float(score),
                        }
        else:
            # Fallback to slow loop if matrix not built (should not happen)
            if force_set:
                search_sets = [force_set]
            else:
                search_sets = [
                    s
                    for s in self.phash_templates.keys()
                    if s not in (exclude_sets or [])
                ]

            for set_name in search_sets:
                if set_name not in self.phash_templates:
                    continue

                cards = self.phash_templates[set_name]
                for card_name, template_hash in cards.items():
                    # Hamming distance: lower is better. Max distance is 64 for 8x8 hash.
                    distance = region_hash - template_hash
                    # Convert to a confidence-like score (0 to 1)
                    score = 1.0 - (distance / 64.0)

                    if score > set_scores.get(set_name, 0):
                        set_scores[set_name] = score

                    if score > quick_best_score:
                        quick_best_score = score
                        quick_best_match = {
                            "card_name": card_name,
                            "card_set": set_name,
                            "confidence": score,
                        }

        # Optimization: If quick search is extremely confident, skip detailed search
        # Only if not forced to do a detailed search
        CONFIDENCE_THRESHOLD = 0.92  # Increased threshold for higher certainty
        if (
            not force_detailed
            and quick_best_match
            and quick_best_match["confidence"] >= CONFIDENCE_THRESHOLD
        ):
            logger.info(
                f"Quick search extremely confident ({quick_best_match['confidence']:.3f}), skipping detailed search"
            )
            return quick_best_match

        # Stage 2: Detailed search at full resolution
        # Determine candidate sets from quick search
        candidate_sets = []
        if force_set:
            candidate_sets = [force_set]
        elif set_scores:
            # Sort sets by their best card score
            sorted_sets = sorted(set_scores.items(), key=lambda x: x[1], reverse=True)
            # Take top sets that are close to the best score
            top_phash_score = sorted_sets[0][1]
            for s_name, s_score in sorted_sets:
                # Include set if it's in top 3 or within 0.05 of the top score
                if len(candidate_sets) < 3 or s_score >= top_phash_score - 0.05:
                    candidate_sets.append(s_name)
                # Cap at 5 sets to maintain performance
                if len(candidate_sets) >= 5:
                    break

        logger.info(f"Candidate sets for detailed search: {candidate_sets}")

        # Upscale card region to match matching resolution for detailed matching
        upscaled_region = cv2.resize(
            card_region, (self.match_width, self.match_height)
        )

        # Normalize query region for correlation
        q_vec = upscaled_region.astype(np.float32).flatten()
        q_vec -= np.mean(q_vec)
        q_norm = np.linalg.norm(q_vec)
        if q_norm > 0:
            q_vec /= q_norm

        # Detailed search in candidate sets
        for search_set in candidate_sets:
            if search_set not in self.template_vectors:
                # Fallback if vectorized data not available
                if (
                    search_set in self.color_templates
                    and self.color_templates[search_set]
                ):
                    for card_name, template_color in self.color_templates[
                        search_set
                    ].items():
                        try:
                            # Resize template if it doesn't match
                            if template_color.shape[:2][::-1] != (
                                self.match_width,
                                self.match_height,
                            ):
                                template_color = cv2.resize(
                                    template_color,
                                    (self.match_width, self.match_height),
                                )

                            result = cv2.matchTemplate(
                                upscaled_region,
                                template_color,
                                cv2.TM_CCOEFF_NORMED,
                            )
                            _, max_val, _, _ = cv2.minMaxLoc(result)

                            if max_val > best_score:
                                best_score = max_val
                                best_match = {
                                    "card_name": card_name,
                                    "card_set": search_set,
                                    "confidence": float(max_val),
                                }
                        except cv2.error:
                            continue
                continue

            data = self.template_vectors[search_set]
            matrix = data["matrix"]
            metadata = data["metadata"]

            # Matrix-vector multiplication for all cards in set
            # This computes normalized correlation (TM_CCOEFF_NORMED)
            # because both matrix and q_vec are zero-centered and unit-normalized.
            scores = matrix @ q_vec

            max_idx = np.argmax(scores)
            max_val = scores[max_idx]

            if max_val > best_score:
                best_score = max_val
                best_match = {
                    "card_name": metadata[max_idx],
                    "card_set": search_set,
                    "confidence": float(max_val),
                }

        # If detailed search found a better match or if we haven't found anything yet
        if best_match:
            return best_match

        # Fallback to quick search result if detailed search failed but quick search had something
        if quick_best_match and quick_best_match["confidence"] > 0.2:
            return quick_best_match

        return None

    def get_template_count(self) -> int:
        """
        Get the number of loaded templates

        Returns:
            int: Number of loaded card templates
        """
        # Count templates across all sets
        count = 0
        for set_name, cards in self.phash_templates.items():
            count += len(cards)
        return count

    def get_loaded_template_codes(self) -> List[str]:
        """
        Get list of loaded template codes

        Returns:
            List[str]: List of card codes for loaded templates
        """
        # Collect all card codes from all sets
        codes = []
        for set_name, cards in self.phash_templates.items():
            for card_name in cards.keys():
                codes.append(f"{set_name}_{card_name}")
        return codes

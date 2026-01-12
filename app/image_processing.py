"""
Card Counter Image Processing Module

Image processing functionality for the Card Counter application.
This module provides card identification from screenshots using OpenCV.
"""

import cv2
import numpy as np
import os
from typing import List, Dict, Any, Tuple
from PIL import Image
import logging

logger = logging.getLogger(__name__)

class ImageProcessor:
    """
    Image processing class for Card Counter application
    
    Provides functionality for identifying cards in screenshot images.
    """
    
    def __init__(self, card_imgs_dir: str = 'card_imgs'):
        """Initialize the image processor"""
        self.card_imgs_dir = card_imgs_dir
        self.card_database = self._load_card_database()
        self.card_names = self._load_card_names()
        
        # Pre-calculated templates for performance
        self.quick_templates = {}
        self.gray_templates = {}
        
        if self.card_database:
            self._prepare_templates()
    
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
                if card_file.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
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
                self._prepare_templates() # Optimization: Pre-calculate versions
                template_count = self.get_template_count()
                logger.info(f"Successfully loaded {template_count} card templates")
                self.loaded = True
            else:
                raise ValueError(f"No valid card templates found in {template_dir}")
                
        except Exception as e:
            logger.error(f"Failed to load card templates: {e}")
            raise

    def _prepare_templates(self):
        """Pre-calculate grayscale and resized versions of all templates for faster matching"""
        self.quick_templates = {}
        self.gray_templates = {}
        
        # Use fixed sizes consistent with _find_best_card_match and _detect_card_positions
        quick_target_width = 80
        # Card regions are 75x106, so quick target height should be consistent
        quick_target_height = int(quick_target_width * 106 / 75)
        
        logger.info(f"Preparing templates: quick size {quick_target_width}x{quick_target_height}")
        
        for set_name, cards in self.card_database.items():
            self.quick_templates[set_name] = {}
            self.gray_templates[set_name] = {}
            for card_name, template in cards.items():
                # 1. Full-size grayscale
                if len(template.shape) == 3:
                    gray = cv2.cvtColor(template, cv2.COLOR_RGB2GRAY)
                else:
                    gray = template
                self.gray_templates[set_name][card_name] = gray
                
                # 2. Quick grayscale
                quick = cv2.resize(template, (quick_target_width, quick_target_height))
                if len(quick.shape) == 3:
                    quick_gray = cv2.cvtColor(quick, cv2.COLOR_RGB2GRAY)
                else:
                    quick_gray = quick
                self.quick_templates[set_name][card_name] = quick_gray

    def process_screenshot(self, image_path: str) -> List[Dict[str, Any]]:
        """
        Process a screenshot to identify cards using fixed position detection
        
        Args:
            image_path: Path to screenshot image
            
        Returns:
            List[Dict]: List of identified cards with positions and confidence scores
        """
        if not self.card_database:
            raise RuntimeError("Card database not loaded. Call load_card_templates() first.")
        
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
            
            logger.info(f"Detected {len(card_positions)} card positions")
            
            # Stage 1: Initial identification for all cards
            initial_results = []
            set_counts = {}
            
            for i, (x, y, w, h) in enumerate(card_positions):
                logger.info(f"Initial scan: card {i+1} at position ({x}, {y})")
                card_region = screenshot[y:y+h, x:x+w]
                best_match = self._find_best_card_match(card_region)
                
                initial_results.append({
                    'position': i + 1,
                    'best_match': best_match,
                    'x': x, 'y': y, 'w': w, 'h': h,
                    'card_region': card_region
                })
                
                # Use slightly lower threshold for majority set identification
                if best_match and best_match['confidence'] > 0.2:
                    card_set = best_match['card_set']
                    set_counts[card_set] = set_counts.get(card_set, 0) + 1
            
            # Determine majority set
            majority_set = None
            if set_counts:
                majority_set = max(set_counts.items(), key=lambda x: x[1])[0]
                logger.info(f"Majority set identified: {majority_set}")
            
            # Stage 2: Re-process outliers if a majority set exists
            detected_cards = []
            for result in initial_results:
                best_match = result['best_match']
                i = result['position']
                
                is_outlier = False
                if not best_match:
                    is_outlier = True
                elif majority_set and best_match['card_set'] != majority_set:
                    is_outlier = True
                    logger.info(f"Card at position {i} belongs to different set ({best_match['card_set']}), forcing to {majority_set}")
                
                if is_outlier and majority_set:
                    logger.info(f"Re-scanning outlier card {i} in majority set {majority_set} with detailed search")
                    new_match = self._find_best_card_match(
                        result['card_region'], 
                        force_set=majority_set, 
                        force_detailed=True
                    )
                    
                    # Update best_match with the result from the majority set
                    # We trust the majority set even if confidence is lower than a match in a wrong set
                    best_match = new_match
                
                # Final check with lower threshold
                if best_match and best_match['confidence'] > 0.2:
                    # Get the display name for this card
                    display_name = self._get_display_name(best_match['card_name'], best_match['card_set'])
                    logger.info(f"Final result card {i}: {display_name} (confidence: {best_match['confidence']:.2f})")
                    
                    detected_cards.append({
                        'position': i,
                        'card_code': best_match['card_name'],
                        'card_name': display_name,
                        'card_set': best_match['card_set'],
                        'confidence': best_match['confidence'],
                        'x': result['x'],
                        'y': result['y'],
                        'width': result['w'],
                        'height': result['h']
                    })
                else:
                    logger.info(f"No card match found for position {i}")
            
            logger.info(f"Found {len(detected_cards)} cards in {image_path}")
            return detected_cards
            
        except Exception as e:
            logger.error(f"Failed to process screenshot {image_path}: {e}")
            raise
    
    def _detect_card_positions(self, screenshot: np.ndarray) -> List[Tuple[int, int, int, int]]:
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
                int(round(h * scale_y))
            )
            
        # Top row positions (always 3 cards)
        top_row_base = [
            (0, 5, 75, 106),     # position 1
            (81, 5, 75, 106),    # position 2
            (164, 5, 75, 106)    # position 3
        ]
        
        top_row_positions = [scale_pos(p) for p in top_row_base]
        
        # Detect layout: check if there are 2 or 3 cards on bottom row
        # Scale the detection rectangle: (x=0, y=124, w=30, h=50)
        det_x, det_y, det_w, det_h = scale_pos((0, 124, 30, 50))
        
        if det_y + det_h <= height and det_x + det_w <= width:
            detection_region = screenshot[det_y:det_y+det_h, det_x:det_x+det_w]
            avg_color = np.mean(detection_region)
            
            # #e7f0f7 in grayscale ≈ 239
            background_threshold = 235
            
            if avg_color > background_threshold:
                # 2 cards on bottom row
                bottom_base = [
                    (39, 121, 75, 106),    # position 4
                    (124, 121, 75, 106)    # position 5
                ]
            else:
                # 3 cards on bottom row
                bottom_base = [
                    (0, 121, 75, 106),     # position 4
                    (81, 121, 75, 106),    # position 5
                    (164, 121, 75, 106)   # position 6
                ]
        else:
            # Fallback to 2-card layout
            bottom_base = [
                (39, 121, 75, 106),
                (124, 121, 75, 106)
            ]
        
        bottom_positions = [scale_pos(p) for p in bottom_base]
        
        return top_row_positions + bottom_positions
    
    def _find_best_card_match(self, card_region: np.ndarray, force_set: str = None, force_detailed: bool = False) -> Dict[str, Any]:
        """
        Find the best matching card in the database for a card region
        
        Args:
            card_region: Card image region as numpy array
            force_set: If provided, only search within this set
            force_detailed: If True, always perform detailed search regardless of quick search confidence
            
        Returns:
            Dict: Best match result with card_name, card_set, and confidence
        """
        best_match = None
        best_score = -1
        
        # Ensure templates are prepared
        if not hasattr(self, 'quick_templates') or not self.quick_templates:
            self._prepare_templates()
            
        # Multi-stage matching for better performance:
        # 1. Quick search at reduced resolution to identify likely set
        # 2. Detailed search at full resolution within the identified set
        
        # Stage 1: Quick search at reduced resolution
        quick_target_width = 80
        aspect_ratio = card_region.shape[1] / card_region.shape[0]
        quick_target_height = int(quick_target_width / aspect_ratio)
        quick_region = cv2.resize(card_region, (quick_target_width, quick_target_height))
        
        # Convert to grayscale for quick search
        if len(quick_region.shape) == 3:
            quick_gray = cv2.cvtColor(quick_region, cv2.COLOR_RGB2GRAY)
        else:
            quick_gray = quick_region
        
        # Quick search to identify likely set and best card match
        set_scores = {}
        quick_best_match = None
        quick_best_score = -1

        search_sets = [force_set] if force_set else self.quick_templates.keys()
        
        for set_name in search_sets:
            if set_name not in self.quick_templates:
                continue
                
            cards = self.quick_templates[set_name]
            for card_name, quick_template_gray in cards.items():
                try:
                    # Note: We assume all templates were resized to the same quick_target_height
                    # which is true for standard card regions (75x106)
                    result = cv2.matchTemplate(quick_gray, quick_template_gray, cv2.TM_CCORR_NORMED)
                    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
                    
                    if max_val > set_scores.get(set_name, 0):
                        set_scores[set_name] = max_val
                    
                    if max_val > quick_best_score:
                        quick_best_score = max_val
                        quick_best_match = {
                            'card_name': card_name,
                            'card_set': set_name,
                            'confidence': max_val
                        }
                except cv2.error:
                    # If size mismatch, fallback to resizing (shouldn't happen with fixed regions)
                    quick_template_resized = cv2.resize(quick_template_gray, (quick_gray.shape[1], quick_gray.shape[0]))
                    result = cv2.matchTemplate(quick_gray, quick_template_resized, cv2.TM_CCORR_NORMED)
                    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
                    if max_val > set_scores.get(set_name, 0):
                        set_scores[set_name] = max_val
                    
                    if max_val > quick_best_score:
                        quick_best_score = max_val
                        quick_best_match = {
                            'card_name': card_name,
                            'card_set': set_name,
                            'confidence': max_val
                        }
        
        # Determine the most likely set from quick search
        likely_set = None
        if set_scores:
            likely_set = max(set_scores.items(), key=lambda x: x[1])[0]
            logger.info(f"Quick search identified likely set: {likely_set} (score: {set_scores[likely_set]:.3f})")

        # Optimization: If quick search is extremely confident, skip detailed search
        # Only if not forced to do a detailed search
        CONFIDENCE_THRESHOLD = 0.90
        if not force_detailed and quick_best_match and quick_best_match['confidence'] >= CONFIDENCE_THRESHOLD:
            logger.info(f"Quick search extremely confident ({quick_best_match['confidence']:.3f}), skipping detailed search")
            return quick_best_match
        
        # Stage 2: Detailed search at full resolution
        search_set = force_set if force_set else likely_set
        
        # Upscale card region to match full card resolution for detailed matching
        target_width, target_height = 367, 512  # Standard full card size
        upscaled_region = cv2.resize(card_region, (target_width, target_height))
        
        # Convert to grayscale once for efficiency
        if len(upscaled_region.shape) == 3:
            upscaled_gray = cv2.cvtColor(upscaled_region, cv2.COLOR_RGB2GRAY)
        else:
            upscaled_gray = upscaled_region
        
        # Detailed search in the identified set
        if search_set and search_set in self.gray_templates:
            logger.info(f"Performing detailed search in set: {search_set}")
            
            for card_name, template_gray in self.gray_templates[search_set].items():
                # Use pre-calculated full-size grayscale template
                try:
                    result = cv2.matchTemplate(upscaled_gray, template_gray, cv2.TM_CCORR_NORMED)
                    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
                    
                    # If this is the best match so far
                    if max_val > best_score:
                        best_score = max_val
                        best_match = {
                            'card_name': card_name,
                            'card_set': search_set,
                            'confidence': max_val
                        }
                except cv2.error:
                    continue
        
        # If detailed search found a better match or if we haven't found anything yet
        if best_match:
            return best_match
        
        # Fallback to quick search result if detailed search failed but quick search had something
        if quick_best_match and quick_best_match['confidence'] > 0.2:
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
        for set_name, cards in self.card_database.items():
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
        for set_name, cards in self.card_database.items():
            for card_name in cards.keys():
                codes.append(f"{set_name}_{card_name}")
        return codes

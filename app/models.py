from PyQt6.QtCore import QAbstractTableModel, Qt, QModelIndex, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from typing import List, Dict, Any, Optional
import os

class CardModel(QAbstractTableModel):
    """Model for displaying cards in QTableView"""
    
    def __init__(self, data=None):
        super().__init__()
        self._data = data or []
        self._headers = ["Art", "Card", "Set", "Rarity", "Count"]
        
    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._data)
    
    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self._headers)
    
    def data(self, index, role=Qt.ItemDataRole):
        if not index.isValid():
            return None
            
        row = index.row()
        col = index.column()
        
        if row >= len(self._data) or col >= len(self._headers):
            return None
            
        card_data = self._data[row]
        
        if role == Qt.ItemDataRole.TextAlignmentRole and col == 0:
            return Qt.AlignmentFlag.AlignCenter

        if role == Qt.ItemDataRole.DisplayRole:
            # Return text for display
            if col == 1:  # Card column
                return card_data.get('card_name', 'Unknown')
            elif col == 2:  # Set column
                return card_data.get('set_name', 'Unknown')
            elif col == 3:  # Rarity column
                return card_data.get('rarity', 'Unknown')
            elif col == 4:  # Count column
                return str(card_data.get('count', 0))
                
        elif role == Qt.ItemDataRole.DecorationRole and col == 0:
            # Return icon for Art column
            image_path = card_data.get('image_path')
            card_code = card_data.get('card_code')
            
            # Try to find card image
            resolved_path = self._find_card_image(card_code, image_path)
            if resolved_path and os.path.exists(resolved_path):
                return QIcon(resolved_path)
                    
        elif role == Qt.ItemDataRole.ToolTipRole:
            # Return tooltip with detailed information
            tooltip = f"{card_data.get('card_name', 'Unknown')}\n"
            tooltip += f"Set: {card_data.get('set_name', 'Unknown')}\n"
            tooltip += f"Rarity: {card_data.get('rarity', 'Unknown')}\n"
            tooltip += f"Count: {card_data.get('count', 0)}"
            return tooltip
            
        return None
    
    def headerData(self, section, orientation, role=Qt.ItemDataRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self._headers):
                return self._headers[section]
        return None
        
    def update_data(self, new_data):
        """Update the model with new data"""
        self.beginResetModel()
        self._data = new_data
        self.endResetModel()

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        """Sort model by column"""
        self.layoutAboutToBeChanged.emit()
        
        is_ascending = order == Qt.SortOrder.AscendingOrder
        
        def sort_key(item):
            if column == 1:  # Card
                return item.get('card_name', '').lower()
            elif column == 2:  # Set
                # Sort by set name, then card name
                return (item.get('set_name', '').lower(), item.get('card_name', '').lower())
            elif column == 3:  # Rarity
                return item.get('rarity', '').lower()
            elif column == 4:  # Count
                return item.get('count', 0)
            return ""

        self._data.sort(key=sort_key, reverse=not is_ascending)
        self.layoutChanged.emit()

    def _find_card_image(self, card_code: str = None, image_path: str = None) -> Optional[str]:
        """Find the path to a card image based on card code or provided image path"""
        # If image_path is provided, try that first
        if image_path:
            # Check various relative locations for the image_path
            check_paths = [
                image_path,
                os.path.join("resources", "card_imgs", image_path),
                os.path.join("static", "card_imgs", image_path),
            ]
            
            # If image_path contains a slash, also try without the first part (e.g. A1/A1_1.webp -> A1_1.webp)
            if "/" in image_path:
                parts = image_path.split("/")
                filename = parts[-1]
                set_code = parts[0]
                check_paths.append(os.path.join("resources", "card_imgs", set_code, filename))
                check_paths.append(os.path.join("static", "card_imgs", set_code, filename))
            
            for path in check_paths:
                if os.path.exists(path):
                    return path

        # Try to find card image in resources based on card code
        # Card code format can be SET_NUMBER (e.g., A1_1) or NAME_SET (e.g., A1_1_A1)
        if card_code and '_' in card_code:
            # If we have multiple underscores, it's likely NAME_SET format
            if card_code.count('_') >= 2:
                name, set_code = card_code.rsplit('_', 1)
            else:
                # Fallback for simpler format
                set_code, _ = card_code.split('_', 1)
                name = card_code
            
            # Try different resource paths
            possible_paths = [
                f"resources/card_imgs/{set_code}/{name}.webp",
                f"resources/card_imgs/{set_code}/{name}.png",
                f"resources/card_imgs/{set_code}/{name}.jpg",
                f"static/card_imgs/{set_code}/{name}.webp",
                f"static/card_imgs/{set_code}/{name}.png",
                f"static/card_imgs/{set_code}/{name}.jpg",
                # Also try the original card_code just in case
                f"resources/card_imgs/{set_code}/{card_code}.webp",
                f"static/card_imgs/{set_code}/{card_code}.webp",
            ]
            
            for path in possible_paths:
                if os.path.exists(path):
                    return path
                    
        return None

class ProcessingTaskModel(QAbstractTableModel):
    """Model for displaying processing tasks"""
    
    def __init__(self, data=None):
        super().__init__()
        self._data = data or []
        self._headers = ["Task ID", "Status", "Progress", "Description"]
    
    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._data)
    
    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self._headers)
    
    def data(self, index, role=Qt.ItemDataRole):
        if not index.isValid():
            return None
            
        row = index.row()
        col = index.column()
        
        if row >= len(self._data) or col >= len(self._headers):
            return None
            
        task_data = self._data[row]
        
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:  # Task ID
                return task_data.get('task_id', '')
            elif col == 1:  # Status
                return task_data.get('status', 'Unknown')
            elif col == 2:  # Progress
                return f"{task_data.get('progress', 0)}%"
            elif col == 3:  # Description
                return task_data.get('description', '')
                
        return None
    
    def headerData(self, section, orientation, role=Qt.ItemDataRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self._headers):
                return self._headers[section]
        return None
        
    def update_data(self, new_data):
        """Update the model with new data"""
        self.beginResetModel()
        self._data = new_data
        self.endResetModel()

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        """Sort model by column"""
        self.layoutAboutToBeChanged.emit()
        
        is_ascending = order == Qt.SortOrder.AscendingOrder
        
        def sort_key(item):
            if column == 0:  # Task ID
                return item.get('task_id', '')
            elif column == 1:  # Status
                return item.get('status', '').lower()
            elif column == 2:  # Progress
                return item.get('progress', 0)
            elif column == 3:  # Description
                return item.get('description', '').lower()
            return ""

        self._data.sort(key=sort_key, reverse=not is_ascending)
        self.layoutChanged.emit()

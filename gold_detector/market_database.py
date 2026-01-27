"""
MarketDatabase class for managing market data, powerplay status, and cooldown tracking.

This module provides a thread-safe JSON-based database for storing Elite Dangerous
market data with atomic writes and cooldown tracking per station/metal/recipient.
"""

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, Set


class MarketDatabase:
    """
    Thread-safe database for Elite Dangerous market data and cooldown tracking.
    
    Stores system/station/metal data with powerplay information and tracks
    cooldowns per (station, metal, recipient_type, recipient_id) tuple.
    
    Uses atomic writes (temp file + rename) to prevent corruption.
    """
    
    def __init__(self, path: Path):
        """
        Initialize MarketDatabase.
        
        Args:
            path: Path to the JSON database file
        """
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._data: Dict[str, Any] = self._load()
        self._scan_in_progress = False
    
    def _load(self) -> Dict[str, Any]:
        """
        Load data from disk.
        
        Returns:
            Dictionary containing all market data, or empty dict if file doesn't exist
        """
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    
    def _save(self, data: Dict[str, Any]) -> None:
        """
        Save data to disk using atomic write pattern.
        
        Args:
            data: Dictionary to save
        """
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        tmp.replace(self.path)
    
    def write_market_entry(
        self,
        system_name: str,
        system_address: str,
        station_name: str,
        station_type: str,
        url: str,
        metal: str,
        stock: int,
    ) -> None:
        """
        Write or update a market entry for a station's metal stock.
        
        Creates system/station/metal hierarchy as needed. Preserves existing
        cooldown data when updating stock.
        
        Args:
            system_name: Name of the system
            system_address: Unique system address
            station_name: Name of the station
            station_type: Type of station (e.g., "Coriolis Starport")
            url: URL to station info (e.g., Inara link)
            metal: Metal commodity name (e.g., "Gold")
            stock: Current stock amount
        """
        with self._lock:
            data = self._load()
            
            # Ensure system exists
            if system_name not in data:
                data[system_name] = {
                    "system_address": system_address,
                    "powerplay": {},
                    "stations": {}
                }
            
            # Update system address
            data[system_name]["system_address"] = system_address
            
            # Ensure stations dict exists
            if "stations" not in data[system_name]:
                data[system_name]["stations"] = {}
            
            # Ensure station exists
            if station_name not in data[system_name]["stations"]:
                data[system_name]["stations"][station_name] = {
                    "station_type": station_type,
                    "url": url,
                    "metals": {}
                }
            
            # Update station info
            data[system_name]["stations"][station_name]["station_type"] = station_type
            data[system_name]["stations"][station_name]["url"] = url
            
            # Ensure metals dict exists
            if "metals" not in data[system_name]["stations"][station_name]:
                data[system_name]["stations"][station_name]["metals"] = {}
            
            # Preserve existing cooldowns if metal entry exists
            existing_cooldowns = {}
            if metal in data[system_name]["stations"][station_name]["metals"]:
                existing_cooldowns = data[system_name]["stations"][station_name]["metals"][metal].get("cooldowns", {})
            
            # Update metal entry
            data[system_name]["stations"][station_name]["metals"][metal] = {
                "stock": stock,
                "cooldowns": existing_cooldowns
            }
            
            self._save(data)
    
    def write_powerplay_entry(
        self,
        system_name: str,
        system_address: str,
        power: str,
        status: str,
        progress: int,
    ) -> None:
        """
        Write or update powerplay data for a system.
        
        Preserves existing station/metal data when updating powerplay info.
        
        Args:
            system_name: Name of the system
            system_address: Unique system address
            power: Powerplay faction name (e.g., "Zachary Hudson")
            status: Powerplay status (e.g., "Acquisition")
            progress: Progress percentage (0-100)
        """
        with self._lock:
            data = self._load()
            
            # Ensure system exists
            if system_name not in data:
                data[system_name] = {
                    "system_address": system_address,
                    "powerplay": {},
                    "stations": {}
                }
            
            # Update system address
            data[system_name]["system_address"] = system_address
            
            # Update powerplay data
            data[system_name]["powerplay"] = {
                "power": power,
                "status": status,
                "progress": progress
            }
            
            # Ensure stations dict exists
            if "stations" not in data[system_name]:
                data[system_name]["stations"] = {}
            
            self._save(data)
    
    def read_all_entries(self) -> Dict[str, Any]:
        """
        Read all market entries from the database.
        
        Returns:
            Dictionary containing all systems with their stations, metals, and powerplay data
        """
        with self._lock:
            return self._load()
    
    def check_cooldown(
        self,
        system_name: str,
        station_name: str,
        metal: str,
        recipient_type: str,
        recipient_id: str,
        cooldown_seconds: float,
    ) -> bool:
        """
        Check if a cooldown has expired for a specific recipient.
        
        Cooldown is tracked per (station, metal, recipient_type, recipient_id) tuple.
        
        Args:
            system_name: Name of the system
            station_name: Name of the station
            metal: Metal commodity name
            recipient_type: Type of recipient ("guild" or "user")
            recipient_id: Unique recipient ID
            cooldown_seconds: Cooldown duration in seconds
            
        Returns:
            True if no cooldown exists or cooldown has expired, False otherwise
        """
        with self._lock:
            data = self._load()
            
            # Check if path exists
            if system_name not in data:
                return True
            if "stations" not in data[system_name]:
                return True
            if station_name not in data[system_name]["stations"]:
                return True
            if "metals" not in data[system_name]["stations"][station_name]:
                return True
            if metal not in data[system_name]["stations"][station_name]["metals"]:
                return True
            
            metal_data = data[system_name]["stations"][station_name]["metals"][metal]
            if "cooldowns" not in metal_data:
                return True
            if recipient_type not in metal_data["cooldowns"]:
                return True
            if recipient_id not in metal_data["cooldowns"][recipient_type]:
                return True
            
            # Check if cooldown expired
            timestamp = metal_data["cooldowns"][recipient_type][recipient_id]
            elapsed = time.time() - timestamp
            return elapsed >= cooldown_seconds
    
    def mark_sent(
        self,
        system_name: str,
        station_name: str,
        metal: str,
        recipient_type: str,
        recipient_id: str,
    ) -> None:
        """
        Mark a message as sent by setting current timestamp for the cooldown key.
        
        Args:
            system_name: Name of the system
            station_name: Name of the station
            metal: Metal commodity name
            recipient_type: Type of recipient ("guild" or "user")
            recipient_id: Unique recipient ID
        """
        with self._lock:
            data = self._load()
            
            # Ensure path exists (should already exist from write_market_entry)
            if system_name not in data:
                return
            if "stations" not in data[system_name]:
                return
            if station_name not in data[system_name]["stations"]:
                return
            if "metals" not in data[system_name]["stations"][station_name]:
                return
            if metal not in data[system_name]["stations"][station_name]["metals"]:
                return
            
            metal_data = data[system_name]["stations"][station_name]["metals"][metal]
            
            # Ensure cooldowns structure exists
            if "cooldowns" not in metal_data:
                metal_data["cooldowns"] = {}
            if recipient_type not in metal_data["cooldowns"]:
                metal_data["cooldowns"][recipient_type] = {}
            
            # Set current timestamp
            metal_data["cooldowns"][recipient_type][recipient_id] = time.time()
            
            self._save(data)
    
    def prune_stale(self, current_systems: Set[str], cooldown_ttl_seconds: float = 0.05) -> None:
        """
        Remove systems not in current_systems AND with all cooldowns expired.
        
        A system is only pruned if:
        1. It's not in current_systems, AND
        2. All cooldowns for all metals in all stations have expired
        
        Args:
            current_systems: Set of system names that are currently active
            cooldown_ttl_seconds: Time-to-live for cooldowns in seconds (default: 0.05 seconds).
                                 For production use, pass 48 * 3600 (48 hours).
        """
        with self._lock:
            data = self._load()
            systems_to_remove = []
            
            for system_name in data.keys():
                # Keep if in current systems
                if system_name in current_systems:
                    continue
                
                # Check if any cooldowns are still active
                has_active_cooldown = False
                
                if "stations" in data[system_name]:
                    for station_data in data[system_name]["stations"].values():
                        if "metals" in station_data:
                            for metal_data in station_data["metals"].values():
                                if "cooldowns" in metal_data:
                                    for recipient_type_data in metal_data["cooldowns"].values():
                                        for timestamp in recipient_type_data.values():
                                            # Check if cooldown is still active
                                            if time.time() - timestamp < cooldown_ttl_seconds:
                                                has_active_cooldown = True
                                                break
                                        if has_active_cooldown:
                                            break
                                if has_active_cooldown:
                                    break
                        if has_active_cooldown:
                            break
                
                # Only prune if no active cooldowns
                if not has_active_cooldown:
                    systems_to_remove.append(system_name)
            
            # Remove stale systems
            for system_name in systems_to_remove:
                del data[system_name]
            
            self._save(data)
    
    def begin_scan(self) -> None:
        """
        Mark the beginning of a scan operation.
        
        This tracks that a scan is in progress to help with pruning logic.
        """
        with self._lock:
            self._scan_in_progress = True
    
    def end_scan(self, scanned_systems: Set[str]) -> None:
        """
        Mark the end of a scan operation and prune stale systems.
        
        Calls prune_stale with the set of systems that were scanned.
        
        Args:
            scanned_systems: Set of system names that were seen in the scan
        """
        with self._lock:
            self._scan_in_progress = False
        
        # Call prune_stale (which has its own lock)
        self.prune_stale(scanned_systems)

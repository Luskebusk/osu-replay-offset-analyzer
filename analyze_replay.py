# analyze_replay.py

import configparser
import os
import sys
import time
import statistics
import traceback # For better error printing
import logging # For better logging
import math # For abs value comparison
import logging.handlers
import csv
from datetime import datetime
from collections import defaultdict # For grouping stats

# --- PyQt6 Imports ---
try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QLabel, QStackedWidget, QTreeWidget, QTreeWidgetItem,
        QLineEdit, QHeaderView, QSizePolicy, QSpacerItem, QMessageBox
    )
    # --- MODIFIED: Added QUrl, QDesktopServices ---
    from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, pyqtSlot, QUrl, QSize
    # --- MODIFIED: Added QIcon, QDesktopServices ---
    from PyQt6.QtGui import QFont, QBrush, QColor, QPalette, QIcon, QDesktopServices
except ImportError:
    print("ERROR: Failed to import 'PyQt6'. Please install it using: pip install PyQt6")
    sys.exit(1)
# --- End PyQt6 Imports ---


# --- Parser Imports ---
try: from osu_db import osu_db
except ImportError: print("ERROR: Failed to import 'osu_db'."); sys.exit(1)
try: from osrparse import Replay, GameMode, Mod, Key
except ImportError: print("ERROR: Failed to import 'osrparse'."); sys.exit(1)
try: from beatmapparser import BeatmapParser
except ImportError: print("ERROR: Failed to import 'beatmapparser'."); sys.exit(1)
# --- End Parser Imports ---

# Watchdog for monitoring
try: from watchdog.observers import Observer; from watchdog.events import FileSystemEventHandler
except ImportError: print("ERROR: Failed to import 'watchdog'."); sys.exit(1)

# --- Configuration ---
APP_NAME = "OsuAnalyzer" # Define app name for folder

# --- Function to get user data directory ---
def get_user_data_dir():
    """Gets the path to the application's data directory in AppData\Local."""
    base_path = os.getenv('LOCALAPPDATA')
    if not base_path:
        base_path = os.path.expanduser("~")
        print("WARNING: LOCALAPPDATA environment variable not found. Using user home directory.")
    app_data_dir = os.path.join(base_path, APP_NAME)
    try:
        os.makedirs(app_data_dir, exist_ok=True)
    except OSError as e:
        print(f"ERROR: Could not create application data directory: {app_data_dir} - Error: {e}")
        return "." # Fallback to current directory
    return app_data_dir

# --- Define file paths using the user data directory ---
USER_DATA_DIR = get_user_data_dir()
CONFIG_FILE = os.path.join(USER_DATA_DIR, 'config.ini')
DEBUG_LOG_FILE = os.path.join(USER_DATA_DIR, 'log.txt')
STATS_CSV_FILE = os.path.join(USER_DATA_DIR, 'analysis_stats.csv')

# --- Global Variables (Set by load_config and main block) ---
REPLAYS_FOLDER = ""
SONGS_FOLDER = ""
OSU_DB_PATH = ""
OSU_DB = None
MANUAL_REPLAY_OFFSET_MS = 0

# --- Logging Setup ---
logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger()

# --- Dark Theme Stylesheet ---
DARK_STYLE = """
    QWidget {
        background-color: #2e2e2e;
        color: #e0e0e0; /* Default text color */
        font-size: 10pt;
        /* Attempt to use the font, fallback to Segoe UI/system default */
        font-family: "Rounded Mplus 1c", "Segoe UI", Arial, sans-serif;
    }
    QMainWindow {
        background-color: #2e2e2e;
    }
    /* Style for the sidebar */
    #SidebarWidget {
        background-color: #363636;
    }
    /* Style for the main content area */
    #ContentWidget {
        background-color: #2e2e2e;
    }
    QPushButton {
        padding: 8px 15px;
        font-size: 11pt;
        border: 1px solid #555;
        border-radius: 4px;
        background-color: #4a4a4a;
        color: #e0e0e0;
        font-weight: bold; /* Make button text bold */
    }
    QPushButton:hover {
        background-color: #5a5a5a;
        border-color: #777;
    }
    QPushButton:pressed {
        background-color: #3a3a3a;
    }
    /* Style for sidebar buttons */
    #SidebarButton {
        background-color: #363636;
        border: none; /* Remove border */
        text-align: center;
        padding: 10px;
        font-size: 14px; /* Match Figma */
        font-weight: 800; /* Extra Bold */
    }
    #SidebarButton:hover {
        background-color: #4a4a4a; /* Slightly lighter on hover */
    }
    #SidebarButton:pressed {
        background-color: #2a2a2a; /* Darker on press */
    }
    /* Style for the selected sidebar button */
    #SidebarButton[selected="true"] {
         background-color: #2e2e2e; /* Match content background */
         border-left: 3px solid #aaa; /* Add a left border indicator */
    }

    QLabel {
        padding: 4px;
        font-size: 11pt;
        color: #d0d0d0;
    }
    /* Style for the large stat labels */
    #StatLabel {
        font-size: 32px;
        font-weight: 800; /* Extra Bold */
        qproperty-alignment: 'AlignCenter'; /* Use qproperty for alignment */
        padding: 15px;
    }
    /* Style for bottom bar labels */
    #BottomBarLabel {
        font-size: 12px; /* Adjusted size */
        font-weight: 700; /* Bold */
        padding: 5px;
    }
    /* Style for GitHub icon button */
    #GitHubButton {
        border: none;
        background-color: transparent;
        padding: 2px; /* Small padding */
    }
    #GitHubButton:hover {
        background-color: #4a4a4a; /* Subtle hover */
    }
    #GitHubButton:pressed {
        background-color: #2a2a2a;
    }

    #BottomBarInfoLabel {
        font-size: 10pt; /* Slightly smaller for info text */
        font-weight: normal; /* Regular weight */
        padding: 5px;
        color: #a0a0a0; /* Dimmer color */
    }
    /* Style for the map name label at the top */
    #MapTitleLabel {
        font-size: 20px; /* Slightly smaller than stats */
        font-weight: 800; /* Extra Bold */
        qproperty-alignment: 'AlignCenter';
        padding-top: 15px;
        padding-bottom: 20px; /* More space below map title */
    }

    QLineEdit#SearchAreaValue { /* Style specifically for the search input */
        padding: 5px;
        border: 1px solid #555;
        border-radius: 3px;
        background-color: #3e3e3e;
        color: #e0e0e0;
        font-size: 10pt;
    }
    QTreeWidget#BoxForHistory { /* Style specifically for the history tree */
        border: 1px solid #444;
        background-color: #3a3a3a;
        alternate-background-color: #424242;
        color: #e0e0e0;
    }
    QHeaderView::section {
        background-color: #4a4a4a;
        padding: 4px;
        border: 1px solid #555;
        color: #e0e0e0;
        font-size: 10pt;
        font-weight: bold;
    }
    QScrollBar:vertical {
        border: 1px solid #555;
        background: #3e3e3e;
        width: 15px;
        margin: 15px 0 15px 0;
        border-radius: 3px;
    }
    QScrollBar::handle:vertical {
        background: #6a6a6a;
        min-height: 20px;
        border-radius: 3px;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { border: none; background: none; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
    QScrollBar:horizontal { border: 1px solid #555; background: #3e3e3e; height: 15px; margin: 0 15px 0 15px; border-radius: 3px; }
    QScrollBar::handle:horizontal { background: #6a6a6a; min-width: 20px; border-radius: 3px; }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { border: none; background: none; }
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; }
"""

# --- Logging Setup Function ---
def setup_logging():
    """Configures logging based on settings in config.ini."""
    log_level_str = 'INFO' # Default log level
    config = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        try:
            config.read(CONFIG_FILE)
            if 'Settings' in config: log_level_str = config['Settings'].get('LogLevel', 'INFO').upper()
        except configparser.Error as e: print(f"Warning: Could not read LogLevel from config file ({CONFIG_FILE}): {e}")

    log_levels = {'DEBUG': logging.DEBUG, 'INFO': logging.INFO, 'WARNING': logging.WARNING, 'ERROR': logging.ERROR}
    log_level = log_levels.get(log_level_str, logging.INFO)
    _logger = logging.getLogger(); _logger.setLevel(log_level)
    for handler in _logger.handlers[:]: _logger.removeHandler(handler)
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    console_handler = logging.StreamHandler(sys.stdout)
    console_log_level = logging.INFO if log_level > logging.DEBUG else logging.DEBUG
    console_handler.setLevel(console_log_level); console_handler.setFormatter(log_formatter); _logger.addHandler(console_handler)
    if log_level == logging.DEBUG:
        try:
            os.makedirs(os.path.dirname(DEBUG_LOG_FILE), exist_ok=True)
            file_handler = logging.FileHandler(DEBUG_LOG_FILE, mode='w', encoding='utf-8')
            file_handler.setLevel(logging.DEBUG); file_handler.setFormatter(log_formatter); _logger.addHandler(file_handler)
            _logger.info(f"DEBUG level enabled. Logging detailed output to '{DEBUG_LOG_FILE}'")
        except Exception as e: _logger.error(f"Failed to create debug log file handler: {e}"); print(f"ERROR: Failed to create debug log file: {e}")
    _logger.info(f"Logging level set to {log_level_str}")
    return _logger

# --- Configuration Loading ---
def load_config():
    """Loads and validates paths and settings from the configuration file."""
    global MANUAL_REPLAY_OFFSET_MS, REPLAYS_FOLDER, SONGS_FOLDER, OSU_DB_PATH
    config = configparser.ConfigParser()
    replays_path_str, songs_path_str, osu_db_path_str = None, None, None
    manual_offset_str, log_level_str = '-10', 'INFO'
    created_default_config = False

    if not os.path.exists(CONFIG_FILE):
        print(f"'{os.path.basename(CONFIG_FILE)}' not found in '{os.path.dirname(CONFIG_FILE)}'. Creating default.")
        print(f"Please edit it with your actual osu! paths.")
        config['Paths'] = {'OsuReplaysFolder': '', 'OsuSongsFolder': '', 'OsuDbPath': ''}
        config['Settings'] = { 'LogLevel': 'INFO', 'ReplayTimeOffsetMs': '-10' }
        try:
            os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
            with open(CONFIG_FILE, 'w') as cf: config.write(cf)
            print(f"Default '{CONFIG_FILE}' created.")
            created_default_config = True
        except IOError as e: print(f"ERROR: Could not write default config file: {e}"); sys.exit(f"Exiting. Could not create '{CONFIG_FILE}'.")

    try: config.read(CONFIG_FILE)
    except configparser.Error as e: print(f"ERROR: Error reading config file: {e}"); raise ValueError(f"Error reading config: {e}") from e

    if 'Paths' not in config: print("ERROR: Missing [Paths] in config.ini"); raise ValueError("Missing [Paths] in config.ini")
    try:
        replays_path_str = config['Paths'].get('OsuReplaysFolder', '')
        songs_path_str = config['Paths'].get('OsuSongsFolder', '')
        osu_db_path_str = config['Paths'].get('OsuDbPath', '')
        if not replays_path_str or not songs_path_str or not osu_db_path_str:
             print(f"ERROR: One or more paths in '{CONFIG_FILE}' are empty. Please configure them.")
             if created_default_config: sys.exit(f"Paths missing in '{CONFIG_FILE}'. Please edit.")
    except KeyError as e: print(f"ERROR: Missing key {e} in [Paths]."); sys.exit(f"Check config for key: {e}")

    if 'Settings' in config:
        log_level_str = config['Settings'].get('LogLevel', 'INFO').upper()
        manual_offset_str = config['Settings'].get('ReplayTimeOffsetMs', '-10')
    else: print("WARNING: Missing [Settings] section in config.ini. Using defaults.")

    _logger = setup_logging() # Setup logging AFTER reading config

    if not replays_path_str or not songs_path_str or not osu_db_path_str:
        _logger.error(f"One or more paths in '{CONFIG_FILE}' are empty. Please configure them.")
        if created_default_config: sys.exit(f"Paths missing in '{CONFIG_FILE}'. Please edit.")

    if not os.path.isdir(replays_path_str): _logger.error(f"Replays folder not found: {replays_path_str}"); raise NotADirectoryError(f"Replays folder not found: {replays_path_str}")
    if not os.path.isdir(songs_path_str): _logger.error(f"Songs folder not found: {songs_path_str}"); raise NotADirectoryError(f"Songs folder not found: {songs_path_str}")
    if not os.path.isfile(osu_db_path_str): _logger.error(f"osu!.db not found: {osu_db_path_str}"); raise FileNotFoundError(f"osu!.db not found: {osu_db_path_str}")

    try: MANUAL_REPLAY_OFFSET_MS = int(manual_offset_str)
    except ValueError: _logger.warning(f"Invalid ReplayTimeOffsetMs '{manual_offset_str}'. Using 0 ms."); MANUAL_REPLAY_OFFSET_MS = 0
    _logger.info(f"Manual Replay Time Offset set to: {MANUAL_REPLAY_OFFSET_MS} ms")

    REPLAYS_FOLDER = replays_path_str; SONGS_FOLDER = songs_path_str; OSU_DB_PATH = osu_db_path_str
    _logger.info("Configuration paths validated.")
    _logger.info(f"Using configuration file: {CONFIG_FILE}")
    print(f"INFO: Config file location: {CONFIG_FILE}")

    return created_default_config

# --- Load osu!.db ---
def load_osu_database(db_path):
    logger.info(f"Loading osu!.db from: {db_path}...")
    start_time = time.time()
    try:
        osu_db_data = osu_db.parse_file(db_path)
        logger.info(f"osu!.db loaded successfully in {time.time() - start_time:.2f} seconds.")
        return osu_db_data
    except Exception as e: logger.critical(f"FATAL: Failed to load/parse osu!.db: {e}"); traceback.print_exc(); sys.exit("Exiting.")

# --- Beatmap Lookup ---
def lookup_beatmap_in_db(beatmap_hash):
    global OSU_DB, SONGS_FOLDER
    if OSU_DB is None: return None, None, None
    logger.info(f"Searching osu!.db for beatmap with hash: {beatmap_hash}...")
    found_entry = None
    try:
        if not hasattr(OSU_DB, 'beatmaps'): return None, None, None
        for beatmap_entry in OSU_DB.beatmaps:
            try:
                entry_hash = beatmap_entry.md5_hash
                if entry_hash and entry_hash.lower() == beatmap_hash.lower(): found_entry = beatmap_entry; break
            except AttributeError: continue
        if found_entry:
            folder_name, osu_filename, od, star_rating = None, None, None, None
            try:
                folder_name = found_entry.folder_name; osu_filename = found_entry.osu_file_name; od = found_entry.overall_difficulty
                if hasattr(found_entry, 'std_stars') and hasattr(found_entry.std_stars, 'stars'):
                    for star_entry in found_entry.std_stars.stars:
                         if hasattr(star_entry, 'int') and star_entry.int == 0:
                             if hasattr(star_entry, 'double'): star_rating = star_entry.double; break
                if star_rating is None: logger.warning(f"Could not find NoMod SR for hash {beatmap_hash}")
                logger.debug(f"Found entry: Folder='{folder_name}', File='{osu_filename}', OD='{od}', SR='{star_rating}'")
                if folder_name and osu_filename:
                    logger.info(f"Found beatmap entry: {folder_name}\\{osu_filename}")
                    full_map_path = os.path.join(SONGS_FOLDER, folder_name, osu_filename)
                    logger.info(f"  Constructed Path: {full_map_path}"); logger.info(f"  Overall Difficulty (OD): {od}"); logger.info(f"  Star Rating (NoMod): {star_rating if star_rating is not None else 'N/A'}")
                    if os.path.isfile(full_map_path): return full_map_path, float(od) if od is not None else None, float(star_rating) if star_rating is not None else None
                    else: logger.warning(f"DB entry found but file missing: {full_map_path}"); return None, None, None
                else: logger.warning(f"DB entry for hash {beatmap_hash} missing path info."); return None, None, None
            except AttributeError as ae: logger.warning(f"DB entry for hash {beatmap_hash} missing attribute ({ae})."); return None, None, None
        else: logger.warning(f"Beatmap hash {beatmap_hash} not found in osu!.db."); return None, None, None
    except Exception as e: logger.error(f"Error looking up hash {beatmap_hash}: {e}"); traceback.print_exc(); return None, None, None

# --- .osu File Parsing ---
def parse_osu_file(map_path):
    logger.info(f"Parsing beatmap: {os.path.basename(map_path)} using BeatmapParser...")
    try:
        parser = BeatmapParser();
        with open(map_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f: parser.read_line(line)
        parser.build_beatmap(); beatmap_data = parser.beatmap
        logger.info("Beatmap parsed successfully with BeatmapParser.")
        return beatmap_data
    except Exception as e: logger.error(f"Error parsing .osu file {os.path.basename(map_path)}: {e}"); traceback.print_exc(); return None

# --- Replay Parsing ---
def parse_replay_file(replay_path):
    try:
        logger.info(f"Parsing replay: {os.path.basename(replay_path)}...")
        replay = Replay.from_path(replay_path)
        if replay.mode != GameMode.STD: logger.warning(f"Skipping non-standard replay: {replay.mode}"); return None
        beatmap_hash, mods_enum, replay_events, score = replay.beatmap_hash, replay.mods, replay.replay_data, replay.score
        logger.info(f"  Beatmap Hash: {beatmap_hash}"); logger.info(f"  Mods: {mods_enum}"); logger.info(f"  Score: {score}")
        input_actions, current_time = [], 0
        relevant_keys_mask = Key.M1 | Key.M2 | Key.K1 | Key.K2
        for idx, event in enumerate(replay_events):
            if event.time_delta < 0 and current_time == 0: logger.debug(f"Skipping initial negative time_delta: {event.time_delta}"); continue
            logger.debug(f"  Replay Frame {idx}: time_delta={event.time_delta}, current_keys={event.keys}")
            current_time += event.time_delta
            current_press_state = event.keys & relevant_keys_mask
            if current_press_state > 0:
                adjusted_input_time = current_time + MANUAL_REPLAY_OFFSET_MS
                input_actions.append({'time': adjusted_input_time, 'keys': current_press_state, 'original_time': current_time})
                logger.debug(f"    -> Input State Recorded: Frame={idx}, OrigTime={current_time}, AdjTime={adjusted_input_time}, Offset={MANUAL_REPLAY_OFFSET_MS}, KeysDown={current_press_state}")
        logger.info(f"  Found {len(input_actions)} input state frames (key/mouse down).")
        if not input_actions: logger.warning("No input actions found."); return None
        return {'beatmap_hash': beatmap_hash, 'mods': mods_enum, 'input_actions': input_actions, 'score': score}
    except Exception as e: logger.error(f"Error parsing replay {os.path.basename(replay_path)}: {e}"); traceback.print_exc(); return None

# --- Hit Window Calculation ---
def get_hit_window_ms(od, window_type='50', mods=Mod.NoMod):
    base_ms = {'300': 79.5, '100': 139.5, '50': 199.5}
    ms_reduction_per_od = {'300': 6, '100': 8, '50': 10}
    if window_type not in base_ms: raise ValueError("Invalid window_type.")
    try: od_float = float(od)
    except (ValueError, TypeError): od_float = 5.0
    window = base_ms[window_type] - ms_reduction_per_od[window_type] * od_float
    rate = 1.0
    if Mod.DoubleTime in mods or Mod.Nightcore in mods: rate = 1.5
    elif Mod.HalfTime in mods: rate = 0.75
    return max(0, window / rate)

# --- Correlation Logic ---
def correlate_inputs_and_calculate_offsets(input_actions, beatmap_data, beatmap_od, mods):
    if not beatmap_data or beatmap_od is None or not input_actions: return []
    hit_offsets, used_input_indices = [], set()
    last_successful_input_index = -1
    rate = 1.0
    if Mod.DoubleTime in mods or Mod.Nightcore in mods: rate = 1.5
    elif Mod.HalfTime in mods: rate = 0.75
    try:
        od = beatmap_od; miss_window_ms = get_hit_window_ms(od, '50', mods)
        logger.info(f"Using miss window (OD50): ±{miss_window_ms:.2f} ms (OD={od}, Mods={mods})")
    except Exception as e: logger.error(f"Error calculating miss window: {e}. Using default 200ms."); miss_window_ms = 200
    try:
        beatmap_objects = beatmap_data.get('hitObjects', [])
        if not beatmap_objects: logger.warning("Beatmap data contains no 'hitObjects'."); return []
        logger.info(f"Correlating {len(input_actions)} inputs with {len(beatmap_objects)} beatmap objects...")
        objects_correlated, skipped_object_count = 0, 0
        for obj_index, obj in enumerate(beatmap_objects):
            obj_type = obj.get('object_name')
            if obj_type not in ['circle', 'slider']: logger.debug(f"  -> Skipping HO {obj_index} (Type: {obj_type})"); skipped_object_count += 1; continue
            expected_hit_time_ms = obj.get('startTime')
            if expected_hit_time_ms is None: logger.warning(f"Skipping HO {obj_index} missing 'startTime'"); continue
            adjusted_expected_hit_time = expected_hit_time_ms / rate
            window_start, window_end = adjusted_expected_hit_time - miss_window_ms, adjusted_expected_hit_time + miss_window_ms
            best_match_input_index, min_abs_offset = -1, float('inf')
            current_search_start_index = last_successful_input_index + 1
            logger.debug(f" --> Correlating HO {obj_index} (Type:{obj_type}, AdjTime:{adjusted_expected_hit_time:.0f}ms), Window=[{window_start:.0f}ms, {window_end:.0f}ms], Searching inputs from index {current_search_start_index}...")
            found_potential_match_in_window = False
            for i in range(current_search_start_index, len(input_actions)):
                action = input_actions[i]; input_time_ms = action['time']
                logger.debug(f"    -> Checking Input {i} @ {input_time_ms:.0f}ms (Used: {i in used_input_indices})")
                if input_time_ms > window_end: logger.debug(f"       Input {i} too late. Stopping search."); break
                if window_start <= input_time_ms <= window_end:
                    found_potential_match_in_window = True
                    if i not in used_input_indices:
                        current_offset = input_time_ms - adjusted_expected_hit_time; current_abs_offset = abs(current_offset)
                        if current_abs_offset < min_abs_offset:
                            min_abs_offset = current_abs_offset; best_match_input_index = i
                            logger.debug(f"       Potential Best Match Found! Input {i} (Offset:{current_offset:+.2f}ms)")
                    else: logger.debug(f"       Input {i} within window but used.")
            if best_match_input_index != -1:
                matched_input_time_ms = input_actions[best_match_input_index]['time']
                offset = matched_input_time_ms - adjusted_expected_hit_time
                if abs(offset) <= miss_window_ms:
                    hit_offsets.append(offset); used_input_indices.add(best_match_input_index); objects_correlated += 1
                    last_successful_input_index = best_match_input_index
                    logger.debug(f"  --> SUCCESS: Matched HO {obj_index} with Input {best_match_input_index}. Offset: {offset:+.2f}. Last used index: {last_successful_input_index}")
                else: logger.warning(f"  --> REJECTED MATCH HO {obj_index}: Offset {offset:+.2f} outside window.")
            else:
                if found_potential_match_in_window: logger.debug(f"  --> MISS: No *unused* input found for HO {obj_index} (T={adjusted_expected_hit_time:.0f}).")
                else: logger.debug(f"  --> MISS: No input found *at all* for HO {obj_index} (T={adjusted_expected_hit_time:.0f}).")
        logger.info(f"Correlation complete. Matched {objects_correlated} hits. Skipped {skipped_object_count} objects. Found {len(hit_offsets)} offsets.")
        if not hit_offsets: logger.warning("No hits correlated.")
    except Exception as e: logger.error(f"Correlation error: {e}"); traceback.print_exc(); return []
    return hit_offsets

# --- Function to save stats ---
def save_stats_to_csv(timestamp, replay_name, map_name, mods, avg_offset, ur, matched_hits, score, star_rating):
    """Appends the analysis results to the stats CSV file."""
    file_exists = os.path.isfile(STATS_CSV_FILE)
    try:
        os.makedirs(os.path.dirname(STATS_CSV_FILE), exist_ok=True)
        with open(STATS_CSV_FILE, 'a', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['Timestamp', 'ReplayFile', 'MapName', 'Mods', 'AvgOffsetMs', 'UR', 'MatchedHits', 'Score', 'StarRating']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            if not file_exists or os.path.getsize(STATS_CSV_FILE) == 0: writer.writeheader(); logger.info(f"Created/found empty stats file: {STATS_CSV_FILE}")
            writer.writerow({
                'Timestamp': timestamp.strftime('%Y-%m-%d %H:%M:%S'), 'ReplayFile': replay_name, 'MapName': map_name, 'Mods': str(mods),
                'AvgOffsetMs': f"{avg_offset:+.2f}", 'UR': f"{ur:.2f}", 'MatchedHits': matched_hits,
                'Score': score, 'StarRating': f"{star_rating:.2f}" if star_rating is not None else "N/A"
            })
            logger.info(f"Stats saved to {STATS_CSV_FILE}")
    except IOError as e: logger.error(f"Error writing stats file {STATS_CSV_FILE}: {e}")
    except Exception as e: logger.error(f"Unexpected error saving stats: {e}"); traceback.print_exc()

# --- Analysis Worker ---
class AnalysisWorker(QObject):
    analysis_complete = pyqtSignal(dict)
    status_update = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    def __init__(self, replay_path): super().__init__(); self.replay_path = replay_path; self._is_running = True
    def run(self):
        try:
            if not self._is_running: return
            replay_basename = os.path.basename(self.replay_path)
            self.status_update.emit(f"Processing: {replay_basename}...")
            logger.info(f"--- Starting Analysis for {replay_basename} ---")
            analysis_timestamp = datetime.now()
            replay_data = parse_replay_file(self.replay_path)
            if not replay_data: logger.error("Failed to parse replay."); self.status_update.emit(f"Error parsing: {replay_basename}"); self.error_occurred.emit(f"Failed to parse replay: {replay_basename}"); return
            beatmap_hash, mods, input_actions, score = replay_data['beatmap_hash'], replay_data['mods'], replay_data['input_actions'], replay_data['score']
            map_path, od_from_db, sr_from_db = lookup_beatmap_in_db(beatmap_hash)
            if not map_path: logger.error(f"Could not find map path for hash {beatmap_hash}."); self.status_update.emit(f"Map not found: {replay_basename}"); self.error_occurred.emit(f"Map not found for hash: {beatmap_hash}"); return
            if od_from_db is None: logger.warning(f"Could not determine OD for hash {beatmap_hash}.")
            map_basename = os.path.basename(map_path)
            beatmap_data = parse_osu_file(map_path)
            if not beatmap_data: logger.error("Failed to parse beatmap."); self.status_update.emit(f"Error parsing map: {replay_basename}"); self.error_occurred.emit(f"Failed to parse map: {map_basename}"); return
            hit_offsets = correlate_inputs_and_calculate_offsets(input_actions, beatmap_data, od_from_db, mods)
            results = {"replay_name": replay_basename, "map_name": map_basename, "mods": str(mods), "score": score, "star_rating": sr_from_db, "avg_offset": None, "ur": None, "matched_hits": 0, "tendency": "N/A"}
            if hit_offsets:
                try:
                    average_offset = statistics.mean(hit_offsets); stdev_offset = statistics.stdev(hit_offsets) if len(hit_offsets) > 1 else 0.0
                    unstable_rate = stdev_offset * 10; matched_hits_count = len(hit_offsets)
                    results.update({"avg_offset": average_offset, "ur": unstable_rate, "matched_hits": matched_hits_count})
                    logger.info("--- Analysis Results ---"); logger.info(f" Replay: {replay_basename}"); logger.info(f" Map: {map_basename}"); logger.info(f" Mods: {mods}"); logger.info(f" Score: {score:,}"); logger.info(f" Star Rating: {sr_from_db:.2f}*" if sr_from_db is not None else "N/A")
                    if MANUAL_REPLAY_OFFSET_MS != 0: logger.info(f" Replay Time Offset: {MANUAL_REPLAY_OFFSET_MS} ms (Applied)")
                    logger.info(f" Average Hit Offset: {average_offset:+.2f} ms"); logger.info(f" Hit Offset StDev:   {stdev_offset:.2f} ms"); logger.info(f" Unstable Rate (UR): {unstable_rate:.2f}")
                    tendency = "ON TIME";
                    if average_offset < -2.0: tendency = "EARLY"
                    elif average_offset > 2.0: tendency = "LATE"
                    results["tendency"] = tendency; logger.info(f" Tendency: Hitting {tendency}")
                    print(f"Result for {replay_basename}: Average Hit Offset: {average_offset:+.2f} ms ({tendency})")
                    logger.info("------------------------")
                    save_stats_to_csv(timestamp=analysis_timestamp, replay_name=replay_basename, map_name=map_basename, mods=mods, avg_offset=average_offset, ur=unstable_rate, matched_hits=matched_hits_count, score=score, star_rating=sr_from_db)
                except statistics.StatisticsError as e: logger.error(f"Statistics error: {e}"); results["tendency"] = "Stat Error"
                except Exception as e: logger.error(f"Error calculating stats: {e}"); traceback.print_exc(); results["tendency"] = "Calc Error"
            else: logger.warning("--- Analysis Results ---"); logger.warning(" Could not calculate average hit offset."); logger.warning("------------------------"); results["tendency"] = "Error/No Data"
            self.analysis_complete.emit(results)
            self.status_update.emit("Monitoring...")
        except Exception as e:
            logger.error(f"Unhandled exception in AnalysisWorker: {e}")
            traceback.print_exc()
            self.error_occurred.emit(f"Unhandled error during analysis: {e}")
        finally:
            self._is_running = False
    def stop(self): self._is_running = False

# --- Watchdog Event Handler ---
class ReplayHandler(FileSystemEventHandler, QObject): # Inherit QObject
    new_replay_signal = pyqtSignal(str)
    def __init__(self): FileSystemEventHandler.__init__(self); QObject.__init__(self); self.last_event_time = 0; self.debounce_period = 2.0; self.last_processed_path = None
    def on_created(self, event):
        current_time = time.time()
        if not event.is_directory and event.src_path.lower().endswith(".osr"):
            file_path = event.src_path; logger.debug(f"Event detected: {file_path}")
            if current_time - self.last_event_time < self.debounce_period: logger.debug(f"Debouncing event (time): {os.path.basename(file_path)}"); return
            self.last_event_time = current_time
            time.sleep(0.5)
            if os.path.exists(file_path):
                try: s1=os.path.getsize(file_path); time.sleep(0.2); s2=os.path.getsize(file_path);
                except OSError as e: logger.error(f"Error checking size {file_path}: {e}")
                logger.info(f"Watchdog detected new replay: {os.path.basename(file_path)}")
                self.last_processed_path = file_path
                self.new_replay_signal.emit(file_path)
            else: logger.warning(f"File disappeared: {file_path}")

# --- Watchdog Monitor Thread ---
class MonitorThread(QThread):
    new_replay_found = pyqtSignal(str)
    def __init__(self, path_to_watch): super().__init__(); self.path_to_watch = path_to_watch; self.observer = Observer(); self.event_handler = ReplayHandler(); self.event_handler.new_replay_signal.connect(self.new_replay_found); self._is_running = True
    def run(self):
        logger.info(f"Starting monitor thread: {self.path_to_watch}"); self.observer.schedule(self.event_handler, self.path_to_watch, recursive=False); self.observer.start()
        try:
            while self._is_running: time.sleep(1)
        except Exception as e: logger.error(f"Monitor thread error: {e}"); traceback.print_exc()
        finally: self.observer.stop(); self.observer.join(); logger.info("Monitor thread stopped.")
    def stop(self): logger.info("Requesting monitor thread stop..."); self._is_running = False; self.observer.stop()

# --- Main GUI Window ---
class MainWindow(QMainWindow):
    request_analysis = pyqtSignal(str)
    def __init__(self):
        super().__init__()
        self.setWindowTitle("osu! Hit Offset Analyzer")
        self.setGeometry(100, 100, 900, 700)
        self.analysis_thread = None; self.analysis_worker = None
        self.replay_queue = []; self.is_analyzing = False
        self.central_widget = QWidget(); self.setCentralWidget(self.central_widget)

        # --- Sidebar Setup ---
        sidebar_widget = QWidget(); sidebar_widget.setObjectName("SidebarWidget"); sidebar_widget.setFixedWidth(161)
        sidebar_layout = QVBoxLayout(sidebar_widget); sidebar_layout.setContentsMargins(0, 0, 0, 10); sidebar_layout.setSpacing(0); sidebar_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.analyzer_button = QPushButton("Analyzer"); self.analyzer_button.setObjectName("SidebarButton"); self.analyzer_button.setFixedHeight(44); self.analyzer_button.setProperty("selected", True)
        self.history_button = QPushButton("History"); self.history_button.setObjectName("SidebarButton"); self.history_button.setFixedHeight(44); self.history_button.setProperty("selected", False)
        sidebar_layout.addSpacerItem(QSpacerItem(20, 24, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed))
        sidebar_layout.addWidget(self.analyzer_button); sidebar_layout.addSpacerItem(QSpacerItem(20, 12, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)); sidebar_layout.addWidget(self.history_button)
        sidebar_layout.addStretch()

# --- MODIFIED: Add GitHub Icon ---
        github_icon_button = QPushButton()
        github_icon_button.setObjectName("GitHubButton")
        github_icon_button.setCursor(Qt.CursorShape.PointingHandCursor)
        github_icon_button.setFlat(True)  # Make background transparent

# Set button size (larger than icon to allow padding)
        github_icon_button.setFixedSize(48, 48)

        try:

            if getattr(sys, 'frozen', False):
                base_dir = sys._MEIPASS
            else:
                base_dir = os.path.dirname(os.path.abspath(__file__))

            icon_path = os.path.join(base_dir, "resources", "github_icon.png")
            logger.debug(f"Attempting to load icon from: {icon_path}")

            if os.path.isfile(icon_path):
                icon= QIcon(icon_path)
                github_icon_button.setIcon(icon)
                github_icon_button.setIconSize(QSize(48, 48))  # Set icon size
                logger.debug("GitHub icon loaded successfully.")
            else:
                alt_icon_path = os.path.join(base_dir, "resources", "github_icon_alt.png")
                if os.path.exists(alt_icon_path):
                    icon = QIcon(alt_icon_path)
                    github_icon_button.setIcon(icon)
                    github_icon_button.setIconSize(QSize(32, 32))  # Set icon size
                    logger.debug("GitHub icon loaded successfully from alternate path.")
                else:
                    raise FileNotFoundError(f"Icon file not found: {icon_path}")
        
        except Exception as e:
            logger.error(f"Error loading GitHub icon: {e}")
            github_icon_button.setText("GitHub")
            github_icon_button.setStyleSheet("font-size: 10pt; font-weight: bold; border: 1px solid #555")

        # Connect click event
        github_icon_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/Luskebusk/osu-replay-offset-analyzer")))

        sidebar_layout.addWidget(github_icon_button, 0, Qt.AlignmentFlag.AlignCenter) # Add icon button
        sidebar_layout.addSpacerItem(QSpacerItem(20, 5, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)) # Small spacer at bottom
        # --- END MODIFIED ---

        # --- Content Area ---
        self.stacked_widget = QStackedWidget(); self.stacked_widget.setObjectName("ContentWidget")

        # --- Page 1: Analyzer Screen ---
        analyzer_page = QWidget()
        self.results_layout = QVBoxLayout(analyzer_page)
        self.results_layout.setContentsMargins(30, 10, 30, 0); self.results_layout.setSpacing(5); self.results_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.stacked_widget.addWidget(analyzer_page)
        # Labels
        self.map_title_label = QLabel("N/A"); self.map_title_label.setObjectName("MapTitleLabel")
        self.tendency_label = QLabel("Tendency: N/A"); self.tendency_label.setObjectName("StatLabel")
        self.offset_label = QLabel("Average Hit Offset: N/A"); self.offset_label.setObjectName("StatLabel")
        self.score_label = QLabel("Score: N/A"); self.score_label.setObjectName("StatLabel")
        self.ur_label = QLabel("Unstable Rate: N/A"); self.ur_label.setObjectName("StatLabel")
        self.matched_label = QLabel("Matched Hits: N/A"); self.matched_label.setObjectName("StatLabel")
        self.sr_label = QLabel("Star Rating: N/A"); self.sr_label.setObjectName("StatLabel")
        self.status_label = QLabel("Status: Monitoring...")
        status_font = QFont(); status_font.setPointSize(10); self.status_label.setFont(status_font)
        # Add widgets to layout
        self.results_layout.addWidget(self.map_title_label)
        self.results_layout.addWidget(self.tendency_label)
        self.results_layout.addWidget(self.offset_label)
        self.results_layout.addWidget(self.score_label)
        self.results_layout.addWidget(self.ur_label)
        self.results_layout.addWidget(self.matched_label)
        self.results_layout.addWidget(self.sr_label)
        self.results_layout.addStretch()
        # Bottom Info Bar
        bottom_bar_widget = QWidget(); bottom_bar_widget.setFixedHeight(40)
        bottom_bar_layout = QHBoxLayout(bottom_bar_widget); bottom_bar_layout.setContentsMargins(10, 0, 10, 0)
        self.mods_info_label = QLabel("Mods: N/A"); self.mods_info_label.setObjectName("BottomBarLabel")
        bottom_bar_layout.addWidget(self.mods_info_label, 0, Qt.AlignmentFlag.AlignLeft)
        bottom_bar_layout.addStretch(1)
        info_label = QLabel("Unstable Rate = Lower is generally better/more consistent"); info_label.setObjectName("BottomBarInfoLabel"); info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bottom_bar_layout.addWidget(info_label, 0, Qt.AlignmentFlag.AlignCenter)
        bottom_bar_layout.addStretch(1)
        self.status_label.setObjectName("BottomBarLabel")
        bottom_bar_layout.addWidget(self.status_label, 0, Qt.AlignmentFlag.AlignRight)
        self.results_layout.addWidget(bottom_bar_widget)

        # --- Page 2: History Screen ---
        self.stats_page = QWidget()
        self.stats_layout = QVBoxLayout(self.stats_page)
        self.stats_layout.setSpacing(6)
        self.stacked_widget.addWidget(self.stats_page)
        self.filter_input = QLineEdit(); self.filter_input.setObjectName("SearchAreaValue"); self.filter_input.setPlaceholderText("Filter by Map Name..."); self.stats_layout.addWidget(self.filter_input)
        self.stats_tree = QTreeWidget(); self.stats_tree.setObjectName("BoxForHistory")
        self.stats_tree.setColumnCount(8); self.stats_tree.setHeaderLabels(['Map / Replay File', 'Timestamp', 'Mods', 'Score', 'AvgOffsetMs', 'UR', 'MatchedHits', 'StarRating'])
        self.stats_tree.setSortingEnabled(True); self.stats_tree.header().setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        self.stats_tree.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents); self.stats_tree.header().setStretchLastSection(False)
        self.stats_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch); self.stats_tree.setAlternatingRowColors(True)
        self.stats_layout.addWidget(self.stats_tree)

        # --- Main Layout ---
        main_hbox = QHBoxLayout(); main_hbox.setContentsMargins(0, 0, 0, 0); main_hbox.setSpacing(0)
        main_hbox.addWidget(sidebar_widget); main_hbox.addWidget(self.stacked_widget)
        self.central_widget.setLayout(main_hbox)

        # --- Connections ---
        self.analyzer_button.clicked.connect(self.show_analyzer_page)
        self.history_button.clicked.connect(self.show_history_page)
        self.filter_input.textChanged.connect(self.filter_stats_tree)
        # self.request_analysis.connect(self.start_analysis_thread) # Connected in main

    def show_analyzer_page(self):
        self.stacked_widget.setCurrentIndex(0); self.analyzer_button.setProperty("selected", True); self.history_button.setProperty("selected", False); self.update_button_styles()
    def show_history_page(self):
        self.stacked_widget.setCurrentIndex(1); self.analyzer_button.setProperty("selected", False); self.history_button.setProperty("selected", True); self.update_button_styles(); self.load_stats_data()
    def update_button_styles(self):
        self.analyzer_button.style().unpolish(self.analyzer_button); self.analyzer_button.style().polish(self.analyzer_button)
        self.history_button.style().unpolish(self.history_button); self.history_button.style().polish(self.history_button)
    def load_stats_data(self):
        logger.info(f"Loading stats from {STATS_CSV_FILE}")
        self.stats_tree.clear(); self.stats_tree.setSortingEnabled(False)
        grouped_stats = defaultdict(list)
        try:
            if not os.path.exists(STATS_CSV_FILE): logger.warning(f"Stats file '{STATS_CSV_FILE}' not found."); return
            with open(STATS_CSV_FILE, 'r', newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile); rows = list(reader)
                for row in rows: grouped_stats[row.get('MapName', 'Unknown Map')].append(row)
            bold_font = QFont(); bold_font.setBold(True)
            tree_items = []
            for map_name, plays in grouped_stats.items():
                high_score = 0; best_play_timestamp = None
                try:
                    valid_plays = [(int(p.get('Score', 0)), p.get('Timestamp')) for p in plays if p.get('Score', '').isdigit()]
                    if valid_plays: high_score, best_play_timestamp = max(valid_plays, key=lambda item: item[0])
                except ValueError: pass
                map_item = QTreeWidgetItem(); map_item.setText(0, map_name); map_item.setText(1, f"({len(plays)} plays)")
                for play_data in plays:
                    child_item = QTreeWidgetItem()
                    child_item.setText(1, play_data.get('Timestamp', '')); child_item.setText(2, play_data.get('Mods', ''))
                    score_str = play_data.get('Score', ''); child_item.setText(3, f"{int(score_str):,}" if score_str.isdigit() else score_str)
                    child_item.setText(4, play_data.get('AvgOffsetMs', '')); child_item.setText(5, play_data.get('UR', ''))
                    child_item.setText(6, play_data.get('MatchedHits', '')); child_item.setText(7, play_data.get('StarRating', ''))
                    try:
                        if int(score_str) == high_score and play_data.get('Timestamp') == best_play_timestamp:
                             for col in range(1, self.stats_tree.columnCount()): child_item.setFont(col, bold_font)
                    except ValueError: pass
                    map_item.addChild(child_item)
                tree_items.append(map_item)
            self.stats_tree.addTopLevelItems(tree_items); logger.info(f"Loaded {len(grouped_stats)} map groups into tree.")
        except Exception as e: logger.error(f"Error loading stats data: {e}"); traceback.print_exc()
        finally: self.stats_tree.setSortingEnabled(True)
    def filter_stats_tree(self):
        filter_text = self.filter_input.text().lower()
        root = self.stats_tree.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i); map_name = item.text(0).lower(); item.setHidden(filter_text not in map_name)

    @pyqtSlot(dict)
    def update_results(self, results_dict):
        logger.info("Updating GUI with analysis results.")
        self.map_title_label.setText(f"{results_dict.get('map_name', 'N/A')}")
        self.tendency_label.setText(f"Tendency: {results_dict.get('tendency', 'N/A')}")
        avg_offset = results_dict.get('avg_offset')
        if avg_offset is not None:
            self.offset_label.setText(f"Average Hit Offset: {avg_offset:+.2f} ms")
        else:
            self.offset_label.setText("Average Hit Offset: N/A")
        score = results_dict.get('score', 'N/A'); self.score_label.setText(f"Score: {score:,}" if isinstance(score, int) else "Score: N/A")
        ur = results_dict.get('ur'); self.ur_label.setText(f"Unstable Rate: {ur:.2f}" if ur is not None else "Unstable Rate: N/A")
        self.matched_label.setText(f"Matched Hits: {results_dict.get('matched_hits', 'N/A')}")
        sr = results_dict.get('star_rating'); self.sr_label.setText(f"Star Rating: {sr:.2f}*" if sr is not None else "Star Rating: N/A")
        self.mods_info_label.setText(f"Mods: {results_dict.get('mods', 'N/A')}")

        self.is_analyzing = False
        logger.debug("Analysis flag set to False in update_results.")
        self.process_next_in_queue()

        if self.stacked_widget.currentWidget() == self.stats_page: self.load_stats_data()

    def update_status(self, status_text): self.status_label.setText(f"Status: {status_text}")

    @pyqtSlot(str)
    def start_analysis_thread(self, replay_path):
        logger.debug(f"start_analysis_thread called for: {replay_path}")
        if self.is_analyzing:
            logger.warning(f"Analysis already in progress. Queueing replay: {os.path.basename(replay_path)}")
            if replay_path not in self.replay_queue: self.replay_queue.append(replay_path)
            return

        self.is_analyzing = True
        logger.info(f"Starting analysis worker for: {replay_path}")
        self.analysis_worker = AnalysisWorker(replay_path); self.analysis_thread = QThread(self)
        self.analysis_worker.moveToThread(self.analysis_thread); self.analysis_worker.analysis_complete.connect(self.update_results)
        self.analysis_worker.status_update.connect(self.update_status); self.analysis_worker.error_occurred.connect(self.handle_analysis_error)
        self.analysis_thread.started.connect(self.analysis_worker.run); self.analysis_thread.finished.connect(self.on_analysis_finished)
        self.analysis_thread.start()

    @pyqtSlot()
    def on_analysis_finished(self):
        """Schedules thread and worker objects for deletion."""
        logger.debug("Analysis thread finished signal received.")
        if self.analysis_worker: self.analysis_worker.deleteLater(); logger.debug("Analysis worker scheduled for deletion.")
        if self.analysis_thread: self.analysis_thread.deleteLater(); logger.debug("Analysis thread scheduled for deletion.")
        self.analysis_worker = None
        self.analysis_thread = None

    def process_next_in_queue(self):
        """Checks the queue and starts the next analysis if needed."""
        logger.debug(f"Processing queue. Queue size: {len(self.replay_queue)}, Analyzing: {self.is_analyzing}")
        if self.replay_queue and not self.is_analyzing:
            self._process_queue_item()
        else:
            logger.debug(f"Queue empty or analysis still running/cleaning up.")

    def _process_queue_item(self):
        if self.replay_queue and not self.is_analyzing:
            next_replay = self.replay_queue.pop(0)
            logger.info(f"Processing next replay from queue: {os.path.basename(next_replay)}")
            self.start_analysis_thread(next_replay)

    @pyqtSlot(str)
    def handle_analysis_error(self, error_msg):
        """Handles errors emitted from the worker thread."""
        logger.error(f"Analysis error signal received: {error_msg}")
        self.update_status(f"Error: {error_msg}")
        self.is_analyzing = False
        logger.debug("Analysis flag set to False in handle_analysis_error.")
        self.process_next_in_queue()

    def closeEvent(self, event):
        """Ensure threads are stopped cleanly on window close."""
        logger.info("Close event received. Stopping threads...")
        self.replay_queue = []
        if hasattr(self, 'monitor_thread') and self.monitor_thread: self.monitor_thread.stop(); self.monitor_thread.wait()
        if self.analysis_thread and self.analysis_thread.isRunning():
            logger.info("Stopping active analysis thread...")
            if self.analysis_worker: self.analysis_worker.stop()
            self.analysis_thread.quit(); self.analysis_thread.wait()
        event.accept()

# --- Main Execution ---
if __name__ == "__main__":
    config_created = False
    try:
        logger = setup_logging()
        logger.info("Starting osu! Average Hit Offset Analyzer"); logger.info("==========================================")
        config_created = load_config()
        OSU_DB = load_osu_database(OSU_DB_PATH)
    except (NotADirectoryError, FileNotFoundError, configparser.Error, ValueError, ImportError, Exception) as e:
        logger.critical(f"Initialization failed: {e}"); traceback.print_exc()
        if isinstance(e, ImportError): print("\n--- Import Error ---\nPlease ensure required libraries and script dependencies are installed/accessible.\n--------------------\n")
        try:
            app_temp = QApplication.instance();
            if app_temp is None: app_temp = QApplication(sys.argv)
            error_box = QMessageBox(); error_box.setIcon(QMessageBox.Icon.Critical)
            error_box.setWindowTitle("Initialization Error")
            error_box.setText(f"Failed to start Analyzer:\n{e}\n\nCheck logs for details (in {USER_DATA_DIR if USER_DATA_DIR != '.' else 'current directory'}).")
            error_box.exec()
        except Exception as e_gui: print(f"Could not display GUI error message: {e_gui}")
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLE)

    if config_created:
        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.Icon.Information)
        msg_box.setWindowTitle("Configuration File Created")
        msg_box.setText(f"A default configuration file has been created.\n\nPlease edit it with your osu! paths:\n\n{CONFIG_FILE}")
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg_box.exec()
        if not REPLAYS_FOLDER or not SONGS_FOLDER or not OSU_DB_PATH:
             logger.warning("Exiting after creating default config as paths are empty.")
             sys.exit(0)

    logger.info(f"Replays Folder: {REPLAYS_FOLDER.replace(os.sep, '/')}")
    logger.info(f"Songs Folder: {SONGS_FOLDER.replace(os.sep, '/')}")
    logger.info(f"osu!.db Path: {OSU_DB_PATH.replace(os.sep, '/')}")

    main_window = MainWindow()
    # Connect signal from main window instance
    main_window.request_analysis.connect(main_window.start_analysis_thread)
    main_window.show()

    monitor_thread = MonitorThread(REPLAYS_FOLDER)
    monitor_thread.new_replay_found.connect(main_window.start_analysis_thread) # Connect watcher signal
    main_window.monitor_thread = monitor_thread
    monitor_thread.start()
    logger.info(f"\nMonitoring for new replays in: {REPLAYS_FOLDER.replace(os.sep, '/')}")
    print("GUI Started. Close the window or press Ctrl+C in terminal to stop.")

    sys.exit(app.exec())

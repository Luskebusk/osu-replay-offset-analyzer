# backend.py

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
import re
from datetime import datetime
from collections import defaultdict # For grouping stats

# --- PyQt6 Imports (Keep necessary ones for backend classes) ---
try:
    # Keep QObject, QThread, pyqtSignal for worker/monitor
    from PyQt6.QtCore import QThread, pyqtSignal, QObject, pyqtSlot
    # Keep Mod, Key, GameMode from osrparse
    from osrparse import Replay, GameMode, Mod, Key
    # Keep FileSystemEventHandler, Observer from watchdog
    from watchdog.observers import Observer; from watchdog.events import FileSystemEventHandler
except ImportError as e:
    # More specific error reporting
    print(f"ERROR: Failed to import required library. Dependency missing or environment issue: {e}")
    # Depending on which import failed, sys.exit might still be appropriate
    # For now, just print the error to allow potential partial functionality
    # sys.exit(1)

# --- Parser Imports ---
try: from osu_db import osu_db
except ImportError: print("ERROR: Failed to import 'osu_db'."); sys.exit(1)
try: from beatmapparser import BeatmapParser
except ImportError: print("ERROR: Failed to import 'beatmapparser'."); sys.exit(1)

# --- Configuration ---
APP_NAME = "OsuAnalyzer" # Define app name for folder

def get_user_data_dir():
    """Gets the path to the application's data directory in AppData/Local."""
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

# --- Global Variables (Potentially refactor later if needed) ---
REPLAYS_FOLDER = ""
SONGS_FOLDER = ""
OSU_DB_PATH = ""
OSU_DB = None
MANUAL_REPLAY_OFFSET_MS = 0

# --- Logging Setup ---
logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger()

# Removed DARK_STYLE constant

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

# --- Configuration Loading --- (Modified to return paths for GUI) ---
def load_config():
    """Loads and validates paths and settings from the configuration file.
       Returns a tuple: (created_default_config, config_data_dict)
       config_data_dict contains loaded paths and settings or defaults.
    """
    global MANUAL_REPLAY_OFFSET_MS, REPLAYS_FOLDER, SONGS_FOLDER, OSU_DB_PATH
    config = configparser.ConfigParser()
    config_data = {
        'replays_folder': '',
        'songs_folder': '',
        'osu_db_path': '',
        'log_level': 'INFO',
        'replay_offset': -8, # Default offset
        'minimize_to_tray': True, 
        'launch_minimized': False,
        'start_stop_with_osu': False
    }
    created_default_config = False

    if not os.path.exists(CONFIG_FILE):
        print(f"'{os.path.basename(CONFIG_FILE)}' not found in '{os.path.dirname(CONFIG_FILE)}'. Creating default.")
        print(f"Please edit it with your actual osu! paths.")
        config['Paths'] = {'OsuReplaysFolder': '', 'OsuSongsFolder': '', 'OsuDbPath': ''}
        config['Settings'] = {
            'LogLevel': config_data['log_level'], 
            'ReplayTimeOffsetMs': str(config_data['replay_offset']),
            'MinimizeToTray': str(config_data['minimize_to_tray']),
            'LaunchMinimized': str(config_data['launch_minimized']),
            'StartStopWithOsu': str(config_data['start_stop_with_osu'])
        }
        try:
            os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
            with open(CONFIG_FILE, 'w') as cf: config.write(cf)
            print(f"Default '{CONFIG_FILE}' created.")
            created_default_config = True
            # Set globals to empty for the return dict
            REPLAYS_FOLDER, SONGS_FOLDER, OSU_DB_PATH = '', '', ''
            MANUAL_REPLAY_OFFSET_MS = config_data['replay_offset']
            # Need to set up logging even if default is created
            setup_logging()
        except IOError as e: print(f"ERROR: Could not write default config file: {e}"); sys.exit(f"Exiting. Could not create '{CONFIG_FILE}'.")
        # Return default data even if created
        # Need to update the returned dict with ALL defaults
        for key in ['log_level', 'replay_offset', 'minimize_to_tray', 'launch_minimized', 'start_stop_with_osu']:
            config_data[key] = config['Settings'].get(key.capitalize().replace('_', ''), config_data[key])
            if isinstance(config_data[key], str) and config_data[key].lower() in ['true', 'false']:
                config_data[key] = config_data[key].lower() == 'true'
            elif key == 'replay_offset':
                 try:
                      config_data[key] = int(config_data[key])
                 except ValueError:
                      config_data[key] = -8 # Default back
        return created_default_config, config_data

    # --- If config exists, read it --- #
    try: config.read(CONFIG_FILE)
    except configparser.Error as e: print(f"ERROR: Error reading config file: {e}"); raise ValueError(f"Error reading config: {e}") from e

    paths_valid = True
    if 'Paths' in config:
        config_data['replays_folder'] = config['Paths'].get('OsuReplaysFolder', '')
        config_data['songs_folder'] = config['Paths'].get('OsuSongsFolder', '')
        config_data['osu_db_path'] = config['Paths'].get('OsuDbPath', '')
        if not config_data['replays_folder'] or not config_data['songs_folder'] or not config_data['osu_db_path']:
            print(f"WARNING: One or more paths in '{CONFIG_FILE}' are empty.")
            paths_valid = False
    else: print("ERROR: Missing [Paths] in config.ini"); paths_valid = False

    if 'Settings' in config:
        config_data['log_level'] = config['Settings'].get('LogLevel', 'INFO').upper()
        manual_offset_str = config['Settings'].get('ReplayTimeOffsetMs', '-8')
        try:
             config_data['replay_offset'] = int(manual_offset_str)
        except ValueError: config_data['replay_offset'] = -8; print(f"WARNING: Invalid ReplayTimeOffsetMs '{manual_offset_str}'. Using -8 ms.")
        # --- Read new boolean settings --- 
        config_data['minimize_to_tray'] = config['Settings'].getboolean('MinimizeToTray', config_data['minimize_to_tray']) # Use getboolean
        config_data['launch_minimized'] = config['Settings'].getboolean('LaunchMinimized', config_data['launch_minimized'])
        config_data['start_stop_with_osu'] = config['Settings'].getboolean('StartStopWithOsu', config_data['start_stop_with_osu'])
    else: 
        print("WARNING: Missing [Settings] section in config.ini. Using defaults.")
        # Ensure defaults are set if section is missing
        config_data['minimize_to_tray'] = True
        config_data['launch_minimized'] = False
        config_data['start_stop_with_osu'] = False

    _logger = setup_logging() # Setup logging AFTER reading config

    # Update global vars
    REPLAYS_FOLDER = config_data['replays_folder']
    SONGS_FOLDER = config_data['songs_folder']
    OSU_DB_PATH = config_data['osu_db_path']
    MANUAL_REPLAY_OFFSET_MS = config_data['replay_offset']

    # Validate paths *after* setting globals
    if paths_valid:
        if not os.path.isdir(REPLAYS_FOLDER):
            _logger.error(f"Replays folder not found: {REPLAYS_FOLDER}"); paths_valid = False
        if not os.path.isdir(SONGS_FOLDER):
            _logger.error(f"Songs folder not found: {SONGS_FOLDER}"); paths_valid = False
        if not os.path.isfile(OSU_DB_PATH):
            _logger.error(f"osu!.db not found: {OSU_DB_PATH}"); paths_valid = False

    if paths_valid:
         _logger.info("Configuration paths validated.")
    else:
         _logger.error(f"One or more paths in '{CONFIG_FILE}' are invalid or missing. Please configure them.")

    _logger.info(f"Manual Replay Time Offset set to: {MANUAL_REPLAY_OFFSET_MS} ms")
    _logger.info(f"Using configuration file: {CONFIG_FILE}")
    print(f"INFO: Config file location: {CONFIG_FILE}")

    # Return whether default was created and the loaded data
    return created_default_config, config_data

# --- Save Settings Function (for GUI) ---
def save_settings(replays_folder, songs_folder, osu_db_path, log_level, time_offset, 
                  minimize_to_tray, launch_minimized, start_stop_with_osu):
    """Saves settings to config file and updates global variables.
       Returns True on success, False on failure.
    """
    global REPLAYS_FOLDER, SONGS_FOLDER, OSU_DB_PATH, MANUAL_REPLAY_OFFSET_MS, OSU_DB

    # Validate inputs (basic validation)
    if not isinstance(replays_folder, str) or not os.path.isdir(replays_folder):
        logger.error("Invalid Replays folder path provided to save_settings.")
        return False, "Invalid Replays folder path."
    if not isinstance(songs_folder, str) or not os.path.isdir(songs_folder):
        logger.error("Invalid Songs folder path provided to save_settings.")
        return False, "Invalid Songs folder path."
    if not isinstance(osu_db_path, str) or not os.path.isfile(osu_db_path):
        logger.error("Invalid osu!.db path provided to save_settings.")
        return False, "Invalid osu!.db path."
    if log_level not in ["DEBUG", "INFO", "WARNING", "ERROR"]:
        logger.warning(f"Invalid log level '{log_level}' provided. Defaulting to INFO.")
        log_level = "INFO"
    try:
        time_offset = int(time_offset)
    except (ValueError, TypeError):
        logger.error("Invalid Time Offset provided to save_settings.")
        return False, "Time Offset must be an integer."
    if not isinstance(minimize_to_tray, bool):
        logger.error("Invalid MinimizeToTray value provided to save_settings.")
        return False, "MinimizeToTray must be True or False."
    if not isinstance(launch_minimized, bool):
        logger.error("Invalid LaunchMinimized value provided to save_settings.")
        return False, "LaunchMinimized must be True or False."
    if not isinstance(start_stop_with_osu, bool):
        logger.error("Invalid StartStopWithOsu value provided to save_settings.")
        return False, "StartStopWithOsu must be True or False."

    # Save to config file
    config = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        try: config.read(CONFIG_FILE)
        except Exception as e: logger.error(f"Error reading config file before saving: {e}")

    if 'Paths' not in config: config['Paths'] = {}
    if 'Settings' not in config: config['Settings'] = {}

    config['Paths']['OsuReplaysFolder'] = replays_folder
    config['Paths']['OsuSongsFolder'] = songs_folder
    config['Paths']['OsuDbPath'] = osu_db_path
    config['Settings']['LogLevel'] = log_level
    config['Settings']['ReplayTimeOffsetMs'] = str(time_offset)
    # --- Save new boolean settings --- 
    config['Settings']['MinimizeToTray'] = str(minimize_to_tray)
    config['Settings']['LaunchMinimized'] = str(launch_minimized)
    config['Settings']['StartStopWithOsu'] = str(start_stop_with_osu)

    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, 'w') as cf: config.write(cf)

        # --- Update global variables --- #
        need_reload_db = OSU_DB_PATH != osu_db_path
        path_changed = REPLAYS_FOLDER != replays_folder # Need to know if monitor path changed
        REPLAYS_FOLDER = replays_folder
        SONGS_FOLDER = songs_folder
        OSU_DB_PATH = osu_db_path
        MANUAL_REPLAY_OFFSET_MS = time_offset

        # Reload logging
        setup_logging()

        # Reload database if path changed (should be handled by caller?)
        if need_reload_db:
            logger.info("osu!.db path changed, database will need reloading.")
            try:
                OSU_DB = load_osu_database(OSU_DB_PATH)
                logger.info("osu!.db reloaded successfully after settings save.")
            except Exception as e:
                 logger.error(f"Error reloading database after settings save: {e}")
                 return False, f"Settings saved, but failed to reload database: {e}"

        logger.info("Settings saved successfully")
        # Return success and whether the monitor path needs restarting
        return True, path_changed

    except Exception as e:
        logger.error(f"Error saving settings: {e}")
        return False, f"Failed to write settings file: {e}"

# --- Load osu!.db ---
def load_osu_database(db_path):
    global OSU_DB # Ensure we modify the global OSU_DB
    logger.info(f"Loading osu!.db from: {db_path}...")
    start_time = time.time()
    try:
        OSU_DB = osu_db.parse_file(db_path) # Assign to global
        logger.info(f"osu!.db loaded successfully in {time.time() - start_time:.2f} seconds.")
        return OSU_DB # Return the loaded data
    except Exception as e:
        logger.critical(f"FATAL: Failed to load/parse osu!.db: {e}")
        traceback.print_exc()
        # Don't sys.exit here, let the GUI handle it
        raise RuntimeError(f"Failed to load osu!.db: {e}") from e # Raise exception for GUI

# --- Beatmap Lookup (Uses global OSU_DB, SONGS_FOLDER) ---
def lookup_beatmap_in_db(beatmap_hash):
    # Keep this function largely as is, using global OSU_DB
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
                folder_name = found_entry.folder_name
                osu_filename = found_entry.osu_file_name
                od = found_entry.overall_difficulty
                if hasattr(found_entry, 'star_rating_osu'):
                    sr_osu = found_entry.star_rating_osu
                    if sr_osu and hasattr(sr_osu, '__iter__'):
                        for sr_entry in sr_osu:
                            if hasattr(sr_entry, 'mods') and sr_entry.mods == 0:
                                if hasattr(sr_entry, 'rating'):
                                    star_rating = sr_entry.rating
                                    logger.info(f"Found NoMod SR in star_rating_osu: {star_rating}")
                                    break
                if star_rating is None: logger.warning(f"Could not find NoMod SR for hash {beatmap_hash}")
                if folder_name and osu_filename:
                    logger.info(f"Found beatmap entry: {folder_name}\\{osu_filename}")
                    full_map_path = os.path.join(SONGS_FOLDER, folder_name, osu_filename)
                    logger.info(f"  Constructed Path: {full_map_path}")
                    logger.info(f"  Overall Difficulty (OD): {od}")
                    logger.info(f"  Star Rating (NoMod): {star_rating if star_rating is not None else 'N/A'}")
                    if os.path.isfile(full_map_path):
                        return full_map_path, float(od) if od is not None else None, float(star_rating) if star_rating is not None else None
                    else: logger.warning(f"DB entry found but file missing: {full_map_path}"); return None, None, None
                else: logger.warning(f"DB entry for hash {beatmap_hash} missing path info."); return None, None, None
            except AttributeError as ae: logger.warning(f"DB entry for hash {beatmap_hash} missing attribute ({ae})."); return None, None, None
        else: logger.warning(f"Beatmap hash {beatmap_hash} not found in osu!.db."); return None, None, None
    except Exception as e: logger.error(f"Error looking up hash {beatmap_hash}: {e}"); traceback.print_exc(); return None, None, None

# --- .osu File Parsing (Uses BeatmapParser) ---
def parse_osu_file(map_path):
    # Keep this function as is
    logger.info(f"Parsing beatmap: {os.path.basename(map_path)} using BeatmapParser...")
    star_rating = None
    try:
        with open(map_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            difficulty_section = re.search(r'\[Difficulty\](.*?)(?:\[|$)', content, re.DOTALL)
            if difficulty_section:
                difficulty_text = difficulty_section.group(1)
                sr_match = re.search(r'StarRating:([0-9\.]+)', difficulty_text)
                if not sr_match: sr_match = re.search(r'OverallDifficulty:([0-9\.]+)', difficulty_text)
                if sr_match: star_rating = float(sr_match.group(1)); logger.info(f"Found star rating in .osu file: {star_rating}")
        parser = BeatmapParser()
        with open(map_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f: parser.read_line(line)
        parser.build_beatmap()
        beatmap_data = parser.beatmap
        if star_rating is not None: beatmap_data['star_rating'] = star_rating
        logger.info("Beatmap parsed successfully with BeatmapParser.")
        return beatmap_data
    except Exception as e: logger.error(f"Error parsing .osu file {os.path.basename(map_path)}: {e}"); traceback.print_exc(); return None

# --- Replay Parsing (Uses global MANUAL_REPLAY_OFFSET_MS) ---
def parse_replay_file(replay_path):
    # Keep this function as is
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
    # Keep this function as is
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
    # Keep this function as is
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

# --- Analysis Worker (Keep as QObject for signals/slots) ---
class AnalysisWorker(QObject):
    analysis_complete = pyqtSignal(dict) # Signal emits analysis results dictionary
    status_update = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, replay_path):
        super().__init__()
        self.replay_path = replay_path
        self._is_running = True

    @pyqtSlot() # Explicitly mark as a slot if needed (good practice)
    def run(self):
        try:
            if not self._is_running:
                return

            replay_basename = os.path.basename(self.replay_path)
            self.status_update.emit(f"Processing: {replay_basename}...")
            logger.info(f"--- Starting Analysis for {replay_basename} ---")
            analysis_timestamp = datetime.now() # Keep timestamp for potential future use if needed

            replay_data = parse_replay_file(self.replay_path)
            if not replay_data:
                logger.error("Failed to parse replay.")
                self.status_update.emit(f"Error parsing: {replay_basename}")
                self.error_occurred.emit(f"Failed to parse replay: {replay_basename}")
                return

            beatmap_hash, mods, input_actions, score = replay_data['beatmap_hash'], replay_data['mods'], replay_data['input_actions'], replay_data['score']
            map_path, od_from_db, sr_from_db = lookup_beatmap_in_db(beatmap_hash)

            if not map_path:
                logger.error(f"Could not find map path for hash {beatmap_hash}.")
                self.status_update.emit(f"Map not found: {replay_basename}")
                self.error_occurred.emit(f"Map not found for hash: {beatmap_hash}")
                return

            if od_from_db is None:
                logger.warning(f"Could not determine OD for hash {beatmap_hash}.")

            map_basename = os.path.basename(map_path)

            # Try to extract star rating from .osu file if not found in db
            if sr_from_db is None:
                try:
                    with open(map_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        if '[Difficulty]' in content:
                            diff_section = content.split('[Difficulty]')[1].split('[')[0]
                            values = []
                            for attr in ['HPDrainRate', 'CircleSize', 'OverallDifficulty', 'ApproachRate']:
                                match = re.search(r'{0}:([0-9\.]+)'.format(attr), diff_section)
                                if match:
                                    values.append(float(match.group(1)))
                            if len(values) >= 2:
                                sr_estimate = sum(values) / len(values) * 0.5
                                logger.info(f"Estimated star rating from .osu file: {sr_estimate:.2f}*")
                                sr_from_db = sr_estimate
                except Exception as e:
                    logger.error(f"Error extracting star rating from .osu file: {e}")

            beatmap_data = parse_osu_file(map_path)
            if not beatmap_data:
                logger.error("Failed to parse beatmap.")
                self.status_update.emit(f"Error parsing map: {replay_basename}")
                self.error_occurred.emit(f"Failed to parse map: {map_basename}")
                return

            hit_offsets = correlate_inputs_and_calculate_offsets(input_actions, beatmap_data, od_from_db, mods)

            results = {
                "replay_name": replay_basename,
                "map_name": map_basename, # Use map_basename here
                "mods": str(mods),
                "score": score,
                "star_rating": sr_from_db,
                "avg_offset": None,
                "ur": None,
                "matched_hits": 0,
                "tendency": "N/A",
                "hit_offsets": hit_offsets
            }

            if hit_offsets:
                try:
                    average_offset = statistics.mean(hit_offsets)
                    stdev_offset = statistics.stdev(hit_offsets) if len(hit_offsets) > 1 else 0.0
                    unstable_rate = stdev_offset * 10
                    matched_hits_count = len(hit_offsets)

                    results.update({
                        "avg_offset": average_offset,
                        "ur": unstable_rate,
                        "matched_hits": matched_hits_count
                    })

                    logger.info("--- Analysis Results ---")
                    logger.info(f" Replay: {replay_basename}")
                    logger.info(f" Map: {map_basename}") # Log map_basename
                    logger.info(f" Mods: {mods}")
                    logger.info(f" Score: {score:,}")
                    logger.info(f" Star Rating: {sr_from_db:.2f}*" if sr_from_db is not None else " Star Rating: N/A")

                    if MANUAL_REPLAY_OFFSET_MS != 0:
                        logger.info(f" Replay Time Offset: {MANUAL_REPLAY_OFFSET_MS} ms (Applied)")

                    logger.info(f" Average Hit Offset: {average_offset:+.2f} ms")
                    logger.info(f" Hit Offset StDev:   {stdev_offset:.2f} ms")
                    logger.info(f" Unstable Rate (UR): {unstable_rate:.2f}")

                    tendency = "ON TIME"
                    if average_offset < -2.0:
                        tendency = "EARLY"
                    elif average_offset > 2.0:
                        tendency = "LATE"

                    results["tendency"] = tendency
                    logger.info(f" Tendency: Hitting {tendency}")
                    print(f"Result for {replay_basename}: Average Hit Offset: {average_offset:+.2f} ms ({tendency})")
                    logger.info("------------------------")

                except statistics.StatisticsError as e:
                    logger.error(f"Statistics error: {e}")
                    results["tendency"] = "Stat Error"
                except Exception as e:
                    logger.error(f"Error calculating stats: {e}")
                    traceback.print_exc()
                    results["tendency"] = "Calc Error"
            else:
                logger.warning("--- Analysis Results ---")
                logger.warning(" Could not calculate average hit offset.")
                logger.warning("------------------------")
                results["tendency"] = "Error/No Data"

            # Emit results for main app to handle (including saving)
            self.analysis_complete.emit(results)
            self.status_update.emit("Monitoring...") # Set status back to monitoring

        except Exception as e:
            logger.error(f"Unhandled exception in AnalysisWorker: {e}")
            traceback.print_exc()
            self.error_occurred.emit(f"Unhandled error during analysis: {e}")
        finally:
            self._is_running = False

    def stop(self):
        self._is_running = False

# --- Watchdog Event Handler (Keep as QObject for signals) ---
class ReplayHandler(FileSystemEventHandler, QObject):
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
                except OSError as e: logger.error(f"Error checking size {file_path}: {e}"); return # Added return on error
                logger.info(f"Watchdog detected new replay: {os.path.basename(file_path)}")
                self.last_processed_path = file_path
                self.new_replay_signal.emit(file_path)
            else: logger.warning(f"File disappeared: {file_path}")

# --- Watchdog Monitor Thread (Keep as QThread) ---
class MonitorThread(QThread):
    new_replay_found = pyqtSignal(str)
    def __init__(self, path_to_watch):
        super().__init__()
        self.path_to_watch = path_to_watch
        self.observer = Observer()
        self.event_handler = ReplayHandler()
        self.event_handler.new_replay_signal.connect(self.new_replay_found)
        self._is_running = True

    def run(self):
        logger.info(f"Starting monitor thread: {self.path_to_watch}")
        self.observer.schedule(self.event_handler, self.path_to_watch, recursive=False)
        self.observer.start()
        try:
            while self._is_running:
                time.sleep(1)
        except Exception as e: logger.error(f"Monitor thread error: {e}"); traceback.print_exc()
        finally:
            self.observer.stop()
            self.observer.join()
            logger.info("Monitor thread stopped.")

    def stop(self):
        logger.info("Requesting monitor thread stop...")
        self._is_running = False
        self.observer.stop()

# --- Removed MainWindow Class --- #

# --- Removed Main Execution Block --- # 
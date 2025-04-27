# analyze_replay.py

import configparser
import os
import sys
import time
import statistics
import traceback # For better error printing
import logging # For better logging
import math # For abs value comparison
# --- ADDED: For file logging ---
import logging.handlers
# --- END ADDED ---


# --- Parser Imports ---
# Use osu!.db parser (requires construct, osu_db.py, osu_string.py, path_util.py etc.)
try:
    from osu_db import osu_db
except ImportError:
    print("ERROR: Failed to import 'osu_db'. Make sure osu_db.py and its dependencies (construct, etc.) are in the same directory or your Python path.")
    sys.exit(1)
# Use osrparse for replays
try:
    from osrparse import Replay, GameMode, Mod, Key
except ImportError:
    print("ERROR: Failed to import 'osrparse'. Please install it using: pip install osrparse")
    sys.exit(1)
# Use python-osu-parser for .osu files (requires beatmapparser.py, slidercalc.py, curve.py)
try:
    # Ensure curve.py has the .length fix applied (len())
    from beatmapparser import BeatmapParser
except ImportError:
    print("ERROR: Failed to import 'beatmapparser'. Make sure beatmapparser.py and its dependencies (slidercalc.py, curve.py) are in the same directory or your Python path.")
    sys.exit(1)
# --- End Parser Imports ---

# Watchdog for monitoring
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    print("ERROR: Failed to import 'watchdog'. Please install it using: pip install watchdog")
    sys.exit(1)

# --- Configuration ---
CONFIG_FILE = 'config.ini'
# --- ADDED: Log file name ---
DEBUG_LOG_FILE = 'analyzer_debug.log'

# --- Global Variables (Set by load_config and main block) ---
REPLAYS_FOLDER = ""
SONGS_FOLDER = ""
OSU_DB_PATH = ""
OSU_DB = None # Will hold the loaded osu!.db data
MANUAL_REPLAY_OFFSET_MS = 0

# --- Logging Setup ---
# Basic config will be overridden/added to by load_config
# Set initial level high to avoid logging before config is read
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
# Get the root logger
logger = logging.getLogger()

# --- Configuration Loading ---
def load_config():
    """Loads and validates paths and settings from the configuration file."""
    global MANUAL_REPLAY_OFFSET_MS # Allow modification of global variable
    config = configparser.ConfigParser()
    replays_path_str = None
    songs_path_str = None
    osu_db_path_str = None
    manual_offset_str = '0' # Default value as string
    log_level_str = 'INFO' # Default

    if not os.path.exists(CONFIG_FILE):
        # Use logger now that it's defined
        logger.warning(f"Configuration file not found: {CONFIG_FILE}")
        # Create a default config if it doesn't exist
        print(f"'{CONFIG_FILE}' not found. Creating a default config file.")
        print("Please edit it with your actual osu! paths and desired settings.")
        # Define default Paths
        config['Paths'] = {
            'OsuReplaysFolder': r'C:\Path\To\Your\osu!\Replays', # Example
            'OsuSongsFolder': r'C:\Path\To\Your\osu!\Songs',     # Example
            'OsuDbPath': r'C:\Path\To\Your\osu!\osu!.db'         # Example
        }
        # --- Add default Settings section ---
        config['Settings'] = {
            'LogLevel': 'INFO', # Options: DEBUG, INFO, WARNING, ERROR
            'ReplayTimeOffsetMs': '-8' # Manual offset in milliseconds (e.g., -10 to shift replay times earlier)
        }
        # --- END Add default Settings section ---
        try:
            with open(CONFIG_FILE, 'w') as configfile:
                config.write(configfile)
            logger.info(f"Default '{CONFIG_FILE}' created. Please edit it and restart.")
        except IOError as e:
             logger.error(f"Could not write default config file: {e}")
        # Exit after creating default config file
        sys.exit(f"Exiting. Please edit '{CONFIG_FILE}' and restart.")

    # If config file exists, read it
    try:
        config.read(CONFIG_FILE)
    except configparser.Error as e:
        logger.error(f"Error reading configuration file: {e}")
        raise ValueError(f"Error reading configuration file: {e}") from e

    # Read Paths (Required section)
    if 'Paths' not in config:
        logger.error("Missing [Paths] section in config.ini")
        raise ValueError("Missing [Paths] section in config.ini")
    try:
        replays_path_str = config['Paths']['OsuReplaysFolder']
        songs_path_str = config['Paths']['OsuSongsFolder']
        osu_db_path_str = config['Paths']['OsuDbPath']
    except KeyError as e:
        logger.error(f"Missing key {e} in '{CONFIG_FILE}' under [Paths].")
        sys.exit(f"Please check your config file for the key: {e}")

    # Read Settings (Optional section, use defaults if missing)
    if 'Settings' in config:
        log_level_str = config['Settings'].get('LogLevel', 'INFO').upper()
        manual_offset_str = config['Settings'].get('ReplayTimeOffsetMs', '0')
    else:
        logger.warning("Missing [Settings] section in config.ini. Using default settings (LogLevel=INFO, ReplayTimeOffsetMs=0).")
        # Ensure defaults are used if section is missing
        log_level_str = 'INFO'
        manual_offset_str = '0'

    # Validate paths
    if not os.path.isdir(replays_path_str):
        raise NotADirectoryError(f"Configured Replays folder not found or not a directory: {replays_path_str}")
    if not os.path.isdir(songs_path_str):
        raise NotADirectoryError(f"Configured Songs folder not found or not a directory: {songs_path_str}")
    if not os.path.isfile(osu_db_path_str):
        raise FileNotFoundError(f"Configured osu!.db file not found: {osu_db_path_str}")

    # --- MODIFIED: Setup Logging Based on Config ---
    log_levels = {'DEBUG': logging.DEBUG, 'INFO': logging.INFO, 'WARNING': logging.WARNING, 'ERROR': logging.ERROR}
    log_level = logging.INFO # Default

    if log_level_str in log_levels:
        log_level = log_levels[log_level_str]
        logger.setLevel(log_level) # Set root logger level
        logging.info(f"Logging level set to {log_level_str} from config.") # Log after setting level
    else:
        logger.warning(f"Invalid LogLevel '{log_level_str}' in config. Using default INFO.")
        logger.setLevel(logging.INFO)

    # Clear existing handlers if any were added by basicConfig
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Create formatter
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    # Create console handler and set its level (usually INFO or higher)
    console_handler = logging.StreamHandler(sys.stdout)
    # Show INFO and higher on console, unless DEBUG is specifically set
    console_log_level = logging.INFO if log_level > logging.DEBUG else logging.DEBUG
    console_handler.setLevel(console_log_level)
    console_handler.setFormatter(log_formatter)
    logger.addHandler(console_handler)

    # If DEBUG level is set, add a file handler
    if log_level == logging.DEBUG:
        try:
            # Use 'w' mode to overwrite the log file each time the script starts
            file_handler = logging.FileHandler(DEBUG_LOG_FILE, mode='w', encoding='utf-8')
            file_handler.setLevel(logging.DEBUG) # Log everything to the file
            file_handler.setFormatter(log_formatter)
            logger.addHandler(file_handler)
            logger.info(f"DEBUG level enabled. Logging detailed output to '{DEBUG_LOG_FILE}'")
        except Exception as e:
            logger.error(f"Failed to create debug log file handler for '{DEBUG_LOG_FILE}': {e}")
    # --- END MODIFIED Logging Setup ---


    # Parse and set Manual Offset
    try:
        MANUAL_REPLAY_OFFSET_MS = int(manual_offset_str)
        logger.info(f"Manual Replay Time Offset set to: {MANUAL_REPLAY_OFFSET_MS} ms")
    except ValueError:
        logger.warning(f"Invalid ReplayTimeOffsetMs '{manual_offset_str}' in config. Using 0 ms.")
        MANUAL_REPLAY_OFFSET_MS = 0

    logger.info("Configuration paths validated.")
    return replays_path_str, songs_path_str, osu_db_path_str

# --- Load osu!.db ---
def load_osu_database(db_path):
    """Loads the osu!.db file into memory using the construct-based parser."""
    logger.info(f"Loading osu!.db from: {db_path}... This might take a moment.")
    start_time = time.time()
    try:
        osu_db_data = osu_db.parse_file(db_path)
        logger.info(f"osu!.db loaded successfully in {time.time() - start_time:.2f} seconds.")
        return osu_db_data
    except Exception as e:
        logger.critical(f"FATAL: Failed to load or parse osu!.db: {e}")
        traceback.print_exc()
        sys.exit("Exiting due to osu!.db loading error.")

# --- Beatmap Lookup ---
def lookup_beatmap_in_db(beatmap_hash):
    """Looks up beatmap path information in the loaded osu!.db by hash."""
    global OSU_DB, SONGS_FOLDER # Need SONGS_FOLDER here
    if OSU_DB is None:
        logger.error("osu!.db is not loaded. Cannot perform lookup.")
        return None, None

    logger.info(f"Searching osu!.db for beatmap with hash: {beatmap_hash}...")
    found_entry = None
    try:
        if not hasattr(OSU_DB, 'beatmaps'):
            logger.error("Loaded osu!.db object has no 'beatmaps' attribute.")
            return None, None

        for beatmap_entry in OSU_DB.beatmaps:
            try:
                entry_hash = beatmap_entry.md5_hash
                if entry_hash and entry_hash.lower() == beatmap_hash.lower():
                    found_entry = beatmap_entry
                    break
            except AttributeError:
                logger.debug("Encountered beatmap entry missing 'md5_hash' attribute, skipping.")
                continue

        if found_entry:
            folder_name, osu_filename, od = None, None, None
            try:
                folder_name = found_entry.folder_name
                osu_filename = found_entry.osu_file_name
                od = found_entry.overall_difficulty
                logger.debug(f"Found potential entry: Folder='{folder_name}', File='{osu_filename}', OD='{od}'")

                if folder_name and isinstance(folder_name, str) and folder_name.strip() and \
                   osu_filename and isinstance(osu_filename, str) and osu_filename.strip():
                    logger.info(f"Found beatmap entry in osu!.db: {folder_name}\\{osu_filename}")
                    full_map_path = os.path.join(SONGS_FOLDER, folder_name, osu_filename) # Use global SONGS_FOLDER
                    logger.info(f"  Constructed Path: {full_map_path}")
                    logger.info(f"  Overall Difficulty (OD) from DB: {od}")
                    if os.path.isfile(full_map_path):
                        return full_map_path, float(od)
                    else:
                        logger.warning(f"Found entry in osu!.db but file not found at: {full_map_path}")
                        return None, None
                else:
                    logger.warning(f"Found hash {beatmap_hash} but DB entry missing valid folder_name ('{folder_name}') or osu_file_name ('{osu_filename}').")
                    return None, None
            except AttributeError as ae:
                 logger.warning(f"Found hash {beatmap_hash} but entry missing critical attribute ({ae}).")
                 return None, None
        else:
            logger.warning(f"Beatmap hash {beatmap_hash} not found in osu!.db.")
            return None, None
    except Exception as e:
        logger.error(f"Error looking up beatmap hash {beatmap_hash} in osu!.db: {e}")
        traceback.print_exc()
        return None, None

# --- .osu File Parsing (Using python-osu-parser) ---
def parse_osu_file(map_path):
    """Parses the .osu file using BeatmapParser."""
    logger.info(f"Parsing beatmap: {os.path.basename(map_path)} using BeatmapParser...")
    try:
        parser = BeatmapParser()
        with open(map_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f: parser.read_line(line)
        parser.build_beatmap()
        beatmap_data = parser.beatmap
        logger.info("Beatmap parsed successfully with BeatmapParser.")
        return beatmap_data
    except Exception as e:
        logger.error(f"Error parsing .osu file {os.path.basename(map_path)} with BeatmapParser:")
        traceback.print_exc()
        return None

# --- Replay Parsing (MODIFIED Input Detection) ---
def parse_replay_file(replay_path):
    """Parses an .osr file and extracts relevant data."""
    try:
        logger.info(f"Parsing replay: {os.path.basename(replay_path)}...")
        replay = Replay.from_path(replay_path)
        if replay.mode != GameMode.STD:
            logger.warning(f"Skipping non-standard replay: {replay.mode}")
            return None

        beatmap_hash = replay.beatmap_hash
        mods_enum = replay.mods
        replay_events = replay.replay_data
        logger.info(f"  Beatmap Hash: {beatmap_hash}")
        logger.info(f"  Mods: {mods_enum}")

        input_actions = []
        current_time = 0
        # --- REMOVED: last_key_state is no longer needed for this simple detection ---
        # last_key_state = 0
        relevant_keys_mask = Key.M1 | Key.M2 | Key.K1 | Key.K2

        for idx, event in enumerate(replay_events): # Added index for logging
            if event.time_delta < 0 and current_time == 0:
                logger.debug(f"Skipping initial negative time_delta event: {event.time_delta}")
                continue

            # Log time_delta
            logger.debug(f"  Replay Frame {idx}: time_delta={event.time_delta}, current_keys={event.keys}")

            current_time += event.time_delta
            current_press_state = event.keys & relevant_keys_mask

            # --- MODIFIED: Record ANY frame where a relevant key is down ---
            if current_press_state > 0:
                adjusted_input_time = current_time + MANUAL_REPLAY_OFFSET_MS
                input_actions.append({'time': adjusted_input_time, 'keys': current_press_state, 'original_time': current_time})
                # Log the detected input with more context
                logger.debug(f"    -> Input State Recorded: Frame={idx}, OrigTime={current_time}, AdjTime={adjusted_input_time}, Offset={MANUAL_REPLAY_OFFSET_MS}, KeysDown={current_press_state}")
            # --- END MODIFICATION ---

            # --- REMOVED: pressed_now and related logic ---
            # pressed_now = current_press_state & ~last_key_state
            # if pressed_now > 0: ...
            # elif logger.isEnabledFor(logging.DEBUG): ...
            # last_key_state = current_press_state

        logger.info(f"  Found {len(input_actions)} input state frames (key/mouse down).") # Adjusted log message
        if not input_actions:
            logger.warning("No input actions found in replay data.")
            return None

        # --- Optional: Add filtering for duplicate consecutive timestamps if needed ---
        # This might be necessary if holding a key generates many frames at the exact same time
        # filtered_actions = []
        # last_time = -1
        # for action in input_actions:
        #     if action['time'] != last_time:
        #         filtered_actions.append(action)
        #         last_time = action['time']
        # input_actions = filtered_actions
        # logger.info(f"  Filtered down to {len(input_actions)} unique timestamp input actions.")
        # --- End Optional Filtering ---


        return {'beatmap_hash': beatmap_hash, 'mods': mods_enum, 'input_actions': input_actions}
    except Exception as e:
        logger.error(f"Error parsing replay file {os.path.basename(replay_path)}:")
        traceback.print_exc()
        return None

# --- Hit Window Calculation ---
def get_hit_window_ms(od, window_type='50', mods=Mod.NoMod):
    """Calculates the hit window in milliseconds based on OD and mods."""
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

# --- Correlation Logic (REVISED v2 - Correct Search Index Handling) ---
def correlate_inputs_and_calculate_offsets(input_actions, beatmap_data, beatmap_od, mods):
    """Correlates inputs to hit objects and calculates hit offsets."""
    if not beatmap_data or beatmap_od is None or not input_actions: return []
    hit_offsets, used_input_indices = [], set()
    last_successful_input_index = -1 # Index of the input used for the last successful match

    rate = 1.0
    if Mod.DoubleTime in mods or Mod.Nightcore in mods: rate = 1.5
    elif Mod.HalfTime in mods: rate = 0.75
    try:
        od = beatmap_od
        miss_window_ms = get_hit_window_ms(od, '50', mods)
        logger.info(f"Using miss window (OD50): ±{miss_window_ms:.2f} ms (OD={od}, Mods={mods})")
    except Exception as e:
        logger.error(f"Error calculating miss window: {e}. Using default 200ms.")
        miss_window_ms = 200
    try:
        beatmap_objects = beatmap_data.get('hitObjects', [])
        if not beatmap_objects: logger.warning("Beatmap data contains no 'hitObjects'."); return []
        logger.info(f"Correlating {len(input_actions)} inputs with {len(beatmap_objects)} beatmap objects...")
        objects_correlated = 0
        skipped_object_count = 0 # Count skipped objects
        for obj_index, obj in enumerate(beatmap_objects):
            obj_type = obj.get('object_name')
            # Check and Log skipped types
            if obj_type not in ['circle', 'slider']:
                logger.debug(f"  -> Skipping HO {obj_index} (Type: {obj_type}) @ Time {obj.get('startTime', 'N/A')}")
                skipped_object_count += 1
                continue
            # END Check and Log
            expected_hit_time_ms = obj.get('startTime')
            if expected_hit_time_ms is None:
                logger.warning(f"Skipping HO {obj_index} due to missing 'startTime'")
                continue

            adjusted_expected_hit_time = expected_hit_time_ms / rate
            window_start = adjusted_expected_hit_time - miss_window_ms
            window_end = adjusted_expected_hit_time + miss_window_ms
            best_match_input_index, min_abs_offset = -1, float('inf')

            # Determine where to start searching
            current_search_start_index = last_successful_input_index + 1

            # Log search details for this object
            logger.debug(f" --> Correlating HO {obj_index} (Type:{obj_type}, AdjTime:{adjusted_expected_hit_time:.0f}ms), Window=[{window_start:.0f}ms, {window_end:.0f}ms], Searching inputs from index {current_search_start_index}...")

            # Search for closest input
            found_potential_match_in_window = False
            # Iterate from current_search_start_index
            for i in range(current_search_start_index, len(input_actions)):
                action = input_actions[i]; input_time_ms = action['time']

                logger.debug(f"    -> Checking Input {i} @ {input_time_ms:.0f}ms (Used: {i in used_input_indices})")

                # Stop searching if input is too late for the window
                if input_time_ms > window_end:
                    logger.debug(f"       Input {i} is too late (After {window_end:.0f}ms). Stopping search for HO {obj_index}.")
                    break # Stop searching inputs for THIS hit object

                # Check if within window and unused
                if window_start <= input_time_ms <= window_end:
                    found_potential_match_in_window = True
                    # Check used_input_indices here
                    if i not in used_input_indices:
                        current_offset = input_time_ms - adjusted_expected_hit_time
                        current_abs_offset = abs(current_offset)
                        # Update if this is the closest hit found so far
                        if current_abs_offset < min_abs_offset:
                            min_abs_offset = current_abs_offset; best_match_input_index = i
                            logger.debug(f"       Potential Best Match Found! Input {i} (Offset:{current_offset:+.2f}ms, Abs:{current_abs_offset:.2f}ms)")
                    else:
                        logger.debug(f"       Input {i} is within window but already used.")


            # Process best match if found
            if best_match_input_index != -1:
                matched_input_time_ms = input_actions[best_match_input_index]['time']
                offset = matched_input_time_ms - adjusted_expected_hit_time
                # Sanity check offset is within window
                if abs(offset) <= miss_window_ms:
                    hit_offsets.append(offset); used_input_indices.add(best_match_input_index)
                    objects_correlated += 1
                    # Update last_successful_input_index
                    last_successful_input_index = best_match_input_index
                    logger.debug(f"  --> SUCCESS: Matched HO {obj_index} (T={adjusted_expected_hit_time:.0f}) with Input {best_match_input_index} (T={matched_input_time_ms:.0f}). Offset: {offset:+.2f}. Last used input index: {last_successful_input_index}")
                else:
                    logger.warning(f"  --> REJECTED MATCH (Logic Error?): HO {obj_index}: Offset {offset:+.2f} outside window ±{miss_window_ms:.2f}ms.")
            else:
                # Log if no input was found for this object
                if found_potential_match_in_window:
                     logger.debug(f"  --> MISS: No *unused* input found for HO {obj_index} (T={adjusted_expected_hit_time:.0f}) within window.")
                else:
                     logger.debug(f"  --> MISS: No input found *at all* for HO {obj_index} (T={adjusted_expected_hit_time:.0f}) within window [{window_start:.0f}ms - {window_end:.0f}ms]")
                # Do NOT advance last_successful_input_index on a miss


        # Log final correlation summary including skipped objects
        logger.info(f"Correlation complete. Matched {objects_correlated} hits. Skipped {skipped_object_count} non-circle/slider objects. Found {len(hit_offsets)} valid hit offsets.")
        if not hit_offsets: logger.warning("No hits correlated.")
    except Exception as e:
        logger.error(f"Correlation error: {e}"); traceback.print_exc(); return []
    return hit_offsets

# --- Main Analysis Function ---
def process_replay(replay_path):
    """Processes a single replay file."""
    logger.info(f"--- Starting Analysis for {os.path.basename(replay_path)} ---")
    replay_data = parse_replay_file(replay_path)
    if not replay_data: logger.error("Failed to parse replay."); return
    beatmap_hash, mods, input_actions = replay_data['beatmap_hash'], replay_data['mods'], replay_data['input_actions']
    map_path, od_from_db = lookup_beatmap_in_db(beatmap_hash)
    if not map_path: logger.error(f"Could not find map path for hash {beatmap_hash}."); return
    if od_from_db is None: logger.warning(f"Could not determine OD for hash {beatmap_hash}."); return
    beatmap_data = parse_osu_file(map_path)
    if not beatmap_data: logger.error("Failed to parse beatmap."); return
    hit_offsets = correlate_inputs_and_calculate_offsets(input_actions, beatmap_data, od_from_db, mods)
    if hit_offsets:
        try:
            average_offset = statistics.mean(hit_offsets)
            stdev_offset = statistics.stdev(hit_offsets) if len(hit_offsets) > 1 else 0.0
            unstable_rate = stdev_offset * 10
            logger.info("--- Analysis Results ---")
            logger.info(f" Replay: {os.path.basename(replay_path)}")
            logger.info(f" Map: {os.path.basename(map_path)}")
            logger.info(f" Mods: {mods}")
            if MANUAL_REPLAY_OFFSET_MS != 0: logger.info(f" Replay Time Offset: {MANUAL_REPLAY_OFFSET_MS} ms (Applied)")
            logger.info(f" Average Hit Offset: {average_offset:+.2f} ms")
            logger.info(f" Hit Offset StDev:   {stdev_offset:.2f} ms")
            logger.info(f" Unstable Rate (UR): {unstable_rate:.2f}")
            tendency = "ON TIME";
            if average_offset < -2.0: tendency = "EARLY"
            elif average_offset > 2.0: tendency = "LATE"
            logger.info(f" Tendency: Hitting {tendency}")
            print(f"Result for {os.path.basename(replay_path)}: Average Hit Offset: {average_offset:+.2f} ms ({tendency})")
            logger.info("------------------------")
        except statistics.StatisticsError as e: logger.error(f"Statistics error (not enough data?): {e}")
        except Exception as e: logger.error(f"Error calculating stats: {e}"); traceback.print_exc()
    else:
       logger.warning("--- Analysis Results ---")
       logger.warning(" Could not calculate average hit offset (correlation failed or no offsets found).")
       logger.warning("------------------------")

# --- Watchdog Event Handler ---
class ReplayHandler(FileSystemEventHandler):
    """Handles file system events for new replay files."""
    def __init__(self):
        self.last_processed_path = None; self.last_processed_time = 0; self.debounce_period = 2.0
    def on_created(self, event):
        current_time = time.time()
        if not event.is_directory and event.src_path.lower().endswith(".osr"):
            file_path = event.src_path; logger.debug(f"Event detected: {file_path}")
            # Debounce check
            if file_path == self.last_processed_path and current_time - self.last_processed_time < self.debounce_period:
                logger.debug(f"Debouncing event for {os.path.basename(file_path)}"); return
            # Wait briefly for file write to complete
            time.sleep(0.5)
            if os.path.exists(file_path):
                # Optional: Check file size stability
                try:
                    s1=os.path.getsize(file_path); time.sleep(0.2); s2=os.path.getsize(file_path)
                    if s1!=s2: logger.warning(f"Size changing {os.path.basename(file_path)}, delaying."); time.sleep(0.5)
                except OSError as e: logger.error(f"Error checking size {file_path}: {e}")
                # Process the replay
                logger.info(f"Processing new replay: {os.path.basename(file_path)}")
                self.last_processed_path = file_path; self.last_processed_time = current_time
                try:
                    process_replay(file_path)
                except Exception as e:
                    logger.error(f"--- ERROR processing {os.path.basename(file_path)} ---"); traceback.print_exc(); logger.error("---")
                finally:
                    # Reprint monitoring message after processing attempt
                     if REPLAYS_FOLDER:
                         print(f"\nMonitoring for new replays in: {REPLAYS_FOLDER.replace(os.sep, '/')}\nPress Ctrl+C to stop.")
                     else: # Should not happen if load_config worked
                         print("\nMonitoring...\nPress Ctrl+C to stop.")
            else:
                logger.warning(f"File disappeared before processing could start: {file_path}")

# --- Main Execution ---
if __name__ == "__main__":
    # Use logger for initial messages too
    logger.info("Starting osu! Average Hit Offset Analyzer")
    logger.info("==========================================")
    try:
        # Load config and paths, set log level and offset
        REPLAYS_FOLDER, SONGS_FOLDER, OSU_DB_PATH = load_config()
        # Load osu!.db once
        OSU_DB = load_osu_database(OSU_DB_PATH)
    except (NotADirectoryError, FileNotFoundError, configparser.Error, ValueError, ImportError, Exception) as e:
        logger.critical(f"Initialization failed: {e}"); traceback.print_exc()
        if isinstance(e, ImportError):
             print("\n--- Import Error ---")
             print("Please ensure required libraries (osrparse, watchdog, construct) and script dependencies (osu_db.py, beatmapparser.py, etc.) are installed and accessible.")
             print("See README or script comments for details.")
             print("--------------------\n")
        # input("Press Enter to exit...") # Uncomment for debugging standalone executable
        sys.exit(1) # Exit if initialization fails

    # Log final paths after successful loading
    logger.info(f"Replays Folder: {REPLAYS_FOLDER.replace(os.sep, '/')}")
    logger.info(f"Songs Folder: {SONGS_FOLDER.replace(os.sep, '/')}")
    logger.info(f"osu!.db Path: {OSU_DB_PATH.replace(os.sep, '/')}")

    # Setup and start watchdog
    event_handler = ReplayHandler(); observer = Observer()
    observer.schedule(event_handler, REPLAYS_FOLDER, recursive=False)
    logger.info(f"\nMonitoring for new replays in: {REPLAYS_FOLDER.replace(os.sep, '/')}")
    print("Press Ctrl+C to stop.") # Keep print for user visibility
    observer.start()

    # Keep running until interrupted
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        logger.info("\nStopping monitoring..."); observer.stop()
    except Exception as e: # Catch other potential errors during monitoring loop
        logger.error(f"\nMonitoring error:"); traceback.print_exc(); observer.stop()

    observer.join(); # Wait for observer thread to finish
    logger.info("Analyzer stopped.")

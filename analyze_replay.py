# analyze_replay.py

import configparser
import os
import sys
import time
import statistics
import traceback # For better error printing
import logging # For better logging
import math # For abs value comparison

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

# --- Global Variables (Set by load_config and main block) ---
REPLAYS_FOLDER = ""
SONGS_FOLDER = ""
OSU_DB_PATH = ""
OSU_DB = None # Will hold the loaded osu!.db data
# --- NEW: Manual Offset Setting ---
MANUAL_REPLAY_OFFSET_MS = 0

# --- Logging Setup ---
# Change level to logging.DEBUG to see detailed correlation logs
# LOG_LEVEL = logging.DEBUG
LOG_LEVEL = logging.INFO # Default to INFO
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# --- Configuration Loading ---
def load_config():
    """Loads and validates paths and settings from the configuration file."""
    global MANUAL_REPLAY_OFFSET_MS # Allow modification of global variable
    config = configparser.ConfigParser()
    replays_path_str = None
    songs_path_str = None
    osu_db_path_str = None
    manual_offset_str = '0' # Default value as string

    if not os.path.exists(CONFIG_FILE):
        logging.error(f"Configuration file not found: {CONFIG_FILE}")
        # Create a default config if it doesn't exist
        print(f"'{CONFIG_FILE}' not found. Creating a default config file.")
        print("Please edit it with your actual osu! paths and desired settings.")
        config['Paths'] = {
            'OsuReplaysFolder': r'C:\Path\To\Your\osu!\Replays', # Example
            'OsuSongsFolder': r'C:\Path\To\Your\osu!\Songs',     # Example
            'OsuDbPath': r'C:\Path\To\Your\osu!\osu!.db'         # Example
        }
        # --- NEW: Add Settings section ---
        config['Settings'] = {
            'LogLevel': 'INFO', # Options: DEBUG, INFO, WARNING, ERROR
            'ReplayTimeOffsetMs': '-10' # Manual offset in milliseconds (e.g., -10 to shift replay times earlier)
        }
        try:
            with open(CONFIG_FILE, 'w') as configfile:
                config.write(configfile)
        except IOError as e:
             logging.error(f"Could not write default config file: {e}")
        sys.exit(f"Exiting. Please edit '{CONFIG_FILE}' and restart.")

    try:
        config.read(CONFIG_FILE)
    except configparser.Error as e:
        logging.error(f"Error reading configuration file: {e}")
        raise ValueError(f"Error reading configuration file: {e}") from e

    # Read Paths
    if 'Paths' not in config:
        logging.error("Missing [Paths] section in config.ini")
        raise ValueError("Missing [Paths] section in config.ini")
    try:
        replays_path_str = config['Paths']['OsuReplaysFolder']
        songs_path_str = config['Paths']['OsuSongsFolder']
        osu_db_path_str = config['Paths']['OsuDbPath']
    except KeyError as e:
        logging.error(f"Missing key {e} in '{CONFIG_FILE}' under [Paths].")
        sys.exit(f"Please check your config file for the key: {e}")

    # Read Settings (Optional section)
    log_level_str = 'INFO' # Default
    if 'Settings' in config:
        log_level_str = config['Settings'].get('LogLevel', 'INFO').upper()
        manual_offset_str = config['Settings'].get('ReplayTimeOffsetMs', '0')
    else:
        logging.warning("Missing [Settings] section in config.ini. Using default settings.")

    # Validate paths
    if not os.path.isdir(replays_path_str):
        raise NotADirectoryError(f"Configured Replays folder not found or not a directory: {replays_path_str}")
    if not os.path.isdir(songs_path_str):
        raise NotADirectoryError(f"Configured Songs folder not found or not a directory: {songs_path_str}")
    if not os.path.isfile(osu_db_path_str):
        raise FileNotFoundError(f"Configured osu!.db file not found: {osu_db_path_str}")

    # Set Log Level based on config
    log_levels = {'DEBUG': logging.DEBUG, 'INFO': logging.INFO, 'WARNING': logging.WARNING, 'ERROR': logging.ERROR}
    if log_level_str in log_levels:
        logging.getLogger().setLevel(log_levels[log_level_str])
        logging.info(f"Logging level set to {log_level_str} from config.")
    else:
        logging.warning(f"Invalid LogLevel '{log_level_str}' in config. Using default INFO.")
        logging.getLogger().setLevel(logging.INFO)

    # Parse and set Manual Offset
    try:
        MANUAL_REPLAY_OFFSET_MS = int(manual_offset_str)
        logging.info(f"Manual Replay Time Offset set to: {MANUAL_REPLAY_OFFSET_MS} ms")
    except ValueError:
        logging.warning(f"Invalid ReplayTimeOffsetMs '{manual_offset_str}' in config. Using 0 ms.")
        MANUAL_REPLAY_OFFSET_MS = 0

    logging.info("Configuration paths validated.")
    return replays_path_str, songs_path_str, osu_db_path_str

# --- Load osu!.db ---
def load_osu_database(db_path):
    """Loads the osu!.db file into memory using the construct-based parser."""
    logging.info(f"Loading osu!.db from: {db_path}... This might take a moment.")
    start_time = time.time()
    try:
        osu_db_data = osu_db.parse_file(db_path)
        logging.info(f"osu!.db loaded successfully in {time.time() - start_time:.2f} seconds.")
        return osu_db_data
    except Exception as e:
        logging.critical(f"FATAL: Failed to load or parse osu!.db: {e}")
        traceback.print_exc()
        sys.exit("Exiting due to osu!.db loading error.")

# --- Beatmap Lookup ---
def lookup_beatmap_in_db(beatmap_hash):
    """Looks up beatmap path information in the loaded osu!.db by hash."""
    global OSU_DB
    if OSU_DB is None:
        logging.error("osu!.db is not loaded. Cannot perform lookup.")
        return None, None # Return None for both path and OD

    logging.info(f"Searching osu!.db for beatmap with hash: {beatmap_hash}...")
    found_entry = None
    try:
        if not hasattr(OSU_DB, 'beatmaps'):
            logging.error("Loaded osu!.db object has no 'beatmaps' attribute.")
            return None, None

        # Iterate through beatmaps to find the hash
        for beatmap_entry in OSU_DB.beatmaps:
            try:
                entry_hash = beatmap_entry.md5_hash
                # Compare hashes case-insensitively
                if entry_hash and entry_hash.lower() == beatmap_hash.lower():
                    found_entry = beatmap_entry
                    break # Stop searching once found
            except AttributeError:
                logging.debug("Encountered beatmap entry missing 'md5_hash' attribute, skipping.")
                continue # Skip potentially malformed entries

        # Process the found entry (if any)
        if found_entry:
            folder_name = None
            osu_filename = None
            od = None
            try:
                # Use direct attribute access based on osu_db.py struct definition
                folder_name = found_entry.folder_name
                osu_filename = found_entry.osu_file_name
                od = found_entry.overall_difficulty # Confirmed attribute name

                logging.debug(f"Found potential entry: Folder='{folder_name}', File='{osu_filename}', OD='{od}'")

                # Check if the essential path components are valid non-empty strings
                if folder_name and isinstance(folder_name, str) and folder_name.strip() and \
                   osu_filename and isinstance(osu_filename, str) and osu_filename.strip():

                    logging.info(f"Found beatmap entry in osu!.db: {folder_name}\\{osu_filename}")
                    # Use global SONGS_FOLDER correctly
                    full_map_path = os.path.join(SONGS_FOLDER, folder_name, osu_filename)
                    logging.info(f"  Constructed Path: {full_map_path}")
                    logging.info(f"  Overall Difficulty (OD) from DB: {od}")

                    if os.path.isfile(full_map_path):
                        return full_map_path, float(od) # Return path and OD as float
                    else:
                        logging.warning(f"Found entry in osu!.db but file not found at: {full_map_path}")
                        return None, None # File missing on disk
                else:
                    logging.warning(f"Found hash {beatmap_hash} but DB entry missing valid folder_name ('{folder_name}') or osu_file_name ('{osu_filename}'). This map might be corrupted or partially deleted in osu!.")
                    return None, None # Incomplete entry in DB

            except AttributeError as ae:
                 logging.warning(f"Found hash {beatmap_hash} but entry missing critical attribute ({ae}). Entry might be incomplete.")
                 return None, None

        else:
            # Hash was not found after checking all beatmaps
            logging.warning(f"Beatmap hash {beatmap_hash} not found in osu!.db.")
            return None, None # Hash not found

    except Exception as e:
        logging.error(f"Error looking up beatmap hash {beatmap_hash} in osu!.db: {e}")
        traceback.print_exc()
        return None, None

# --- .osu File Parsing (Using python-osu-parser) ---
def parse_osu_file(map_path):
    """Parses the .osu file using BeatmapParser."""
    logging.info(f"Parsing beatmap: {os.path.basename(map_path)} using BeatmapParser...")
    try:
        parser = BeatmapParser() # Instantiate
        # Read file line by line (ensure correct encoding, utf-8 is common for .osu)
        with open(map_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                parser.read_line(line)
        # Process the read lines
        parser.build_beatmap()
        beatmap_data = parser.beatmap # Get the resulting dictionary
        logging.info("Beatmap parsed successfully with BeatmapParser.")
        return beatmap_data # Return the dictionary
    except Exception as e:
        logging.error(f"Error parsing .osu file {os.path.basename(map_path)} with BeatmapParser:")
        traceback.print_exc()
        return None

# --- Replay Parsing ---
def parse_replay_file(replay_path):
    """Parses an .osr file and extracts relevant data."""
    try:
        logging.info(f"Parsing replay: {os.path.basename(replay_path)}...")
        replay = Replay.from_path(replay_path)

        # Check if the game mode is Standard (confirmed GameMode.OSU)
        if replay.mode != GameMode.STD:
            logging.warning(f"Skipping non-standard replay: {replay.mode}")
            return None

        beatmap_hash = replay.beatmap_hash
        mods_enum = replay.mods # Keep as osrparse Mod enum
        replay_events = replay.replay_data

        logging.info(f"  Beatmap Hash: {beatmap_hash}")
        logging.info(f"  Mods: {mods_enum}")

        input_actions = [] # Correctly initialized as a list
        current_time = 0
        last_key_state = 0
        # Define the keys we care about for hit timing
        relevant_keys_mask = Key.M1 | Key.M2 | Key.K1 | Key.K2

        for event in replay_events:
            # Skip potential initial junk frames more reliably
            if event.time_delta < 0 and current_time == 0:
                logging.debug(f"Skipping initial negative time_delta event: {event.time_delta}")
                continue

            current_time += event.time_delta
            current_press_state = event.keys & relevant_keys_mask
            # Detect only the keys that were *just* pressed (transition from 0 to 1)
            pressed_now = current_press_state & ~last_key_state

            # Only record the timestamp when a relevant key is *pressed down*
            if pressed_now > 0:
                # --- Apply manual offset HERE ---
                adjusted_input_time = current_time + MANUAL_REPLAY_OFFSET_MS
                input_actions.append({'time': adjusted_input_time, 'keys': pressed_now, 'original_time': current_time})
                logging.debug(f"Input detected: OrigTime={current_time}, AdjTime={adjusted_input_time}, Offset={MANUAL_REPLAY_OFFSET_MS}, Keys={pressed_now}")
                # --- End Offset Application ---

            last_key_state = current_press_state # Update the state for the next iteration

        logging.info(f"  Found {len(input_actions)} input actions (key/mouse presses).")

        if not input_actions:
            logging.warning("No input actions found in replay data.")
            # Return None if no inputs, as correlation is impossible
            return None

        return {
            'beatmap_hash': beatmap_hash,
            'mods': mods_enum, # Return the osrparse Mod enum value
            'input_actions': input_actions
        }

    except Exception as e:
        logging.error(f"Error parsing replay file {os.path.basename(replay_path)}:")
        traceback.print_exc()
        return None

# --- Hit Window Calculation ---
def get_hit_window_ms(od, window_type='50', mods=Mod.NoMod): # Default to osrparse.Mod.NoMod
    """Calculates the hit window in milliseconds based on OD and mods."""
    base_ms = {'300': 79.5, '100': 139.5, '50': 199.5}
    ms_reduction_per_od = {'300': 6, '100': 8, '50': 10}

    if window_type not in base_ms:
        logging.error(f"Invalid window_type '{window_type}' requested.")
        raise ValueError("Invalid window_type. Use '300', '100', or '50'.")

    try: od_float = float(od)
    except (ValueError, TypeError):
        logging.error(f"Invalid OD value for hit window calculation: {od}. Using OD 5 as fallback.")
        od_float = 5.0

    window = base_ms[window_type] - ms_reduction_per_od[window_type] * od_float
    rate = 1.0
    if Mod.DoubleTime in mods or Mod.Nightcore in mods: rate = 1.5
    elif Mod.HalfTime in mods: rate = 0.75
    adjusted_window = window / rate
    return max(0, adjusted_window)

# --- Correlation Logic (Find Closest Hit) ---
def correlate_inputs_and_calculate_offsets(input_actions, beatmap_data, beatmap_od, mods):
    """
    Correlates inputs to hit objects and calculates hit offsets.
    Finds the input with the *minimum absolute offset* within the window.
    Uses manually adjusted input times if offset is configured.
    """
    if not beatmap_data or beatmap_od is None or not input_actions:
        logging.warning("Missing beatmap data, OD, or input actions for correlation.")
        return []

    hit_offsets = []
    used_input_indices = set()
    last_input_search_idx = 0

    rate = 1.0
    if Mod.DoubleTime in mods or Mod.Nightcore in mods: rate = 1.5
    elif Mod.HalfTime in mods: rate = 0.75

    try:
        od = beatmap_od
        miss_window_ms = get_hit_window_ms(od, '50', mods)
        logging.info(f"Using miss window (OD50): ±{miss_window_ms:.2f} ms (OD={od}, Mods={mods})")
    except Exception as e:
        logging.error(f"Error calculating miss window: {e}. Using default 200ms.")
        miss_window_ms = 200

    try:
        beatmap_objects = beatmap_data.get('hitObjects', [])
        if not beatmap_objects:
             logging.warning("Beatmap data contains no 'hitObjects'.")
             return []

        logging.info(f"Correlating {len(input_actions)} inputs with {len(beatmap_objects)} beatmap objects...")
        objects_correlated = 0
        for obj_index, obj in enumerate(beatmap_objects):
            obj_type = obj.get('object_name')
            if obj_type not in ['circle', 'slider']: continue

            expected_hit_time_ms = obj.get('startTime')
            if expected_hit_time_ms is None:
                logging.warning(f"Skipping hit object {obj_index} due to missing 'startTime'")
                continue

            adjusted_expected_hit_time = expected_hit_time_ms / rate
            window_start = adjusted_expected_hit_time - miss_window_ms
            window_end = adjusted_expected_hit_time + miss_window_ms

            best_match_input_index = -1
            min_abs_offset = float('inf')

            for i in range(last_input_search_idx, len(input_actions)):
                action = input_actions[i]
                # Use the (potentially adjusted) time from parse_replay_file
                input_time_ms = action['time']

                if input_time_ms < window_start - miss_window_ms:
                    if i not in used_input_indices: last_input_search_idx = i + 1
                    continue
                if input_time_ms > window_end: break

                if window_start <= input_time_ms <= window_end and i not in used_input_indices:
                    current_offset = input_time_ms - adjusted_expected_hit_time
                    current_abs_offset = abs(current_offset)
                    if current_abs_offset < min_abs_offset:
                        min_abs_offset = current_abs_offset
                        best_match_input_index = i
                        logging.debug(f"    [Obj {obj_index} @ {adjusted_expected_hit_time:.0f}ms] New best potential match: Input {i} @ {input_time_ms:.0f}ms (Offset: {current_offset:.2f}ms, Abs: {current_abs_offset:.2f}ms)")

            if best_match_input_index != -1:
                # Use the (potentially adjusted) time for offset calculation
                matched_input_time_ms = input_actions[best_match_input_index]['time']
                offset = matched_input_time_ms - adjusted_expected_hit_time
                if abs(offset) <= miss_window_ms:
                    hit_offsets.append(offset)
                    used_input_indices.add(best_match_input_index)
                    objects_correlated += 1
                    last_input_search_idx = best_match_input_index + 1
                    logging.debug(f"  -> Matched HO {obj_index} (T={adjusted_expected_hit_time:.0f}) with Input {best_match_input_index} (T={matched_input_time_ms:.0f}). Final Offset: {offset:.2f}")
                else:
                    logging.warning(f"  -> Rejected match for HO {obj_index}: Offset {offset:.2f} outside window ±{miss_window_ms:.2f}ms.")
            else:
                 logging.debug(f"  -> No input found for HO {obj_index} (T={adjusted_expected_hit_time:.0f}) within window [{window_start:.0f}ms - {window_end:.0f}ms]")

        logging.info(f"Correlation complete. Matched {objects_correlated} hits. Found {len(hit_offsets)} valid hit offsets.")
        if not hit_offsets:
            logging.warning("No hits were successfully correlated. Could not calculate average offset.")

    except Exception as e:
        logging.error(f"An unexpected error occurred during correlation: {e}")
        traceback.print_exc()
        return []

    return hit_offsets


# --- Main Analysis Function ---
def process_replay(replay_path):
    """Processes a single replay file."""
    logging.info(f"--- Starting Analysis for {os.path.basename(replay_path)} ---")

    # 1. Parse Replay (applies manual offset if set)
    replay_data = parse_replay_file(replay_path)
    if not replay_data:
        logging.error("Failed to parse replay file.")
        return

    beatmap_hash = replay_data['beatmap_hash']
    mods = replay_data['mods']
    input_actions = replay_data['input_actions']

    # 2. Find Beatmap Path and OD using osu!.db
    map_path, od_from_db = lookup_beatmap_in_db(beatmap_hash)
    if not map_path:
        logging.error(f"Could not find beatmap file path for hash {beatmap_hash}. Skipping analysis.")
        return
    if od_from_db is None:
        logging.warning(f"Could not determine OD for hash {beatmap_hash} from DB. Skipping correlation.")
        return

    # 3. Parse Beatmap using BeatmapParser
    beatmap_data = parse_osu_file(map_path)
    if not beatmap_data:
        logging.error("Failed to parse the beatmap file. Skipping analysis.")
        return

    # 4. Correlate and Calculate Offsets
    hit_offsets = correlate_inputs_and_calculate_offsets(input_actions, beatmap_data, od_from_db, mods)

    # 5. Calculate Average and Display
    if hit_offsets:
        try:
            average_offset = statistics.mean(hit_offsets)
            stdev_offset = statistics.stdev(hit_offsets) if len(hit_offsets) > 1 else 0.0
            unstable_rate = stdev_offset * 10

            logging.info("--- Analysis Results ---")
            logging.info(f" Replay: {os.path.basename(replay_path)}")
            logging.info(f" Map: {os.path.basename(map_path)}")
            logging.info(f" Mods: {mods}")
            # Add note if manual offset was used
            if MANUAL_REPLAY_OFFSET_MS != 0:
                 logging.info(f" Replay Time Offset: {MANUAL_REPLAY_OFFSET_MS} ms (Applied)")
            logging.info(f" Average Hit Offset: {average_offset:+.2f} ms")
            logging.info(f" Hit Offset StDev:   {stdev_offset:.2f} ms")
            logging.info(f" Unstable Rate (UR): {unstable_rate:.2f}")

            tendency = "ON TIME"
            if average_offset < -2.0: tendency = "EARLY"
            elif average_offset > 2.0: tendency = "LATE"
            logging.info(f" Tendency: Hitting {tendency}")
            print(f"Result for {os.path.basename(replay_path)}: Average Hit Offset: {average_offset:+.2f} ms ({tendency})")
            logging.info("------------------------")

        except statistics.StatisticsError as stat_error:
            logging.error(f"Statistics error (likely not enough data points): {stat_error}")
            logging.warning("Could not calculate statistics for offsets.")
            logging.warning("------------------------")
        except Exception as e:
             logging.error(f"Error calculating statistics: {e}")
             traceback.print_exc()
             logging.warning("------------------------")
    else:
       logging.warning("--- Analysis Results ---")
       logging.warning(" Could not calculate average hit offset (correlation failed or no offsets found).")
       logging.warning("------------------------")


# --- Watchdog Event Handler ---
class ReplayHandler(FileSystemEventHandler):
    """Handles file system events for new replay files."""
    def __init__(self):
        self.last_processed_path = None
        self.last_processed_time = 0
        self.debounce_period = 2.0 # Seconds

    def on_created(self, event):
        """Called when a file or directory is created."""
        current_time = time.time()
        if not event.is_directory and event.src_path.lower().endswith(".osr"):
            file_path = event.src_path
            logging.debug(f"File creation event detected: {file_path}")

            if file_path == self.last_processed_path and \
               current_time - self.last_processed_time < self.debounce_period:
                logging.debug(f"Debouncing event for recently processed file: {os.path.basename(file_path)}")
                return

            time.sleep(0.5) # Wait for file write
            if os.path.exists(file_path):
                try: # Check size stability
                    size1 = os.path.getsize(file_path)
                    time.sleep(0.2)
                    size2 = os.path.getsize(file_path)
                    if size1 != size2:
                        logging.warning(f"File size still changing for {os.path.basename(file_path)}, delaying.")
                        time.sleep(0.5)
                except OSError as e:
                    logging.error(f"Error checking file size for {file_path}: {e}")

                logging.info(f"Processing new replay: {os.path.basename(file_path)}")
                self.last_processed_path = file_path
                self.last_processed_time = current_time

                try:
                    process_replay(file_path)
                except Exception as e:
                    logging.error(f"--- ERROR during processing {os.path.basename(file_path)} ---")
                    traceback.print_exc()
                    logging.error("-----------------------------------------------------")
                finally:
                     if REPLAYS_FOLDER:
                         print(f"\nMonitoring for new replays in: {REPLAYS_FOLDER.replace(os.sep, '/')}")
                         print("Press Ctrl+C to stop.")
                     else:
                         print("\nMonitoring... (Replays folder path not set globally?)")
                         print("Press Ctrl+C to stop.")
            else:
                logging.warning(f"File disappeared before processing could start: {file_path}")


# --- Main Execution ---
if __name__ == "__main__":
    print("osu! Average Hit Offset Analyzer")
    print("==============================")

    try:
        # Load configuration paths and settings
        REPLAYS_FOLDER, SONGS_FOLDER, OSU_DB_PATH = load_config()

        # Load osu!.db database ONCE at startup
        OSU_DB = load_osu_database(OSU_DB_PATH)

    except (NotADirectoryError, FileNotFoundError, configparser.Error, ValueError, ImportError, Exception) as e:
        logging.critical(f"Initialization failed: {e}")
        traceback.print_exc()
        if isinstance(e, ImportError):
             print("\n--- Import Error ---")
             print("Please ensure you have installed the required libraries:")
             print(" - osrparse: pip install osrparse")
             print(" - watchdog: pip install watchdog")
             print("Also ensure osu_db.py, beatmapparser.py and their dependencies")
             print("(construct, osu_string.py, path_util.py, slidercalc.py, curve.py)")
             print("are in the same directory as analyze_replay.py or in your Python path.")
             print("Make sure curve.py includes the '.length' fix if needed.")
             print("--------------------\n")
        # input("Press Enter to exit...")
        sys.exit(1)

    logging.info(f"Replays Folder: {REPLAYS_FOLDER.replace(os.sep, '/')}")
    logging.info(f"Songs Folder: {SONGS_FOLDER.replace(os.sep, '/')}")
    logging.info(f"osu!.db Path: {OSU_DB_PATH.replace(os.sep, '/')}")

    event_handler = ReplayHandler()
    observer = Observer()
    observer.schedule(event_handler, REPLAYS_FOLDER, recursive=False)

    logging.info(f"\nMonitoring for new replays in: {REPLAYS_FOLDER.replace(os.sep, '/')}")
    print("Press Ctrl+C to stop.")

    observer.start()
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        logging.info("\nStopping monitoring...")
        observer.stop()
    except Exception as e:
        logging.error(f"\nAn unexpected error occurred during monitoring:")
        traceback.print_exc()
        observer.stop()

    observer.join()
    logging.info("Analyzer stopped.")

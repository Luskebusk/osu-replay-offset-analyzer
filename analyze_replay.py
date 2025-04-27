# analyze_replay.py

import configparser
import os
import sys
import time
import statistics
import traceback # For better error printing
import logging # For better logging

# --- Parser Imports ---
# Use osu!.db parser (requires construct, osu_db.py, osu_string.py, path_util.py etc.)
from osu_db import osu_db
# Use osrparse for replays
from osrparse import Replay, GameMode, Mod, Key
# Use python-osu-parser for .osu files (requires beatmapparser.py, slidercalc.py, curve.py)
# Ensure curve.py has the .length fix applied (len())
from beatmapparser import BeatmapParser
# --- End Parser Imports ---

# Watchdog for monitoring
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# --- Configuration ---
CONFIG_FILE = 'config.ini'

# --- Global Variables (Set by load_config and main block) ---
REPLAYS_FOLDER = ""
SONGS_FOLDER = ""
OSU_DB_PATH = ""
OSU_DB = None # Will hold the loaded osu!.db data

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO, # Change to logging.DEBUG for more detailed correlation logs
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# --- Configuration Loading ---
def load_config():
    """Loads and validates paths from the configuration file."""
    config = configparser.ConfigParser()
    if not os.path.exists(CONFIG_FILE):
        logging.error(f"Configuration file not found: {CONFIG_FILE}")
        # Create a default config if it doesn't exist
        print(f"'{CONFIG_FILE}' not found. Creating a default config file.")
        print("Please edit it with your actual osu! Replays, Songs, and osu!.db paths.")
        config['Paths'] = {
            'OsuReplaysFolder': r'C:\Path\To\Your\osu!\Replays', # Example
            'OsuSongsFolder': r'C:\Path\To\Your\osu!\Songs',   # Example
            'OsuDbPath': r'C:\Path\To\Your\osu!\osu!.db'       # Example
        }
        with open(CONFIG_FILE, 'w') as configfile:
            config.write(configfile)
        sys.exit(f"Exiting. Please edit '{CONFIG_FILE}' and restart.")

    try:
        config.read(CONFIG_FILE)
    except configparser.Error as e:
        logging.error(f"Error reading configuration file: {e}")
        raise ValueError(f"Error reading configuration file: {e}") from e

    if 'Paths' not in config:
        logging.error("Missing [Paths] section in config.ini")
        raise ValueError("Missing [Paths] section in config.ini")

    try:
        # --- CORRECTED ACCESS ---
        replays_path_str = config['Paths']['OsuReplaysFolder']
        songs_path_str = config['Paths']['OsuSongsFolder']
        osu_db_path_str = config['Paths']['OsuDbPath']
        # --- END CORRECTION ---
    except KeyError as e:
        logging.error(f"Missing key {e} in '{CONFIG_FILE}' under [Paths].")
        sys.exit(f"Please check your config file for the key: {e}")
    except configparser.NoSectionError:
        logging.error(f"Missing section [Paths] in '{CONFIG_FILE}'.")
        sys.exit("Please check your config file structure.")

    # Validate paths
    if not os.path.isdir(replays_path_str):
        raise NotADirectoryError(f"Configured Replays folder not found or not a directory: {replays_path_str}")
    if not os.path.isdir(songs_path_str):
        raise NotADirectoryError(f"Configured Songs folder not found or not a directory: {songs_path_str}")
    if not os.path.isfile(osu_db_path_str):
        raise FileNotFoundError(f"Configured osu!.db file not found: {osu_db_path_str}")

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
                    full_map_path = os.path.join(SONGS_FOLDER, folder_name, osu_filename)
                    logging.info(f"  Constructed Path: {full_map_path}")
                    logging.info(f"  Overall Difficulty (OD) from DB: {od}")

                    if os.path.isfile(full_map_path):
                        return full_map_path, float(od) # Return path and OD as float
                    else:
                        logging.warning(f"Found entry in osu!.db but file not found at: {full_map_path}")
                        return None, None # File missing on disk
                else:
                    # This is where the previous warning came from
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
                continue

            current_time += event.time_delta
            current_press_state = event.keys & relevant_keys_mask
            # Detect only the keys that were *just* pressed (transition from 0 to 1)
            pressed_now = current_press_state & ~last_key_state

            # Only record the timestamp when a relevant key is *pressed down*
            if pressed_now > 0:
                input_actions.append({'time': current_time, 'keys': pressed_now})

            last_key_state = current_press_state # Update the state for the next iteration

        logging.info(f"  Found {len(input_actions)} input actions (key/mouse presses).")

        if not input_actions:
            logging.warning("No input actions found in replay data.")
            # Decide if this is critical - returning None might be better
            # return None

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
    # Base ms for OD 0
    base_ms = {
        '300': 79.5,
        '100': 139.5,
        '50': 199.5
    }
    # Reduction per OD point
    ms_reduction_per_od = {
        '300': 6,
        '100': 8,
        '50': 10
    }

    if window_type not in base_ms:
        logging.error(f"Invalid window_type '{window_type}' requested.")
        raise ValueError("Invalid window_type. Use '300', '100', or '50'.")

    # Calculate base window for the given OD
    # Ensure OD is treated as a float for calculation
    try:
        od_float = float(od)
    except (ValueError, TypeError):
        logging.error(f"Invalid OD value for hit window calculation: {od}. Using OD 5 as fallback.")
        od_float = 5.0 # Default fallback OD

    window = base_ms[window_type] - ms_reduction_per_od[window_type] * od_float

    # Adjust for mods affecting speed (DT/NC, HT)
    rate = 1.0
    if Mod.DoubleTime in mods or Mod.Nightcore in mods: # Use osrparse.Mod
        rate = 1.5
    elif Mod.HalfTime in mods: # Use osrparse.Mod
        rate = 0.75

    # Hit windows are tighter with higher rate
    adjusted_window = window / rate

    return max(0, adjusted_window) # Ensure window isn't negative

# --- Correlation Logic ---
def correlate_inputs_and_calculate_offsets(input_actions, beatmap_data, beatmap_od, mods):
    """Correlates inputs to hit objects and calculates hit offsets."""
    if not beatmap_data or beatmap_od is None or not input_actions:
        logging.warning("Missing beatmap data, OD, or input actions for correlation.")
        return [] # Return empty list if data is missing

    hit_offsets = [] # Correctly initialized as list
    used_input_indices = set()
    last_input_index = 0 # Optimization for searching inputs

    # Determine rate modifier for adjusting beatmap times
    rate = 1.0
    if Mod.DoubleTime in mods or Mod.Nightcore in mods:
        rate = 1.5
    elif Mod.HalfTime in mods:
        rate = 0.75

    # Calculate the largest window (miss window = 50 window) for matching
    try:
        # Use the OD passed into the function (from DB lookup)
        od = beatmap_od
        miss_window_ms = get_hit_window_ms(od, '50', mods)
        logging.info(f"Using miss window (±50ms equivalent): ±{miss_window_ms:.2f} ms (OD={od}, Mods={mods})")
    except Exception as e:
        logging.error(f"Error calculating miss window: {e}. Using default 200ms.")
        traceback.print_exc()
        miss_window_ms = 200 # Default fallback

    # Access hit objects from the beatmap_data dictionary
    try:
        beatmap_objects = beatmap_data.get('hitObjects', [])
        if not beatmap_objects:
             logging.warning("Beatmap data contains no 'hitObjects'.")
             return []

        logging.info(f"Correlating {len(input_actions)} inputs with {len(beatmap_objects)} beatmap objects...")

        objects_correlated = 0
        for obj_index, obj in enumerate(beatmap_objects):
            obj_type = obj.get('object_name')
            # Only process circles and slider starts for simple offset calculation
            if obj_type not in ['circle', 'slider']:
                continue

            # Expected time is in ms
            expected_hit_time_ms = obj.get('startTime', 0)
            if expected_hit_time_ms is None:
                logging.warning(f"Skipping hit object {obj_index} due to missing 'startTime'")
                continue

            # Adjust expected hit time based on rate mods
            adjusted_expected_hit_time = expected_hit_time_ms / rate

            # Define the time window for searching inputs
            window_start = adjusted_expected_hit_time - miss_window_ms
            window_end = adjusted_expected_hit_time + miss_window_ms

            best_match_input_index = -1

            # Search for the *first unused* input action within the window
            for i in range(last_input_index, len(input_actions)):
                action = input_actions[i]
                input_time_ms = action['time']

                if i in used_input_indices:
                    continue

                if input_time_ms > window_end:
                    break # Inputs are sorted by time, no need to check further

                if input_time_ms >= window_start:
                    # Found the first potential unused input within the window
                    best_match_input_index = i
                    break # Use this input

            if best_match_input_index != -1:
                # Found a correlated input
                matched_input_time_ms = input_actions[best_match_input_index]['time']
                offset = matched_input_time_ms - adjusted_expected_hit_time
                hit_offsets.append(offset)
                used_input_indices.add(best_match_input_index)
                # Optimization: Start next search from the input *after* the one we just used
                last_input_index = best_match_input_index + 1
                objects_correlated += 1
                logging.debug(f"  Matched HO {obj_index} (T={adjusted_expected_hit_time:.0f}) with Input {best_match_input_index} (T={matched_input_time_ms:.0f}). Offset: {offset:.2f}")
            else:
                 logging.debug(f"  No input found for HO {obj_index} (T={adjusted_expected_hit_time:.0f})")


        logging.info(f"Correlation complete. Matched {objects_correlated} hits. Found {len(hit_offsets)} valid hit offsets.")
        if not hit_offsets:
            logging.warning("No hits were successfully correlated. Could not calculate average offset.")

    except Exception as e:
        logging.error(f"An unexpected error occurred during correlation: {e}")
        traceback.print_exc()
        return [] # Return empty list on error

    return hit_offsets


# --- Main Analysis Function ---
def process_replay(replay_path):
    """Processes a single replay file."""
    logging.info(f"--- Starting Analysis for {os.path.basename(replay_path)} ---")

    # 1. Parse Replay
    replay_data = parse_replay_file(replay_path)
    if not replay_data:
        logging.error("Failed to parse replay file.")
        return

    beatmap_hash = replay_data['beatmap_hash']
    mods = replay_data['mods'] # osrparse Mod enum
    input_actions = replay_data['input_actions']

    # 2. Find Beatmap Path and OD using osu!.db
    map_path, od_from_db = lookup_beatmap_in_db(beatmap_hash)
    if not map_path:
        logging.error(f"Could not find beatmap file path for hash {beatmap_hash}. Skipping analysis.")
        return
    if od_from_db is None:
        logging.warning(f"Could not determine OD for hash {beatmap_hash} from DB. Skipping correlation.")
        # Potentially add fallback to parse OD from .osu file here if needed,
        # but BeatmapParser doesn't easily provide it. Skipping is safer.
        return

    # 3. Parse Beatmap using BeatmapParser
    beatmap_data = parse_osu_file(map_path) # Now returns a dict
    if not beatmap_data:
        logging.error("Failed to parse the beatmap file. Skipping analysis.")
        return

    # 4. Correlate and Calculate Offsets
    # Pass the beatmap_data dict and the OD from DB lookup
    hit_offsets = correlate_inputs_and_calculate_offsets(input_actions, beatmap_data, od_from_db, mods)

    # 5. Calculate Average and Display
    if hit_offsets: # Check if the list is not None and not empty
        try:
            average_offset = statistics.mean(hit_offsets)
            # Calculate stdev only if more than one hit exists
            stdev_offset = statistics.stdev(hit_offsets) if len(hit_offsets) > 1 else 0.0
            # Calculate UR (Unstable Rate) = standard deviation * 10
            unstable_rate = stdev_offset * 10

            logging.info("--- Analysis Results ---")
            logging.info(f" Replay: {os.path.basename(replay_path)}")
            logging.info(f" Map: {os.path.basename(map_path)}")
            logging.info(f" Mods: {mods}")
            logging.info(f" Average Hit Offset: {average_offset:+.2f} ms") # Added + sign for clarity
            logging.info(f" Hit Offset StDev:   {stdev_offset:.2f} ms")
            logging.info(f" Unstable Rate (UR): {unstable_rate:.2f}")

            # Determine Tendency
            if average_offset < -1.5: # Threshold can be adjusted
                logging.info(" Tendency: Hitting EARLY")
                print(f"Result for {os.path.basename(replay_path)}: Average Hit Offset: {average_offset:+.2f} ms (EARLY)")
            elif average_offset > 1.5: # Threshold can be adjusted
                logging.info(" Tendency: Hitting LATE")
                print(f"Result for {os.path.basename(replay_path)}: Average Hit Offset: {average_offset:+.2f} ms (LATE)")
            else:
                logging.info(" Tendency: Hitting ON TIME")
                print(f"Result for {os.path.basename(replay_path)}: Average Hit Offset: {average_offset:+.2f} ms (ON TIME)")
            logging.info("------------------------")

        except statistics.StatisticsError as stat_error:
            logging.error(f"Statistics error (likely not enough data points): {stat_error}")
            logging.warning("Could not calculate statistics for offsets.")
            logging.warning("------------------------")
        except Exception as e:
             logging.error(f"Error calculating statistics: {e}")
             traceback.print_exc()
             logging.warning("------------------------")

    else: # hit_offsets list is empty
         logging.warning("--- Analysis Results ---")
         logging.warning(" Could not calculate average hit offset (correlation failed or no offsets found).")
         logging.warning("------------------------")


# --- Watchdog Event Handler ---
class ReplayHandler(FileSystemEventHandler):
    """Handles file system events for new replay files."""
    def __init__(self):
        self.last_event_time = 0
        self.debounce_period = 2.0 # Seconds to wait between processing files

    def on_created(self, event):
        """Called when a file or directory is created."""
        current_time = time.time()
        if not event.is_directory and event.src_path.lower().endswith(".osr"):
            file_path = event.src_path
            logging.debug(f"File creation event detected: {file_path}")

            # Simple debounce: process only if enough time has passed since last event
            if current_time - self.last_event_time > self.debounce_period:
                # Wait a moment to ensure file is fully written
                time.sleep(0.5)
                if os.path.exists(file_path):
                    logging.info(f"Processing new replay: {os.path.basename(file_path)}")
                    self.last_event_time = current_time # Update time *before* processing
                    try:
                        process_replay(file_path)
                        # Reprint monitoring message after successful processing
                        print(f"\nMonitoring for new replays in: {REPLAYS_FOLDER.replace(os.sep, '/')}")
                        print("Press Ctrl+C to stop.")
                    except Exception as e:
                        logging.error(f"--- ERROR during processing {os.path.basename(file_path)} ---")
                        traceback.print_exc()
                        logging.error("-----------------------------------------------------")
                        # Reprint monitoring message even after error
                        print(f"\nMonitoring for new replays in: {REPLAYS_FOLDER.replace(os.sep, '/')}")
                        print("Press Ctrl+C to stop.")
                else:
                    logging.warning(f"File disappeared before processing could start: {file_path}")
            else:
                logging.debug(f"Debouncing event for {file_path}")


# --- Main Execution ---
if __name__ == "__main__":
    print("osu! Average Hit Offset Analyzer")
    print("==============================")

    try:
        # Load configuration paths
        REPLAYS_FOLDER, SONGS_FOLDER, OSU_DB_PATH = load_config()

        # Load osu!.db database ONCE at startup
        OSU_DB = load_osu_database(OSU_DB_PATH)

    except (NotADirectoryError, FileNotFoundError, configparser.Error, ValueError, Exception) as e:
        logging.critical(f"Initialization failed: {e}")
        traceback.print_exc()
        sys.exit(1) # Exit if config or db loading fails

    # Print paths using forward slashes for consistency
    logging.info(f"Replays Folder: {REPLAYS_FOLDER.replace(os.sep, '/')}")
    logging.info(f"Songs Folder: {SONGS_FOLDER.replace(os.sep, '/')}")
    logging.info(f"osu!.db Path: {OSU_DB_PATH.replace(os.sep, '/')}")

    # Setup and start the watchdog observer
    event_handler = ReplayHandler()
    observer = Observer()
    observer.schedule(event_handler, REPLAYS_FOLDER, recursive=False) # Don't need recursive

    logging.info(f"\nMonitoring for new replays in: {REPLAYS_FOLDER.replace(os.sep, '/')}")
    print("Press Ctrl+C to stop.") # Keep this for user interaction

    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("\nStopping monitoring...")
        observer.stop()
    except Exception as e:
        logging.error(f"\nAn unexpected error occurred during monitoring:")
        traceback.print_exc()
        observer.stop() # Ensure observer stops on other errors too

    observer.join()
    logging.info("Analyzer stopped.")
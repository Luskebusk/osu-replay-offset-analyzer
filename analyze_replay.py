# analyze_replay.py

import configparser
import os
import sys
import time
import statistics
import traceback # For better error printing
import logging # For better logging

# --- New Imports ---
from osu_db import OsuDb # For osu!.db parsing (from osu_db.py)
import rosu_pp_py as rosu # For.osu parsing (rename to avoid conflict with os)
# --- End New Imports ---

from osrparse import Replay, GameMode, Mod, Key # Keep osrparse

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
    level=logging.INFO,
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
        replays_path_str = config['Paths']
        songs_path_str = config['Paths']
        osu_db_path_str = config['Paths']['OsuDbPath'] # Read the new path
    except KeyError as e:
        logging.error(f"Missing key {e} in '{CONFIG_FILE}' under [Paths].")
        sys.exit("Please check your config file.")

    # Validate paths
    if not os.path.isdir(replays_path_str):
        raise NotADirectoryError(f"Configured Replays folder not found or not a directory: {replays_path_str}")
    if not os.path.isdir(songs_path_str):
        raise NotADirectoryError(f"Configured Songs folder not found or not a directory: {songs_path_str}")
    if not os.path.isfile(osu_db_path_str): # Check if osu!.db is a file
        raise FileNotFoundError(f"Configured osu!.db file not found: {osu_db_path_str}")

    # Return all three paths
    logging.info("Configuration paths validated.")
    return replays_path_str, songs_path_str, osu_db_path_str

# --- Load osu!.db ---
def load_osu_database(db_path):
    """Loads the osu!.db file into memory."""
    logging.info(f"Loading osu!.db from: {db_path}...")
    start_time = time.time()
    try:
        # Use the OsuDb class imported from the local osu_db.py file
        osu_db = OsuDb.from_file(db_path) # [1]
        load_time = time.time() - start_time
        logging.info(f"osu!.db loaded successfully in {load_time:.2f} seconds.")
        # Optional: Log number of beatmaps found
        if hasattr(osu_db, 'beatmaps'):
             logging.info(f"Found {len(osu_db.beatmaps)} beatmap entries.")
        return osu_db
    except Exception as e:
        logging.error(f"FATAL: Failed to load or parse osu!.db: {e}")
        traceback.print_exc()
        sys.exit("Exiting due to osu!.db loading error.")

# --- Beatmap Lookup (Replaces find_and_parse_beatmap) ---
def lookup_beatmap_in_db(beatmap_hash):
    """Looks up beatmap path information in the loaded osu!.db by hash."""
    global OSU_DB # Access the globally loaded database object
    if OSU_DB is None:
        logging.error("osu!.db is not loaded. Cannot perform lookup.")
        return None, None # Return None for both path and OD

    logging.info(f"Searching osu!.db for beatmap with hash: {beatmap_hash}...")
    try:
        # Iterate through beatmaps to find the hash
        # Note: osu_db_parser library might offer a direct lookup method,
        # but iteration is a safe fallback if the exact method isn't known/stable.
        # Check the structure of osu_db.py if direct lookup is needed.
        if not hasattr(OSU_DB, 'beatmaps'):
             logging.error("Loaded osu!.db object has no 'beatmaps' attribute.")
             return None, None

        for beatmap_entry in OSU_DB.beatmaps:
            # Access attributes safely
            entry_hash = getattr(beatmap_entry, 'md5_hash', None)
            if entry_hash and entry_hash.lower() == beatmap_hash.lower():
                folder_name = getattr(beatmap_entry, 'folder_name', None)
                osu_filename = getattr(beatmap_entry, 'osu_filename', None) # Check exact name in osu_db.py
                od = getattr(beatmap_entry, 'od', None) # Try to get OD

                if folder_name and osu_filename:
                    logging.info(f"Found beatmap entry in osu!.db: {folder_name}\\{osu_filename}")
                    # Construct the full path
                    full_map_path = os.path.join(SONGS_FOLDER, folder_name, osu_filename)
                    logging.info(f"  Constructed Path: {full_map_path}")
                    if od is not None:
                         logging.info(f"  Overall Difficulty (OD) from DB: {od}")
                    else:
                         logging.warning("  Could not retrieve OD directly from DB entry.")

                    # IMPORTANT: Verify the file actually exists on disk
                    if os.path.isfile(full_map_path):
                         return full_map_path, od # Return path and OD (or None if OD wasn't found)
                    else:
                         logging.warning(f"Found entry in osu!.db but file not found at: {full_map_path}")
                         return None, None # File missing
                else:
                    logging.warning(f"Found hash {beatmap_hash} but entry missing folder/filename.")
                    return None, None # Incomplete entry

        # If loop finishes without finding the hash
        logging.warning(f"Beatmap hash {beatmap_hash} not found in osu!.db.")
        return None, None # Hash not found

    except Exception as e:
        logging.error(f"Error looking up beatmap hash {beatmap_hash} in osu!.db: {e}")
        traceback.print_exc()
        return None, None

# ---.osu File Parsing (Using rosu-pp-py) ---
def parse_osu_file(map_path):
    """Parses the.osu file using rosu-pp-py."""
    logging.info(f"Parsing beatmap: {os.path.basename(map_path)} using rosu-pp-py...")
    try:
        # Use rosu-pp-py's Beatmap class to parse
        rosu_beatmap = rosu.Beatmap(path=map_path)
        logging.info("Beatmap parsed successfully with rosu-pp-py.")
        return rosu_beatmap
    except Exception as e:
        logging.error(f"Error parsing.osu file {os.path.basename(map_path)} with rosu-pp-py:")
        traceback.print_exc()
        return None

# --- Replay Parsing ---
def parse_replay_file(replay_path):
    """Parses an.osr file and extracts relevant data."""
    try:
        logging.info(f"Parsing replay: {os.path.basename(replay_path)}...")
        replay = Replay.from_path(replay_path)

        # Check if the game mode is Standard (use OSU)
        # Note: osrparse GameMode enum might use different names depending on version.
        # GameMode.STD or GameMode.OSU are common. Check osrparse docs if needed.
        # Let's try GameMode.OSU first as it's often used.
        if replay.mode!= GameMode.OSU:
            logging.warning(f"Skipping non-standard replay: {replay.mode}")
            return None

        beatmap_hash = replay.beatmap_hash
        mods_enum = replay.mods # Keep as osrparse Mod enum
        replay_events = replay.replay_data

        logging.info(f"  Beatmap Hash: {beatmap_hash}")
        logging.info(f"  Mods: {mods_enum}")

        input_actions = '' # Initialize as list
        current_time = 0
        last_key_state = 0
        relevant_keys_mask = Key.M1 | Key.M2 | Key.K1 | Key.K2

        for event in replay_events:
            # Skip potential initial junk frames more reliably
            if event.time_delta < 0 and current_time == 0:
                continue

            current_time += event.time_delta
            current_press_state = event.keys & relevant_keys_mask
            pressed_now = current_press_state & ~last_key_state

            if pressed_now > 0:
                input_actions.append({'time': current_time, 'keys': pressed_now})

            last_key_state = current_press_state

        logging.info(f"  Found {len(input_actions)} input actions (key/mouse presses).")

        if not input_actions:
            logging.warning("No input actions found in replay data.")

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
    # Base ms for OD 0 [2]
    base_ms = {
        '300': 79.5,
        '100': 139.5,
        '50': 199.5
    }
    # Reduction per OD point [2]
    ms_reduction_per_od = {
        '300': 6,
        '100': 8,
        '50': 10
    }

    if window_type not in base_ms:
        logging.error(f"Invalid window_type '{window_type}' requested.")
        raise ValueError("Invalid window_type. Use '300', '100', or '50'.")

    # Calculate base window for the given OD
    window = base_ms[window_type] - ms_reduction_per_od[window_type] * od

    # Adjust for mods affecting speed (DT/NC, HT) [2]
    rate = 1.0
    if Mod.DoubleTime in mods or Mod.Nightcore in mods: # Use osrparse.Mod
        rate = 1.5
    elif Mod.HalfTime in mods: # Use osrparse.Mod
        rate = 0.75

    # Hit windows are tighter with higher rate
    adjusted_window = window / rate

    # Return the +/- range
    return max(0, adjusted_window) # Ensure window isn't negative

# --- Correlation Logic ---
def correlate_inputs_and_calculate_offsets(input_actions, rosu_beatmap, mods):
    """Correlates inputs to hit objects and calculates hit offsets."""
    if not rosu_beatmap or not input_actions:
        logging.warning("Missing beatmap or input actions for correlation.")
        return

    hit_offsets = ''
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
        # Get OD from the parsed rosu_beatmap object
        od = rosu_beatmap.od
        miss_window_ms = get_hit_window_ms(od, '50', mods)
        logging.info(f"Using miss window (±50ms equivalent): ±{miss_window_ms:.2f} ms (OD={od}, Mods={mods})")
    except Exception as e:
        logging.error(f"Error calculating miss window: {e}. Using default 200ms.")
        miss_window_ms = 200 # Default fallback

    # Access hit objects from rosu-pp-py beatmap object
    try:
        # rosu-pp-py stores hit objects in the 'hit_objects' attribute
        beatmap_objects = rosu_beatmap.hit_objects
        logging.info(f"Correlating {len(input_actions)} inputs with {len(beatmap_objects)} beatmap objects...")

        for obj_index, obj in enumerate(beatmap_objects):
            # Check if the object is a circle or slider start (ignore spinners, slider ends/ticks for offset)
            # rosu-pp-py uses 'kind' attribute: HitObjectKind.Circle, HitObjectKind.Slider, HitObjectKind.Spinner
            if not isinstance(obj.kind, (rosu.HitObjectKind.Circle, rosu.HitObjectKind.Slider)):
                continue

            # Adjust expected hit time based on rate mods
            # 'start_time' attribute holds the time in milliseconds
            expected_hit_time = obj.start_time / rate

            # Define the time window for searching inputs
            window_start = expected_hit_time - miss_window_ms
            window_end = expected_hit_time + miss_window_ms

            best_match_input_index = -1

            # Search for the *first unused* input action within the window
            for i in range(last_input_index, len(input_actions)):
                action = input_actions[i]
                input_time = action['time']

                if i in used_input_indices:
                    continue # Skip already used inputs

                if input_time > window_end:
                    # Since inputs are chronological, no further inputs will be in the window
                    break

                if input_time >= window_start:
                    # Found the first potential unused input within the window
                    best_match_input_index = i
                    break # Use this input

            if best_match_input_index!= -1:
                # Found a correlated input
                matched_input_time = input_actions[best_match_input_index]['time']
                offset = matched_input_time - expected_hit_time
                hit_offsets.append(offset)
                used_input_indices.add(best_match_input_index)
                # Optimization: Start next search from the input *after* the one we just used
                last_input_index = best_match_input_index + 1
                # logging.debug(f"  Matched HO {obj_index} (T={expected_hit_time:.0f}) with Input {best_match_input_index} (T={matched_input_time:.0f}). Offset: {offset:.2f}")
            # else: logging.debug(f"  No input found for HO {obj_index} (T={expected_hit_time:.0f})")

        logging.info(f"Correlation complete. Found {len(hit_offsets)} valid hit offsets.")
        if not hit_offsets:
            logging.warning("No hits were correlated. Could not calculate average offset.")

    except AttributeError as e:
         logging.error(f"Error accessing hit object attributes (e.g., 'kind', 'start_time'): {e}")
         logging.error("The structure of hit objects from rosu-pp-py might be different than expected.")
         return
    except Exception as e:
         logging.error(f"An unexpected error occurred during correlation: {e}")
         traceback.print_exc()
         return

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

    # 2. Find Beatmap Path using osu!.db
    map_path, od_from_db = lookup_beatmap_in_db(beatmap_hash)
    if not map_path:
        logging.error(f"Could not find beatmap info for hash {beatmap_hash}. Skipping analysis.")
        return

    # 3. Parse Beatmap using rosu-pp-py
    rosu_beatmap = parse_osu_file(map_path)
    if not rosu_beatmap:
        logging.error("Failed to parse the beatmap file. Skipping analysis.")
        return

    # Use OD from parsed map if available, otherwise fallback to DB value if it existed
    beatmap_od = rosu_beatmap.od
    if od_from_db is not None and abs(rosu_beatmap.od - od_from_db) > 0.1:
        logging.warning(f"OD mismatch? DB: {od_from_db}, Parsed Map: {rosu_beatmap.od}. Using parsed map value.")
    elif od_from_db is None:
         logging.warning("OD not found in DB, using value from parsed map.")


    # 4. Correlate and Calculate Offsets
    hit_offsets = correlate_inputs_and_calculate_offsets(input_actions, rosu_beatmap, mods)

    # 5. Calculate Average and Display
    if hit_offsets:
        average_offset = statistics.mean(hit_offsets)
        # Calculate stdev only if more than one hit exists
        stdev_offset = statistics.stdev(hit_offsets) if len(hit_offsets) > 1 else 0.0
        # Calculate UR (Unstable Rate) = standard deviation * 10 [3, 4]
        unstable_rate = stdev_offset * 10

        logging.info("--- Analysis Results ---")
        logging.info(f" Replay: {os.path.basename(replay_path)}")
        logging.info(f" Map: {os.path.basename(map_path)}")
        logging.info(f" Mods: {mods}")
        logging.info(f" Average Hit Offset: {average_offset:+.2f} ms") # Added + sign for clarity
        logging.info(f" Hit Offset StDev:   {stdev_offset:.2f} ms")
        logging.info(f" Unstable Rate (UR): {unstable_rate:.2f}")
        if average_offset < -1.5: # Threshold can be adjusted
            logging.info(" Tendency: Hitting EARLY")
        elif average_offset > 1.5: # Threshold can be adjusted
            logging.info(" Tendency: Hitting LATE")
        else:
            logging.info(" Tendency: Hitting ON TIME")
        logging.info("------------------------")

    else:
        logging.warning("--- Analysis Results ---")
        logging.warning(" Could not calculate average hit offset (no hits correlated).")
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

    logging.info(f"Monitoring for new replays in: {REPLAYS_FOLDER}")
    print("Press Ctrl+C to stop.") # Keep this for user interaction

    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Stopping monitoring...")
        observer.stop()
    except Exception as e:
        logging.error(f"An unexpected error occurred during monitoring:")
        traceback.print_exc()
        observer.stop() # Ensure observer stops on other errors too

    observer.join()
    logging.info("Analyzer stopped.")
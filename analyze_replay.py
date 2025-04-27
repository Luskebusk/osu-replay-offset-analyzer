# analyze_replay.py

import configparser
import os
import sys
import time
import statistics
import traceback # For better error printing
import logging # For better logging
import math # For abs value comparison
from datetime import datetime # For datetime operations
import csv # For CSV file operations
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
DEBUG_LOG_FILE = 'analyzer_debug.log'
STATS_CSV_FILE = 'analysis_stats.csv'

# --- Global Variables (Set by load_config and main block) ---
REPLAYS_FOLDER = ""
SONGS_FOLDER = ""
OSU_DB_PATH = ""
OSU_DB = None # Will hold the loaded osu!.db data
MANUAL_REPLAY_OFFSET_MS = 0

# --- Logging Setup ---
# Basic config will be overridden/added to by load_config
logging.basicConfig(
    level=logging.WARNING, # Default level, will be updated by load_config
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger() # Get the root logger

# --- Configuration Loading ---
def load_config():
    """Loads and validates paths and settings from the configuration file."""
    global MANUAL_REPLAY_OFFSET_MS # Allow modification of global variable
    config = configparser.ConfigParser()
    replays_path_str, songs_path_str, osu_db_path_str = None, None, None
    manual_offset_str, log_level_str = '-10', 'INFO' # Defaults updated

    if not os.path.exists(CONFIG_FILE):
        logger.warning(f"Configuration file not found: {CONFIG_FILE}")
        print(f"'{CONFIG_FILE}' not found. Creating a default config file.")
        print("Please edit it with your actual osu! paths and desired settings.")
        config['Paths'] = {
            'OsuReplaysFolder': r'C:\Path\To\Your\osu!\Replays',
            'OsuSongsFolder': r'C:\Path\To\Your\osu!\Songs',
            'OsuDbPath': r'C:\Path\To\Your\osu!\osu!.db'
        }
        config['Settings'] = {
            'LogLevel': 'INFO',
            'ReplayTimeOffsetMs': '-10' # Default offset
        }
        try:
            with open(CONFIG_FILE, 'w') as configfile: config.write(configfile)
            logger.info(f"Default '{CONFIG_FILE}' created. Please edit it and restart.")
        except IOError as e: logger.error(f"Could not write default config file: {e}")
        sys.exit(f"Exiting. Please edit '{CONFIG_FILE}' and restart.")

    try: config.read(CONFIG_FILE)
    except configparser.Error as e: logger.error(f"Error reading config: {e}"); raise ValueError(f"Error reading config: {e}") from e

    if 'Paths' not in config: logger.error("Missing [Paths] in config.ini"); raise ValueError("Missing [Paths] in config.ini")
    try:
        replays_path_str = config['Paths']['OsuReplaysFolder']
        songs_path_str = config['Paths']['OsuSongsFolder']
        osu_db_path_str = config['Paths']['OsuDbPath']
    except KeyError as e: logger.error(f"Missing key {e} in [Paths]."); sys.exit(f"Check config for key: {e}")

    if 'Settings' in config:
        log_level_str = config['Settings'].get('LogLevel', 'INFO').upper()
        manual_offset_str = config['Settings'].get('ReplayTimeOffsetMs', '-10')
    else: logger.warning("Missing [Settings] section in config.ini. Using defaults.")

    if not os.path.isdir(replays_path_str): raise NotADirectoryError(f"Replays folder not found: {replays_path_str}")
    if not os.path.isdir(songs_path_str): raise NotADirectoryError(f"Songs folder not found: {songs_path_str}")
    if not os.path.isfile(osu_db_path_str): raise FileNotFoundError(f"osu!.db not found: {osu_db_path_str}")

    # Setup Logging
    log_levels = {'DEBUG': logging.DEBUG, 'INFO': logging.INFO, 'WARNING': logging.WARNING, 'ERROR': logging.ERROR}
    log_level = log_levels.get(log_level_str, logging.INFO)
    logger.setLevel(log_level)
    for handler in logger.handlers[:]: logger.removeHandler(handler)
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    console_handler = logging.StreamHandler(sys.stdout)
    console_log_level = logging.INFO if log_level > logging.DEBUG else logging.DEBUG
    console_handler.setLevel(console_log_level); console_handler.setFormatter(log_formatter); logger.addHandler(console_handler)
    if log_level == logging.DEBUG:
        try:
            file_handler = logging.FileHandler(DEBUG_LOG_FILE, mode='w', encoding='utf-8')
            file_handler.setLevel(logging.DEBUG); file_handler.setFormatter(log_formatter); logger.addHandler(file_handler)
            logger.info(f"DEBUG level enabled. Logging detailed output to '{DEBUG_LOG_FILE}'")
        except Exception as e: logger.error(f"Failed to create debug log file handler: {e}")
    logger.info(f"Logging level set to {log_level_str}")

    try: MANUAL_REPLAY_OFFSET_MS = int(manual_offset_str)
    except ValueError: logger.warning(f"Invalid ReplayTimeOffsetMs '{manual_offset_str}'. Using 0 ms."); MANUAL_REPLAY_OFFSET_MS = 0
    logger.info(f"Manual Replay Time Offset set to: {MANUAL_REPLAY_OFFSET_MS} ms")
    logger.info("Configuration paths validated.")
    return replays_path_str, songs_path_str, osu_db_path_str

# --- Load osu!.db ---
def load_osu_database(db_path):
    """Loads the osu!.db file into memory."""
    logger.info(f"Loading osu!.db from: {db_path}... This might take a moment.")
    start_time = time.time()
    try:
        osu_db_data = osu_db.parse_file(db_path)
        logger.info(f"osu!.db loaded successfully in {time.time() - start_time:.2f} seconds.")
        return osu_db_data
    except Exception as e: logger.critical(f"FATAL: Failed to load/parse osu!.db: {e}"); traceback.print_exc(); sys.exit("Exiting.")

# --- Beatmap Lookup ---
def lookup_beatmap_in_db(beatmap_hash):
    """Looks up beatmap path, OD, and Star Rating in the loaded osu!.db by hash."""
    global OSU_DB, SONGS_FOLDER
    if OSU_DB is None: return None, None, None # Path, OD, SR
    logger.info(f"Searching osu!.db for beatmap with hash: {beatmap_hash}...")
    found_entry = None
    try:
        if not hasattr(OSU_DB, 'beatmaps'): return None, None, None
        for beatmap_entry in OSU_DB.beatmaps:
            try:
                entry_hash = beatmap_entry.md5_hash
                if entry_hash and entry_hash.lower() == beatmap_hash.lower():
                    found_entry = beatmap_entry; break
            except AttributeError: continue
        if found_entry:
            folder_name, osu_filename, od, star_rating = None, None, None, None
            try:
                folder_name = found_entry.folder_name
                osu_filename = found_entry.osu_file_name
                od = found_entry.overall_difficulty
                if hasattr(found_entry, 'std_stars') and hasattr(found_entry.std_stars, 'stars'):
                    for star_entry in found_entry.std_stars.stars:
                         if hasattr(star_entry, 'int') and star_entry.int == 0:
                             if hasattr(star_entry, 'double'): star_rating = star_entry.double; break
                if star_rating is None: logger.warning(f"Could not find NoMod SR for hash {beatmap_hash}")
                logger.debug(f"Found entry: Folder='{folder_name}', File='{osu_filename}', OD='{od}', SR='{star_rating}'")
                if folder_name and osu_filename:
                    logger.info(f"Found beatmap entry: {folder_name}\\{osu_filename}")
                    full_map_path = os.path.join(SONGS_FOLDER, folder_name, osu_filename)
                    logger.info(f"  Constructed Path: {full_map_path}")
                    logger.info(f"  Overall Difficulty (OD): {od}")
                    logger.info(f"  Star Rating (NoMod): {star_rating if star_rating is not None else 'N/A'}")
                    if os.path.isfile(full_map_path): return full_map_path, float(od) if od is not None else None, float(star_rating) if star_rating is not None else None
                    else: logger.warning(f"DB entry found but file missing: {full_map_path}"); return None, None, None
                else: logger.warning(f"DB entry for hash {beatmap_hash} missing path info."); return None, None, None
            except AttributeError as ae: logger.warning(f"DB entry for hash {beatmap_hash} missing attribute ({ae})."); return None, None, None
        else: logger.warning(f"Beatmap hash {beatmap_hash} not found in osu!.db."); return None, None, None
    except Exception as e: logger.error(f"Error looking up hash {beatmap_hash}: {e}"); traceback.print_exc(); return None, None, None

# --- .osu File Parsing ---
def parse_osu_file(map_path):
    """Parses the .osu file using BeatmapParser."""
    logger.info(f"Parsing beatmap: {os.path.basename(map_path)} using BeatmapParser...")
    try:
        parser = BeatmapParser()
        with open(map_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f: parser.read_line(line)
        parser.build_beatmap(); beatmap_data = parser.beatmap
        logger.info("Beatmap parsed successfully with BeatmapParser.")
        return beatmap_data
    except Exception as e: logger.error(f"Error parsing .osu file {os.path.basename(map_path)}: {e}"); traceback.print_exc(); return None

# --- Replay Parsing ---
def parse_replay_file(replay_path):
    """Parses an .osr file and extracts relevant data."""
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
                    logger.debug(f"  --> SUCCESS: Matched HO {obj_index} (T={adjusted_expected_hit_time:.0f}) with Input {best_match_input_index} (T={matched_input_time_ms:.0f}). Offset: {offset:+.2f}. Last used index: {last_successful_input_index}")
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

# --- Function to save stats (MODIFIED) ---
def save_stats_to_csv(timestamp, replay_name, map_name, mods, avg_offset, ur, matched_hits, score, star_rating):
    """Appends the analysis results to the stats CSV file."""
    file_exists = os.path.isfile(STATS_CSV_FILE)
    try:
        with open(STATS_CSV_FILE, 'a', newline='', encoding='utf-8') as csvfile:
            # --- MODIFIED: Added Score and StarRating ---
            fieldnames = ['Timestamp', 'ReplayFile', 'MapName', 'Mods', 'AvgOffsetMs', 'UR', 'MatchedHits', 'Score', 'StarRating']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            if not file_exists or os.path.getsize(STATS_CSV_FILE) == 0:
                writer.writeheader()
                logger.info(f"Created or found empty stats file: {STATS_CSV_FILE}")

            writer.writerow({
                'Timestamp': timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                'ReplayFile': replay_name,
                'MapName': map_name,
                'Mods': str(mods),
                'AvgOffsetMs': f"{avg_offset:+.2f}",
                'UR': f"{ur:.2f}",
                'MatchedHits': matched_hits,
                'Score': score, # Added score
                'StarRating': f"{star_rating:.2f}" if star_rating is not None else "N/A" # Added SR, formatted
            })
            logger.info(f"Stats saved to {STATS_CSV_FILE}")
    except IOError as e: logger.error(f"Error writing to stats file {STATS_CSV_FILE}: {e}")
    except Exception as e: logger.error(f"Unexpected error saving stats: {e}"); traceback.print_exc()
# --- END MODIFIED Function ---

# --- Main Analysis Function (MODIFIED) ---
def process_replay(replay_path):
    """Processes a single replay file."""
    replay_basename = os.path.basename(replay_path)
    logger.info(f"--- Starting Analysis for {replay_basename} ---")
    analysis_timestamp = datetime.now()

    replay_data = parse_replay_file(replay_path)
    if not replay_data: logger.error("Failed to parse replay."); return
    # --- MODIFIED: Get score ---
    beatmap_hash, mods, input_actions, score = replay_data['beatmap_hash'], replay_data['mods'], replay_data['input_actions'], replay_data['score']

    # --- MODIFIED: Get star rating ---
    map_path, od_from_db, sr_from_db = lookup_beatmap_in_db(beatmap_hash)
    if not map_path: logger.error(f"Could not find map path for hash {beatmap_hash}."); return
    if od_from_db is None: logger.warning(f"Could not determine OD for hash {beatmap_hash}."); return
    # Star rating (sr_from_db) can be None, we handle that later
    map_basename = os.path.basename(map_path)

    beatmap_data = parse_osu_file(map_path)
    if not beatmap_data: logger.error("Failed to parse beatmap."); return

    hit_offsets = correlate_inputs_and_calculate_offsets(input_actions, beatmap_data, od_from_db, mods)

    if hit_offsets:
        try:
            average_offset = statistics.mean(hit_offsets)
            stdev_offset = statistics.stdev(hit_offsets) if len(hit_offsets) > 1 else 0.0
            unstable_rate = stdev_offset * 10
            matched_hits_count = len(hit_offsets)

            logger.info("--- Analysis Results ---")
            logger.info(f" Replay: {replay_basename}")
            logger.info(f" Map: {map_basename}")
            logger.info(f" Mods: {mods}")
            # --- ADDED: Log score and SR ---
            logger.info(f" Score: {score:,}") # Format score with commas
            logger.info(f" Star Rating: {sr_from_db:.2f}*" if sr_from_db is not None else "N/A")
            # --- END ADDED ---
            if MANUAL_REPLAY_OFFSET_MS != 0: logger.info(f" Replay Time Offset: {MANUAL_REPLAY_OFFSET_MS} ms (Applied)")
            logger.info(f" Average Hit Offset: {average_offset:+.2f} ms")
            logger.info(f" Hit Offset StDev:   {stdev_offset:.2f} ms")
            logger.info(f" Unstable Rate (UR): {unstable_rate:.2f}")
            tendency = "ON TIME";
            if average_offset < -2.0: tendency = "EARLY"
            elif average_offset > 2.0: tendency = "LATE"
            logger.info(f" Tendency: Hitting {tendency}")
            print(f"Result for {replay_basename}: Average Hit Offset: {average_offset:+.2f} ms ({tendency})")
            logger.info("------------------------")

            # --- MODIFIED: Call save stats with new args ---
            save_stats_to_csv(
                timestamp=analysis_timestamp,
                replay_name=replay_basename,
                map_name=map_basename,
                mods=mods,
                avg_offset=average_offset,
                ur=unstable_rate,
                matched_hits=matched_hits_count,
                score=score, # Pass score
                star_rating=sr_from_db # Pass star rating (can be None)
            )
            # --- END MODIFIED ---

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
    logger.info("Starting osu! Average Hit Offset Analyzer")
    logger.info("==========================================")
    try:
        REPLAYS_FOLDER, SONGS_FOLDER, OSU_DB_PATH = load_config()
        OSU_DB = load_osu_database(OSU_DB_PATH)
    except (NotADirectoryError, FileNotFoundError, configparser.Error, ValueError, ImportError, Exception) as e:
        logger.critical(f"Initialization failed: {e}"); traceback.print_exc()
        if isinstance(e, ImportError):
             print("\n--- Import Error ---")
             print("Please ensure required libraries (osrparse, watchdog, construct) and script dependencies (osu_db.py, beatmapparser.py, etc.) are installed and accessible.")
             print("See README or script comments for details.")
             print("--------------------\n")
        sys.exit(1)

    logger.info(f"Replays Folder: {REPLAYS_FOLDER.replace(os.sep, '/')}")
    logger.info(f"Songs Folder: {SONGS_FOLDER.replace(os.sep, '/')}")
    logger.info(f"osu!.db Path: {OSU_DB_PATH.replace(os.sep, '/')}")

    event_handler = ReplayHandler(); observer = Observer()
    observer.schedule(event_handler, REPLAYS_FOLDER, recursive=False)
    logger.info(f"\nMonitoring for new replays in: {REPLAYS_FOLDER.replace(os.sep, '/')}")
    print("Press Ctrl+C to stop.")
    observer.start()

    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        logger.info("\nStopping monitoring..."); observer.stop()
    except Exception as e:
        logger.error(f"\nMonitoring error:"); traceback.print_exc(); observer.stop()

    observer.join();
    logger.info("Analyzer stopped.")


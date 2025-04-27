#!/usr/bin/env python
# -*- coding: utf-8 -*-

import time
import configparser
import os
import hashlib
import statistics
import math
import sys
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from osrparse import Replay, ReplayEvent, GameMode, Mod
from osrparse.utils import Key
from beatmapparser import BeatmapParser

# --- Configuration Loading ---
def load_config():
    config = configparser.ConfigParser()
    config_path = 'config.ini'
    if not os.path.exists(config_path):
         # Create a default config if it doesn't exist
        print(f"'{config_path}' not found. Creating a default config file.")
        print("Please edit it with your actual osu! Replays and Songs folder paths.")
        config['Paths'] = {
            'OsuReplaysFolder': r'C:\Users\oleko\AppData\Local\osu!\Replays', # Example Path using raw string
            'OsuSongsFolder': r'C:\Users\oleko\AppData\Local\osu!\Songs'      # Example Path using raw string
        }
        with open(config_path, 'w') as configfile:
            config.write(configfile)
        # Exit after creating config to allow user to edit it
        sys.exit(f"Exiting. Please edit '{config_path}' and restart.")

    try:
        # Read the configuration file first
        read_files = config.read(config_path)
        if not read_files:
            # Handle case where config file exists but couldn't be read/parsed
            raise configparser.Error(f"Could not read or parse config file: {config_path}")

    except configparser.Error as e:
        # Handle potential parsing errors (e.g., malformed file)
        print(f"Error reading configuration file '{config_path}': {e}", file=sys.stderr)
        sys.exit(1) # Exit on parsing error

    try:
        # --- CORRECTED ACCESS ---
        # Access the specific string value for each key within the [Paths] section
        # using config['KeyName'] syntax.
        replays_path_str = config['Paths']['OsuReplaysFolder']
        songs_path_str = config['Paths']['OsuSongsFolder']
        # --- END CORRECTION ---

    except KeyError:
         # This error means either [Paths] section is missing or one of the keys is missing
         print(f"Error: Missing '[Paths]' section or 'OsuReplaysFolder'/'OsuSongsFolder' key in '{config_path}'.")
         sys.exit("Please check your config file structure and content.")
    except configparser.NoSectionError:
         # This should ideally be caught by the KeyError above, but included for robustness
         print(f"Error: Missing '[Paths]' section in '{config_path}'.")
         sys.exit("Please check your config file structure.")

    # --- Validation using the extracted STRINGS ---
    # Use the extracted strings (replays_path_str, songs_path_str) for directory checks
    if not os.path.isdir(replays_path_str): # [1, 2, 3]
        raise NotADirectoryError(f"Configured Replays folder not found or not a directory: {replays_path_str}")
    if not os.path.isdir(songs_path_str): # [1, 2, 3]
        raise NotADirectoryError(f"Configured Songs folder not found or not a directory: {songs_path_str}")

    # Return the validated path strings
    return replays_path_str, songs_path_str

# ---.osu Hashing (Placeholder - Needs Correct Implementation) ---
def calculate_osu_hash(file_path):
    """Placeholder for osu!'s specific beatmap hash calculation."""
    # WARNING: This is NOT the correct osu! beatmap hash algorithm.
    # Replace with a correct implementation or use a library that provides it.
    try:
        hasher = hashlib.md5()
        with open(file_path, 'rb') as f:
             buf = f.read()
             hasher.update(buf) # osu! hash is md5 of the string content, not bytes directly in some contexts. Needs verification.
        return hasher.hexdigest()
    except Exception as e:
        # print(f"Warning: Error calculating placeholder hash for {os.path.basename(file_path)}: {e}")
        return None

# ---.osu Parsing (Using Awlexus/python-osu-parser) ---
def parse_osu_file_internal(osu_path):
    """
    Parses the.osu file using the manually added BeatmapParser.
    """
    print(f"Parsing beatmap: {os.path.basename(osu_path)}...")
    try:
        parser = BeatmapParser() # [4]
        # The parse_file method likely handles reading and processing
        parser.parse_file(osu_path) 

        # Extract data based on the structure observed in the library's code [4]
        raw_hit_objects = parser.beatmap.get("hitObjects",)
        difficulty_section = parser.beatmap.get("Difficulty", {})
        od = float(difficulty_section.get('OverallDifficulty', 5.0)) # Default OD 5

        # Convert hit objects to the format expected by the main script
        hit_objects = ''
        for ho in raw_hit_objects:
            obj_type_str = ho.get("object_name", "unknown")
            obj_time = ho.get("startTime")

            # Map string type back to integer bitmask if possible
            # 1=circle, 2=slider, 8=spinner [4]
            obj_type_int = 0
            if obj_type_str == 'circle':
                obj_type_int = 1
            elif obj_type_str == 'slider':
                obj_type_int = 2
            elif obj_type_str == 'spinner':
                obj_type_int = 8
            # Add other potential mappings if needed, or handle 'unknown'

            if obj_time is not None:
                hit_objects.append({
                    'time': obj_time,
                    'type': obj_type_int
                    # Add x, y if needed by future enhancements:
                    # 'x': ho.get("position", ),
                    # 'y': ho.get("position", )[1]
                })

        if not hit_objects:
            print("Warning: No hit objects extracted from beatmap.")
            # Decide if you want to return None or an empty list
            # return None 

        print(f"  Extracted OD: {od}")
        print(f"  Extracted {len(hit_objects)} hit objects.")

        return {'hit_objects': hit_objects, 'od': od}

    except FileNotFoundError:
         print(f"Error:.osu file not found at {osu_path}")
         return None
    except Exception as e:
        print(f"Error parsing.osu file {os.path.basename(osu_path)} with BeatmapParser: {e}")
        # Consider logging the full traceback for debugging if needed
        # import traceback
        # traceback.print_exc()
        return None


# --- Beatmap Finding ---
def find_and_parse_beatmap(beatmap_hash, songs_dir):
    """Finds the.osu file by hash and parses it."""
    print(f"Searching for beatmap with hash: {beatmap_hash}...")
    found_map_path = None

    # Iterate through song folders - can be slow!
    for root, _, files in os.walk(songs_dir):
        for file in files:
            if file.lower().endswith('.osu'):
                osu_path = os.path.join(root, file)
                current_hash = calculate_osu_hash(osu_path) # Needs correct implementation!
                if current_hash == beatmap_hash:
                    print(f"Found potential match: {osu_path}")
                    found_map_path = osu_path
                    # Attempt to parse to confirm it's likely the right map (optional check)
                    parsed_check = parse_osu_file_internal(found_map_path)
                    if parsed_check: # Basic check if parsing succeeded
                         print(f"Successfully parsed match: {os.path.basename(osu_path)}")
                         return parsed_check # Return the parsed data directly
                    else:
                         print(f"Parsing failed for matched hash file: {os.path.basename(osu_path)}. Continuing search...")
                         found_map_path = None # Reset if parsing failed

        # Optimization: If found in a subdirectory, maybe stop searching further in that branch?
        # This simple version continues searching all files.

    if not found_map_path:
        print(f"Beatmap with hash {beatmap_hash} not found or failed to parse in {songs_dir}")
        return None

    # Should ideally return parsed_check above if found and parsed successfully
    # This line is fallback if the loop structure is changed
    return parse_osu_file_internal(found_map_path)


# --- Replay Parsing ---
def parse_replay_file(replay_path):
    """Parses an .osr file and extracts relevant data."""
    try:
        print(f"Parsing replay: {os.path.basename(replay_path)}...")
        replay = Replay.from_path(replay_path)

        # Check if the game mode is Standard (Osu!)
        if replay.mode != GameMode.Osu: # Use GameMode.Osu
            print(f"Skipping non-standard replay: {replay.mode}")
            return None

        beatmap_hash = replay.beatmap_hash
        mods_enum = replay.mods
        replay_events = replay.replay_data

        print(f"  Beatmap Hash: {beatmap_hash}")
        print(f"  Mods: {mods_enum}")

        # --- CORRECTION: Initialize as an empty list ---
        input_actions = []
        # --- END CORRECTION ---

        current_time = 0
        last_key_state = 0
        relevant_keys_mask = Key.M1 | Key.M2 | Key.K1 | Key.K2

        for event in replay_events:
            # Skip the first two unusual frames osrparse might include
            # (These have unusual coordinates and often a zero or negative time_delta)
            # Adjust condition slightly based on observed osrparse behavior
            if event.x == 256 and event.y == -500 and event.time_delta <= 0 and current_time == 0:
                continue

            current_time += event.time_delta
            current_press_state = event.keys & relevant_keys_mask
            # Detect only the keys that were *just* pressed (transition from 0 to 1)
            pressed_now = current_press_state & ~last_key_state

            # Only record the timestamp when a relevant key is *pressed down*
            if pressed_now > 0:
                input_actions.append({'time': current_time, 'keys': pressed_now})

            last_key_state = current_press_state # Update the state for the next iteration

        print(f"  Found {len(input_actions)} input actions (key/mouse presses).")

        if not input_actions:
            print("Warning: No input actions found in replay data.")
            # Optionally return None or an empty dict if no actions is critical
            # return None

        return {
            'beatmap_hash': beatmap_hash,
            'mods': mods_enum,
            'input_actions': input_actions # Now this is a list
        }

    except Exception as e:
        # Log the full traceback for better debugging
        import traceback
        print(f"Error parsing replay file {os.path.basename(replay_path)}:")
        traceback.print_exc() # Prints the full stack trace
        return None

# --- Hit Window Calculation ---
def get_hit_window_ms(od, window_type='50', mods=0):
    """Calculates the hit window in milliseconds based on OD and mods."""
    if od is None: od = 5.0

    # Base hit windows formulas derived from osu! wiki/community info [4, 5]
    if window_type == '300': base_window = 79.5 - 6 * od
    elif window_type == '100': base_window = 139.5 - 8 * od
    else: base_window = 199.5 - 10 * od #[4]

    speed_multiplier = 1.0
    if Mod.DOUBLE_TIME in mods or Mod.NIGHTCORE in mods: speed_multiplier = 1.5 #[4]
    elif Mod.HALF_TIME in mods: speed_multiplier = 0.75 #[4]

    # Adjust window based on speed multiplier [4]
    return max(0, base_window / speed_multiplier)

# --- Correlation and Offset Calculation ---
def calculate_hit_offsets(replay_data, beatmap_data):
    """Correlates replay inputs with beatmap objects and calculates offsets."""
    if not replay_data or not beatmap_data or not replay_data.get('input_actions') or not beatmap_data.get('hit_objects'):
        print("Missing data for offset calculation.")
        return # Return empty list

    input_actions = replay_data['input_actions']
    hit_objects = beatmap_data['hit_objects']
    od = beatmap_data.get('od')
    mods = replay_data.get('mods', Mod.NO_MOD)

    if od is None:
        print("Warning: OD not found in beatmap data, defaulting to OD 5.")
        od = 5.0

    hit_offsets = ''
    last_input_index = 0
    # Use the widest window (50) for matching inputs to objects [4, 5]
    hit_window_50 = get_hit_window_ms(od, '50', mods)
    # print(f"Using Hit Window (±50ms): ±{hit_window_50:.2f} ms (OD={od}, Mods={mods})")

    speed_multiplier = 1.0
    if Mod.DOUBLE_TIME in mods or Mod.NIGHTCORE in mods: speed_multiplier = 1.5 #[4]
    elif Mod.HALF_TIME in mods: speed_multiplier = 0.75 #[4]

    object_index = -1
    for obj in hit_objects:
        object_index += 1
        obj_time = obj.get('time')
        obj_type = obj.get('type')

        if obj_time is None or obj_type is None: continue # Skip invalid objects

        # Check object type using bitmask [6]
        is_circle = (obj_type & 1)!= 0
        is_slider = (obj_type & 2)!= 0
        if not (is_circle or is_slider): continue # Only consider circles and slider starts

        min_time = obj_time - hit_window_50
        max_time = obj_time + hit_window_50
        found_action = None

        # Search for the first input action within the window
        for i in range(last_input_index, len(input_actions)):
            action = input_actions[i]
            action_time = action['time']
            if action_time > max_time: break # Passed the window
            if action_time >= min_time:
                 found_action = action
                 last_input_index = i + 1 # Optimize next search
                 break # Use first action found

        if found_action:
            raw_offset = found_action['time'] - obj_time
            # Scale offset based on mods [4, 7]
            scaled_offset = raw_offset / speed_multiplier
            hit_offsets.append(scaled_offset)
            # print(f"  Matched HO {object_index} (T={obj_time}) -> Action (T={found_action['time']}). Scaled Offset: {scaled_offset:.2f}")

    print(f"Calculated {len(hit_offsets)} hit offsets.")
    return hit_offsets

# --- Averaging ---
def calculate_average_offset(offsets):
    """Calculates the average of a list of hit offsets."""
    if not offsets:
        print("No valid hit offsets found.")
        return None
    try:
        average = statistics.mean(offsets)
        # print(f"Average Hit Offset: {average:.2f} ms")
        return average
    except statistics.StatisticsError:
         print("Error calculating average offset.")
         return None


# --- Display ---
def display_result(average_offset, replay_filename):
    """Displays the calculated average offset."""
    print("-" * 40)
    print(f"Analysis Complete for: {replay_filename}")
    if average_offset is None:
        print("  Could not calculate average offset.")
    else:
        offset_ms = average_offset
        if abs(offset_ms) < 0.5: # Threshold for centered
            timing = "Centered" #[8]
        elif offset_ms < 0:
            timing = "Early" #[8]
        else:
            timing = "Late" #[8]
        print(f"  Average Hit Offset: {offset_ms:+.2f} ms ({timing})")
    print("-" * 40)

# --- Main Analysis Function ---
def analyze_replay(replay_path, songs_dir):
    """Orchestrates the analysis of a single replay."""
    print(f"\n--- Starting Analysis for {os.path.basename(replay_path)} ---")
    replay_data = parse_replay_file(replay_path)
    if not replay_data:
        return # Error handled in parse_replay_file

    beatmap_data = find_and_parse_beatmap(replay_data['beatmap_hash'], songs_dir)
    if not beatmap_data:
        display_result(None, os.path.basename(replay_path)) # Display failure
        return # Error handled in find_and_parse_beatmap

    hit_offsets = calculate_hit_offsets(replay_data, beatmap_data)
    average_offset = calculate_average_offset(hit_offsets)
    display_result(average_offset, os.path.basename(replay_path))


# --- Watchdog Event Handler ---
class ReplayEventHandler(FileSystemEventHandler): #[9, 10, 11, 12]
    def __init__(self, songs_dir):
        self.songs_dir = songs_dir
        self.last_processed_time = 0
        self.processing_threshold = 2 # Only process files created within the last X seconds

    def on_created(self, event): #[9, 10, 12]
        if not event.is_directory and event.src_path.lower().endswith('.osr'):
            file_path = event.src_path
            try:
                time.sleep(0.5) # Wait for file write to complete
                current_time = time.time()
                file_mod_time = os.path.getmtime(file_path)

                # Check if file is recent and not already processed
                if file_mod_time > self.last_processed_time and (current_time - file_mod_time) < self.processing_threshold:
                     # print(f"Processing new replay: {os.path.basename(file_path)}")
                     self.last_processed_time = file_mod_time
                     analyze_replay(file_path, self.songs_dir) # Trigger analysis
                # else:
                     # print(f"Ignoring old or already processed file event: {os.path.basename(file_path)}")

            except FileNotFoundError:
                 print(f"Warning: File disappeared before processing: {os.path.basename(file_path)}")
            except Exception as e:
                print(f"Error during event handling for {os.path.basename(file_path)}: {e}")

# --- Main Execution ---
if __name__ == "__main__":
    print("osu! Average Hit Offset Analyzer")
    print("="*30)

    try:
        REPLAYS_DIR, SONGS_DIR = load_config()
        print(f"Replays Folder: {REPLAYS_DIR}")
        print(f"Songs Folder: {SONGS_DIR}")
    except (FileNotFoundError, NotADirectoryError, KeyError) as e:
        print(f"Configuration Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred during startup: {e}")
        sys.exit(1)

    event_handler = ReplayEventHandler(SONGS_DIR)
    observer = Observer() #[9, 10, 11, 12]
    observer.schedule(event_handler, REPLAYS_DIR, recursive=False) #[9, 10, 11, 12]
    observer.start() #[9, 10, 11, 12]

    print(f"\nMonitoring for new replays in: {REPLAYS_DIR}") #[9, 10, 11, 12]
    print("Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1) #[9, 10, 11, 12]
    except KeyboardInterrupt:
        observer.stop() #[9, 10, 11, 12]
        print("\nMonitoring stopped by user.")
    except Exception as e:
         print(f"\nAn unexpected error occurred during monitoring: {e}")
         observer.stop() # Ensure observer stops on error

    observer.join() #[9, 10, 11, 12]
    print("Application finished.")
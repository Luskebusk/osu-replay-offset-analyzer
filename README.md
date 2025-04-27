# osu! Average Hit Offset Analyzer

This script monitors your osu! Replays folder and automatically analyzes newly created standard mode replays to determine if you are hitting notes early or late on average.

## Features

* **Automatic Analysis:** Runs in the background and processes replays as soon as they are saved.
* **Fast Beatmap Lookup:** Uses your local `osu!.db` file for quick beatmap identification.
* **Average Offset Calculation:** Calculates the average timing error (in milliseconds) across all successfully hit circles and slider starts in the replay.
* **Tendency Indication:** Tells you if you were generally hitting EARLY, LATE, or ON TIME for that play.
* **Unstable Rate (UR):** Also calculates and displays the UR based on the hit offsets.

## Prerequisites

* Python 3.7 or newer ([https://www.python.org/](https://www.python.org/))
* `pip` (Python package installer, usually included with Python)
* Git (for cloning, optional if downloading manually)

## Setup Instructions

1.  **Get the Code:**
    * **Option A (Git):** Open a terminal or command prompt and run:
        ```bash
        git clone <repository_url> osu-offset-analyzer
        cd osu-offset-analyzer
        ```
        (Replace `<repository_url>` with the actual URL if you host this on GitHub/GitLab etc.)
    * **Option B (Manual):** Download the project files (especially `analyze_replay.py`) as a ZIP and extract them to a folder (e.g., `osu-offset-analyzer`). Open your terminal in that folder.

2.  **Create Virtual Environment (Recommended):**
    * It's highly recommended to use a virtual environment to keep dependencies separate.
    * Run:
        ```bash
        python -m venv venv
        ```
    * Activate the environment:
        * **Windows (Cmd/PowerShell):** `.\venv\Scripts\activate`
        * **Linux/macOS (Bash/Zsh):** `source venv/bin/activate`
    * You should see `(venv)` at the beginning of your terminal prompt.

3.  **Install Python Libraries:**
    * Run:
        ```bash
        pip install -r requirements.txt
        ```
        (This installs `osrparse`, `watchdog`, and `construct`)

4.  **Download Manual Parser Files:**
    * This project requires some helper files that are not available on PyPI.
    * **osu!.db Parser Files:**
        * Go to [https://github.com/KirkSuD/osu_db_kaitai_struct/tree/master/osu_db_construct](https://github.com/KirkSuD/osu_db_kaitai_struct/tree/master/osu_db_construct)
        * Download **all** `.py` files from this specific folder:
            * `adapters.py`
            * `osu_collection.py`
            * `osu_db.py`
            * `osu_scores.py`
            * `osu_types.py`
            * `path_util.py`
            * `playlist.py`
        * Place all these downloaded `.py` files directly into your project folder (where `analyze_replay.py` is).
    * **.osu Parser Files:**
        * Go to [https://github.com/Awlexus/python-osu-parser/tree/master](https://github.com/Awlexus/python-osu-parser/tree/master)
        * Download the following `.py` files:
            * `beatmapparser.py`
            * `slidercalc.py`
            * `curve.py`
        * Place these three downloaded `.py` files directly into your project folder.

5.  **Apply Fix to `curve.py`:**
    * Open the `curve.py` file you just downloaded.
    * Find all instances where `.length` is used on a list variable (check around lines 49, 50, 52).
    * Replace `.length` with `len()` (e.g., change `array.length` to `len(array)`).
    * Save the changes to `curve.py`.

## Configuration

1.  **Locate `config.ini`:** Find the `config.ini` file in the project folder. If it doesn't exist, run the script once (`python analyze_replay.py`), and it will create a default one for you before exiting.
2.  **Edit Paths:** Open `config.ini` with a text editor.
3.  **Update the paths** under the `[Paths]` section to match your osu! installation:
    * `OsuReplaysFolder`: Path to your osu! `Replays` directory.
    * `OsuSongsFolder`: Path to your osu! `Songs` directory.
    * `OsuDbPath`: Path to your `osu!.db` file (usually directly inside your main osu! folder).
    * *Use forward slashes (`/`) or raw strings (`r'C:\path...'`) for paths, especially on Windows.*
4.  **Save** the `config.ini` file.

## Running the Script

1.  **Activate Environment:** Make sure your virtual environment is activated (you should see `(venv)` in your terminal prompt).
2.  **Run:** Execute the script from your terminal:
    ```bash
    python analyze_replay.py
    ```
3.  **Initialization:** The script will first load your `osu!.db`. This might take 20-60 seconds depending on the size of your beatmap library. You will see a message when it's done.
4.  **Monitoring:** Once loaded, it will print `Monitoring for new replays...` and wait in the background.
5.  **Play osu!:** Go play an osu! standard map.
6.  **Analysis:** Shortly after you finish the map and the replay file (.osr) is saved, the script should detect it and automatically print the analysis results to the terminal, including the Average Hit Offset and the calculated Unstable Rate (UR).
7.  **Stop the Script:** Press `Ctrl+C` in the terminal where the script is running to stop the monitoring process.

## Output Interpretation

The script will output something like:

Result for YourName - Artist - Title [Diff] (Date) Osu.osr: Average Hit Offset: -5.12 ms (EARLY)

* **Negative Offset (`-`):** You are hitting, on average, *early*.
* **Positive Offset (`+`):** You are hitting, on average, *late*.
* **Value:** The number indicates *how many milliseconds* early or late you are on average.
* **(EARLY)/(LATE)/(ON TIME):** A quick summary based on the offset value.

Use this information to potentially adjust your global offset in osu! settings or just be aware of your timing tendencies.

## Troubleshooting

* **`ModuleNotFoundError`:** Ensure you have activated the virtual environment (`venv\Scripts\activate`) and installed requirements (`pip install -r requirements.txt`). Make sure all manually downloaded `.py` files are in the same directory as `analyze_replay.py`.
* **`FileNotFoundError` / `NotADirectoryError` on Startup:** Double-check the paths in your `config.ini` file. Make sure they are correct and accessible. Use forward slashes (`/`).
* **`StreamEndError` during `osu!.db` loading:** Your `osu!.db` might be corrupted or use a format slightly different from what the parser expects. Try closing osu!, deleting `osu!.db` (osu! will regenerate it, potentially losing some metadata like "Date Added"), and restarting osu! once before running the script again. *Use this as a last resort.*
* **Warning: `entry missing folder/filename`:** This means the script found the beatmap hash in your `osu!.db`, but the database entry itself is incomplete (missing the folder or .osu file name). This often happens with deleted/corrupted beatmaps. The script will safely skip analysis for these.
* **Script seems stuck on "Loading osu!.db":** This file can be large. Allow up to a minute or two for it to load the first time the script runs.

## Dependencies & Credits

* osrparse ([https://github.com/kszlim/osu-replay-parser](https://github.com/kszlim/osu-replay-parser))
* watchdog ([https://github.com/gorakhargosh/watchdog](https://github.com/gorakhargosh/watchdog))
* construct ([https://github.com/construct/construct](https://github.com/construct/construct))
* osu!db Parser components based on [https://github.com/KirkSuD/osu_db_kaitai_struct](https://github.com/KirkSuD/osu_db_kaitai_struct) (specifically the `osu_db_construct` part)
* .osu Parser components based on [https://github.com/Awlexus/python-osu-parser](https://github.com/Awlexus/python-osu-parser)
# osu! Hit Offset Analyzer

*Made mostly through AI, If you have any issues, feel free to open a Issue or send me a mail to my email on my profile*

This application monitors your osu! Replays folder and automatically analyzes newly created standard mode replays. It provides insights into your average hit timing (early/late), Unstable Rate (UR), and saves your play stats locally.

## Features

* **Automatic Analysis:** Runs in the background and processes replays as soon as they are saved.
* **GUI Interface:** Displays results and stats in a user-friendly window.
* **Instant Results:** Shows key metrics immediately after a play is analyzed.
* **Stats History:** Saves results to a local CSV file (`analysis_stats.csv`).
* **Grouped Stats View:** Displays historical plays grouped by map, highlighting your high score for each map.
* **Filtering & Sorting:** Allows filtering stats by map name and sorting by various columns.
* **Average Offset Calculation:** Calculates the average timing error (in milliseconds) across hit circles and slider starts.
* **Tendency Indication:** Tells you if you were generally hitting EARLY, LATE, or ON TIME.
* **Unstable Rate (UR):** Calculates and displays the UR based on the hit offsets.
* **Configurable Offset:** Allows manual adjustment of replay timing via `config.ini` for calibration.

## Installation (Windows Installer)

1.  **Download:** Go to the [Releases Page](https://github.com/Luskebusk/osu-replay-offset-analyzer/releases) on GitHub.
2.  Download the latest `OsuAnalyzerSetup.exe` file.
3.  **Run Installer:** Run the downloaded `OsuAnalyzerSetup.exe`. It will guide you through the installation process. Standard users may be prompted for administrator privileges if installing for all users (default). You can choose to install just for the current user if preferred.
4.  **Shortcuts:** The installer will typically create Start Menu and optional Desktop shortcuts.

## Configuration

1.  **First Run:** When you run the "Osu Replay Analyzer" for the first time (e.g., from the Start Menu shortcut), it will check for a configuration file.
2.  **Automatic Creation:** If the config file doesn't exist, the application will automatically create a default `config.ini` file in your user's local application data folder. A pop-up message will appear showing you the exact location, typically:
    `C:\Users\<YourUsername>\AppData\Local\OsuAnalyzer\config.ini`
3.  **Edit Paths:** Open this `config.ini` file with a text editor (like Notepad). You **must** update the paths under the `[Paths]` section to match your osu! installation:
    * `OsuReplaysFolder`: Full path to your osu! `Replays` directory (e.g., `C:/Users/YourUsername/AppData/Local/osu!/Replays`).
    * `OsuSongsFolder`: Full path to your osu! `Songs` directory (e.g., `C:/Users/YourUsername/AppData/Local/osu!/Songs`).
    * `OsuDbPath`: Full path to your `osu!.db` file (e.g., `C:/Users/YourUsername/AppData/Local/osu!/osu!.db`).
    * **Important:** Use forward slashes (`/`) or double backslashes (`\\`) for paths in the config file.
4.  **Edit Settings (Optional):** Under the `[Settings]` section:
    * `LogLevel`: Change to `DEBUG` for more detailed logs (written to `analyzer_debug.log` in the same folder as `config.ini`). Default is `INFO`.
    * `ReplayTimeOffsetMs`: Adjust this value (e.g., `-10`, `-15`, `+5`) if you find the analyzer consistently reports offsets that feel slightly off compared to your perceived timing. This helps calibrate the tool to your system. Default is `-10`.
5.  **Save** the `config.ini` file.
6.  **Restart:** Restart the "Osu Replay Analyzer" application after saving changes to `config.ini`.

## Running the Application

1.  **Launch:** Use the Start Menu or Desktop shortcut created by the installer to run "Osu Replay Analyzer".
2.  **Initialization:** The application window will not appear until it has first load your `osu!.db`. This might take 20-60 seconds depending on the size of your beatmap library.
3.  **Monitoring:** Once loaded, a window will show up.The status will change to "Monitoring...". The application is now waiting for new replay files.
4.  **Play osu!:** Go play an osu! standard map.
5.  **Analysis & Results:** Shortly after you finish the map and the replay file (.osr) is saved, the application should automatically:
    * Update the "Instant Results" tab with the analysis for that play.
    * Save the results to `analysis_stats.csv` (located in the same folder as `config.ini`).
    * Update the status back to "Monitoring...".
6.  **View Stats:** Click the "Stats History" button to view all saved plays, grouped by map. You can filter by map name and sort by columns. Your high score for each map (within the recorded plays) will be shown in bold.
7.  **Close:** Simply close the application window when you are finished. The monitoring process will stop automatically.

## Output Interpretation (Instant Results Tab)

* **Avg Offset:** The average timing error in milliseconds.
    * Negative (`-`): Hitting early on average.
    * Positive (`+`): Hitting late on average.
* **Tendency:** A quick summary (EARLY/LATE/ON TIME) based on the average offset.
* **UR:** Unstable Rate calculated from the standard deviation of hit offsets. Lower is generally better/more consistent.
* **Score/SR/Mods:** Information retrieved from the replay and database.

Use this information to potentially adjust your global offset in osu! or track your timing consistency.

## Troubleshooting

* **Application doesn't start / Closes immediately:**
    * Ensure you have correctly edited the paths in `config.ini` located in `%LOCALAPPDATA%\OsuAnalyzer`.
    * Check the `analyzer_debug.log` file (in the same folder as `config.ini`) for error messages. You may need to set `LogLevel = DEBUG` in `config.ini` to generate this log.
    * Your `osu!.db` might be corrupted. Try closing osu!, deleting `osu!.db` (osu! will regenerate it, potentially losing some metadata), and restarting osu! once before running the analyzer again. *Use this as a last resort.*
* **"Map not found" / "OD not found" Status:** The beatmap hash from the replay wasn't found in your `osu!.db`. This can happen if osu! hasn't processed the map yet or if the database is out of sync. Playing the map once in osu! usually fixes this.
* **Low "Matched Hits" Count:** The analyzer currently only processes circles and slider starts. Spinners, slider ends, and slider repeats are ignored for offset calculation.
* **Incorrect Avg Offset:** If the offset seems consistently wrong even after checking calibration (`ReplayTimeOffsetMs`), there might be an issue with the underlying parsers or timing data. Please open an issue on GitHub.

## Dependencies & Credits

* PyQt6 ([https://riverbankcomputing.com/software/pyqt/](https://riverbankcomputing.com/software/pyqt/))
* osrparse ([https://github.com/kszlim/osu-replay-parser](https://github.com/kszlim/osu-replay-parser))
* watchdog ([https://github.com/gorakhargosh/watchdog](https://github.com/gorakhargosh/watchdog))
* construct ([https://github.com/construct/construct](https://github.com/construct/construct))
* osu!db Parser components based on [https://github.com/KirkSuD/osu_db_kaitai_struct](https://github.com/KirkSuD/osu_db_kaitai_struct) (specifically the `osu_db_construct` part)
* .osu Parser components based on [https://github.com/Awlexus/python-osu-parser](https://github.com/Awlexus/python-osu-parser)

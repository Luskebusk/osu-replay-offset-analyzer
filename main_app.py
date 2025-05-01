import sys
import os
import csv
import configparser
import logging
import time # Added for sleep
script_dir = os.path.dirname(os.path.abspath(__file__))
icon_base_dir = os.path.join(script_dir, 'icons')
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QLabel, QStackedWidget, QGridLayout, QFrame, QScrollArea, QMenu, QCheckBox,
    QToolButton, QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit, 
    QComboBox, QSlider, QFileDialog, QMessageBox, QDockWidget, QTreeWidget, 
    QTreeWidgetItem, QSystemTrayIcon # <-- Re-added QSystemTrayIcon
)
from PyQt6.QtCore import (
    Qt, QSize, QUrl, QMargins, QDateTime, QThread, pyqtSignal, QTimer, 
    pyqtSlot, QCoreApplication, QLibraryInfo, QResource
)
from PyQt6.QtGui import (
    QIcon, QPainter, QDesktopServices, QFont, QColor, QAction, QPen, 
    QDoubleValidator, QIntValidator, QPixmap # <-- Added QAction
)
import random
from PyQt6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis, QScatterSeries
from collections import defaultdict

# --- Setup Logging (Moved Up) --- 
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- psutil Import (Optional) --- 
PSUTIL_AVAILABLE = False
try:
    import psutil
    PSUTIL_AVAILABLE = True
    logger.debug("psutil library found. osu! process monitoring enabled.")
except ImportError:
    logger.warning("psutil library not found. Install it (`pip install psutil`) to enable osu! process monitoring features.")

# --- Backend Imports ---
try:
    from backend import (
        AnalysisWorker, MonitorThread, load_config, save_settings, load_osu_database,
        get_user_data_dir, CONFIG_FILE, STATS_CSV_FILE, logger as backend_logger
    )
except ImportError as e:
    print(f"FATAL ERROR: Could not import backend components: {e}")
    sys.exit(1)

# --- Get base directory for icons --- 
script_dir = os.path.dirname(os.path.abspath(__file__))
icon_base_dir = os.path.join(script_dir, 'icons')

# === Osu! Process Monitor Thread ===
class OsuProcessMonitorThread(QThread):
    osu_running_status = pyqtSignal(bool) # Signal emits True if osu! is running, False otherwise

    def __init__(self, check_interval_sec=5):
        super().__init__()
        self.check_interval_sec = check_interval_sec
        self._is_running = False
        self.osu_was_running = None # Track previous state

    def run(self):
        if not PSUTIL_AVAILABLE:
            logger.warning("OsuProcessMonitorThread started but psutil is not available. Thread exiting.")
            return
            
        logger.info(f"Starting osu! process monitor (check interval: {self.check_interval_sec}s)")
        self._is_running = True
        self.osu_was_running = self.is_osu_running() # Initial check
        self.osu_running_status.emit(self.osu_was_running) # Emit initial status
        logger.info(f"Initial osu! status: {'Running' if self.osu_was_running else 'Not Running'}")

        while self._is_running:
            try:
                current_osu_status = self.is_osu_running()
                if current_osu_status != self.osu_was_running:
                    logger.info(f"osu! process status changed: {'Running' if current_osu_status else 'Not Running'}")
                    self.osu_running_status.emit(current_osu_status)
                    self.osu_was_running = current_osu_status
                else:
                    logger.debug(f"osu! process status unchanged ({'Running' if current_osu_status else 'Not Running'})")
                    
                # Wait for the next check interval
                # Use a loop with shorter sleeps to make stop() more responsive
                for _ in range(self.check_interval_sec * 5): # Check stop flag every 0.2s
                     if not self._is_running:
                          break
                     time.sleep(0.2)
                     
            except Exception as e:
                 logger.error(f"Error in OsuProcessMonitorThread loop: {e}", exc_info=True)
                 # Wait before retrying after an error
                 time.sleep(self.check_interval_sec)
                 
        logger.info("Osu! process monitor thread stopped.")

    def is_osu_running(self):
        """Checks if osu!.exe process is running."""
        if not PSUTIL_AVAILABLE:
             return False
        try:
             for proc in psutil.process_iter(['name']):
                  if proc.info['name'] and proc.info['name'].lower() == 'osu!.exe':
                       return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            # Handle potential errors during process iteration
            pass
        except Exception as e:
             logger.warning(f"Error checking for osu! process: {e}")
        return False

    def stop(self):
        logger.info("Requesting osu! process monitor thread stop...")
        self._is_running = False

class MainWindow(QMainWindow):
    config_updated = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("osu! Replay Analyzer")
        # Set window icon (taskbar, title bar) to analyzer.png for Windows compatibility
        window_icon_path = os.path.join(icon_base_dir, 'analyzer.png') 
        if not os.path.exists(window_icon_path):
             logger.warning(f"Window icon 'analyzer.png' not found at {window_icon_path}. Falling back to analyzer.svg.")
             window_icon_path = os.path.join(icon_base_dir, 'analyzer.svg') # Fallback to SVG

        if os.path.exists(window_icon_path):
             self.setWindowIcon(QIcon(window_icon_path))
        else:
             logger.error(f"Window icon ('analyzer.png' or 'analyzer.svg') not found. No icon will be set.")
             
        self.resize(1200, 800)
        
        # --- Define History Headers Consistently --- 
        self.history_headers = ['Timestamp', 'MapName', 'Mods', 'AvgOffsetMs', 'UR', 'MatchedHits', 'Score', 'StarRating'] # Reverted back to 'StarRating'
        
        # --- Load History Data (needed for bottom bar label) --- 
        self.history_data = self.load_history_from_csv()
        
        # --- Backend related initializations ---
        self.config_data = {}
        self.osu_db = None
        self.analysis_worker = None
        self.analysis_thread = None
        self.monitor_thread = None
        self.osu_process_monitor_thread = None # Initialize osu monitor
        # Store last analysis results for graph metrics
        self.last_analysis_avg_offset = None
        self.last_analysis_ur = None
        self.last_analysis_hit_offsets = []
        # self.load_initial_config() # MOVED: Load config after basic UI elements exist

        # Set dark mode
        self.setProperty("darkMode", True)
        
        # --- Load Stylesheet (as before) ---
        self.load_stylesheet()

        # --- Create Content Area (Central Widget) with VBox layout --- 
        content_area = QWidget()
        content_area.setObjectName("contentArea")
        content_layout = QVBoxLayout(content_area) # Main content uses VBox
        content_layout.setContentsMargins(0, 0, 0, 0) # No margins for the main content area itself
        content_layout.setSpacing(0)
        self.setCentralWidget(content_area)

        # --- Stacked Widget (goes into content_layout first) --- 
        self.stack = QStackedWidget()
        content_layout.addWidget(self.stack, 1) # Stack takes vertical stretch

        # --- Custom Bottom Bar (goes into content_layout second) --- 
        bottom_bar = QWidget()
        bottom_bar.setObjectName("statusBarReplacement") # Use object name for styling
        bottom_bar.setFixedHeight(24) # Give it a fixed height
        bottom_bar_layout = QHBoxLayout(bottom_bar)
        bottom_bar_layout.setContentsMargins(12, 0, 12, 0) # Horizontal padding
        bottom_bar_layout.setSpacing(10)

        # Create and add labels to bottom bar layout
        self.entry_count_label = QLabel(f"Entries: {len(self.history_data)}") # Changed text
        self.entry_count_label.setObjectName("historyStatsLabel")
        bottom_bar_layout.addWidget(self.entry_count_label) # Left

        bottom_bar_layout.addStretch()

        self.statusLabel = QLabel("Initializing...") # Status label
        self.statusLabel.setObjectName("statusLabel")
        bottom_bar_layout.addWidget(self.statusLabel) # Right
        
        content_layout.addWidget(bottom_bar) # Add bottom bar below stack

        # --- Create Sidebar Content (as before) --- 
        self.sidebar = QWidget() # Content for the dock
        self.sidebar.setObjectName("sidebar") # Set object name for QSS
        # self.sidebar.setFixedWidth(64) # Width set on the dock widget now
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 16, 0, 16)
        sidebar_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        sidebar_layout.setSpacing(16)
        
        # Create sidebar buttons
        self.analyzer_btn = self.create_nav_button("analyzerNAV", "Analyzer") # Use analyzerNAV.svg
        sidebar_layout.addWidget(self.analyzer_btn)
        
        self.history_btn = self.create_nav_button("history", "History")
        sidebar_layout.addWidget(self.history_btn)
        
        self.settings_btn = self.create_nav_button("settings", "Settings")
        sidebar_layout.addWidget(self.settings_btn)
        
        self.info_btn = self.create_nav_button("info", "Information")
        sidebar_layout.addWidget(self.info_btn)
        
        sidebar_layout.addStretch()
        
        github_btn = QPushButton() # ... (github button setup as before) ...
        icon_file = "github.svg"
        icon_path = os.path.join(icon_base_dir, icon_file)
        if os.path.exists(icon_path):
            github_btn.setIcon(QIcon(icon_path))
            logger.debug(f"Attempting to load GitHub icon from: {icon_path}")
            if github_btn.icon().isNull():
                logger.warning(f"GitHub icon file exists but failed to load or is invalid: {icon_path}")
                github_btn.setText("GH")
        else:
            logger.warning(f"GitHub icon file not found at: {icon_path}")
            github_btn.setText("GH")
        github_btn.setIconSize(QSize(24, 24))
        github_btn.setFixedSize(48, 48) # Fixed syntax
        github_btn.setObjectName("GitHubButton")
        github_btn.setToolTip("View on GitHub")
        github_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/Luskebusk/osu-replay-offset-analyzer")))
        sidebar_layout.addWidget(github_btn)
        # main_layout.addWidget(self.sidebar) # Don't add to main layout yet

        # --- Create and Add Sidebar Dock Widget --- 
        sidebar_dock = QDockWidget("Navigation", self)
        sidebar_dock.setObjectName("sidebarDock")
        sidebar_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        sidebar_dock.setWidget(self.sidebar) # Put the sidebar content inside the dock
        sidebar_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures) # Remove title bar and close/float buttons
        sidebar_dock.setTitleBarWidget(QWidget()) # Explicitly remove title bar
        sidebar_dock.setFixedWidth(64) # Set fixed width on the dock itself
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, sidebar_dock)

        # --- Load Config BEFORE Creating Pages AND Tray Icon --- 
        self.load_initial_config() # Moved up slightly

        # --- Create System Tray Icon --- 
        self.create_tray_icon()

        # --- Add pages to stack --- 
        logger.info("Creating analyzer page...")
        analyzer_page = self.create_analyzer_page()
        logger.info("Analyzer page created.")
        logger.info("Creating history page...")
        history_page = self.create_history_page() # Create history page normally
        logger.info("History page created.")
        logger.info("Creating settings page...")
        settings_page = self.create_settings_page()
        logger.info("Settings page created.")
        logger.info("Creating info page...")
        info_page = self.create_info_page()
        logger.info("Info page created.")
        
        logger.info("Adding pages to stack widget...")
        logger.info("Adding analyzer_page...") # Changed to INFO
        self.stack.addWidget(analyzer_page)
        logger.info("Adding history_page...") # Changed to INFO
        self.stack.addWidget(history_page)
        logger.info("Adding settings_page...") # Changed to INFO
        self.stack.addWidget(settings_page)
        logger.info("Adding info_page...") # Changed to INFO
        self.stack.addWidget(info_page)
        logger.info("Pages added to stack widget.") # Keep as INFO
        
        # Add widgets to main layout
        self.setCentralWidget(content_area)
        
        # Connect buttons
        self.analyzer_btn.clicked.connect(lambda: self.switch_page(0))
        self.history_btn.clicked.connect(lambda: self.switch_page(1))
        self.settings_btn.clicked.connect(lambda: self.switch_page(2))
        self.info_btn.clicked.connect(lambda: self.switch_page(3))
        
        # Connect config update signal
        self.config_updated.connect(self.update_ui_from_config)

        # --- Attempt to load database ---
        self.attempt_load_database()

        # --- Start monitoring if enabled (Replay Monitor) --- 
        self.maybe_start_monitor()

        # --- Start osu! Process Monitor if enabled --- 
        self.maybe_start_osu_process_monitor() # New method call

        # Set initial page
        self.switch_page(0)
        # Populate settings page initially after it's created
        self.update_ui_from_config(self.config_data)
        
        # --- Handle Launch Minimized (after UI and tray are set up) --- 
        # This check now happens in the __main__ block before window.show()
    
    def create_nav_button(self, icon_name, tooltip):
        button = QPushButton()
        # Use absolute paths relative to script
        icon_file = f"{icon_name}.svg"
        icon_path = os.path.join(icon_base_dir, icon_file)

        # Check if the file exists and try to load the icon
        if os.path.exists(icon_path):
            button.setIcon(QIcon(icon_path))
            logger.debug(f"Attempting to load nav icon from: {icon_path}")
            # Check if loading failed even though the file exists
            if button.icon().isNull():
                logger.warning(f"Nav icon file exists but failed to load or is invalid: {icon_path}")
                button.setText(icon_name[0].upper()) # Fallback text
        else:
            # File doesn't exist
            logger.warning(f"Nav icon file not found at: {icon_path}")
            button.setText(icon_name[0].upper()) # Fallback text

        # Store absolute path for potential use with QSS or other logic
        button.setProperty("iconPath", icon_path)
        # Removed activeIconPath property

        button.setIconSize(QSize(24, 24))
        button.setFixedSize(48, 48)
        button.setToolTip(tooltip)
        button.setCheckable(True)
        button.setObjectName("navButton")
        return button
    
    def switch_page(self, index):
        self.stack.setCurrentIndex(index)
        buttons = [self.analyzer_btn, self.history_btn, self.settings_btn, self.info_btn]
        for i, btn in enumerate(buttons):
            btn.setProperty("checked", i == index)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            
        # --- REMOVED Margin Adjustment Code ---
        # Adjust content area margins based on the page
        # page_content_layout = self.centralWidget().layout() # Get the layout of the central widget (content_area)
        # if page_content_layout: # Check if layout exists
        #     if index == 1:  # History page
        #         page_content_layout.setContentsMargins(12, 12, 12, 12)  # Smaller margins for history
        #     else:
        #         page_content_layout.setContentsMargins(24, 24, 24, 24)  # Default margins
        # else:
        #     logger.warning("Could not get central widget layout to adjust margins.")
    
    def create_analyzer_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24) # Set default margins for this page
        layout.setSpacing(12)  # Reduced spacing between elements
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        # Song title
        song_title = QLabel("Song")
        song_title.setObjectName("songTitle")
        song_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(song_title)
        
        # Stats grid - compact layout
        stats_container = QWidget()
        stats_container.setObjectName("statsContainer")
        stats_grid = QGridLayout(stats_container)
        stats_grid.setSpacing(12)  # Reduced spacing between cards
        stats_grid.setContentsMargins(0, 0, 0, 0)  # Remove margins
        
        # Create stat cards
        self.stats = [
            ("Tendency", "N/A", "#FF5D9E"),
            ("Average Hit Offset", "N/A", "#50C4ED"),
            ("Score", "N/A", "#FFC857"),
            ("Unstable Rate", "N/A", "#70E4EF"),
            ("Matched Hits", "N/A", "#A5FF9E"),
            ("Star Rating", "N/A", "#CF9EFF")
        ]
        
        self.stat_cards = {} # Store card widgets (frame, title_label, value_label)
        for i, (stat_name, stat_value, color) in enumerate(self.stats):
            card_widgets = self.create_stat_card(stat_name, stat_value, color) # Returns dict of widgets
            row = i // 2
            col = i % 2
            # Correctly add the frame widget, not the whole dict
            stats_grid.addWidget(card_widgets["frame"], row, col)
            self.stat_cards[stat_name] = card_widgets # Store the dict {frame, title_label, value_label}
        
        layout.addWidget(stats_container)
        
        # Graph section - more space for this
        graph_section = QWidget()
        graph_layout = QVBoxLayout(graph_section)
        graph_layout.setContentsMargins(0, 16, 0, 0)  # Add spacing at top only
        graph_layout.setSpacing(6)  # Reduce spacing in graph section
        
        # Header with title and dropdown
        header_container = QWidget()
        header_layout = QHBoxLayout(header_container)
        header_layout.setContentsMargins(0, 0, 0, 6)  # Reduced bottom margin
        header_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Create dropdown button with menu
        dropdown_button = QToolButton()
        dropdown_button.setText("Filters")
        dropdown_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        dropdown_button.setObjectName("dropdownButton")
        dropdown_button.setCursor(Qt.CursorShape.PointingHandCursor)
        dropdown_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        
        dropdown_menu = QMenu(dropdown_button)
        dropdown_menu.setObjectName("dropdownMenu")
        
        # Add checkboxes for different metrics
        self.graph_options = {}
        graph_metrics = ["Tendency", "Average Hit Offset", "Unstable Rate", "Matched Hits"]
        
        for i, metric in enumerate(graph_metrics):
            checkbox = QCheckBox(metric)
            checkbox.setObjectName(f"checkbox_{metric.replace(' ', '_')}")
            
            # Create action to hold the checkbox
            action = QAction(metric, dropdown_menu)
            action.setCheckable(True)
            
            # Find matching color from stats
            for name, _, color in self.stats:
                if name == metric:
                    action.setData(color)
                    break
            
            # Connect action toggled signal
            action.toggled.connect(lambda checked, m=metric: self.toggle_graph_metric(m, checked))
            
            dropdown_menu.addAction(action)
            self.graph_options[metric] = action
        
        dropdown_button.setMenu(dropdown_menu)
        header_layout.addWidget(dropdown_button)
        
        graph_layout.addWidget(header_container)
        
        # Center container for indicators
        self.center_container = QWidget()
        center_layout = QHBoxLayout(self.center_container)
        center_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_layout.setContentsMargins(0, 0, 0, 4)  # Very small bottom margin
        
        graph_layout.addWidget(self.center_container)
        
        # Graph container with more height
        graph_container = QWidget()
        graph_container.setObjectName("graphContainer")
        graph_container.setMinimumHeight(240)  # Ensure graph has sufficient height
        graph_container_layout = QVBoxLayout(graph_container)
        graph_container_layout.setContentsMargins(8, 8, 8, 8)  # Reduced padding
        
        # Create chart for hit error distribution
        self.chart = QChart()
        self.chart.setBackgroundVisible(False)
        self.chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)
        self.chart.legend().setVisible(False)
        self.chart.setMargins(QMargins(0, 0, 0, 0))  # Remove chart margins
        
        # Create hit error series (now empty initially)
        self.hit_error_series = QLineSeries()
        self.hit_error_series.setColor(QColor("#50C4ED"))  # Blue color
        
        # REMOVED sample data generation
        # for i in range(-20, 21):
        #     y = ...
        #     self.hit_error_series.append(i, y)
            
        self.chart.addSeries(self.hit_error_series)
        
        # Set up axes (keep initial range, update later in update_analyzer_graph)
        self.axis_x = QValueAxis()
        self.axis_x.setRange(-20, 20)
        self.axis_x.setTitleText("Hit Error (ms)")
        self.axis_x.setLabelFormat("%d")
        self.axis_x.setLabelsColor(Qt.GlobalColor.white)
        self.axis_x.setTitleBrush(Qt.GlobalColor.white)
        self.axis_x.setGridLineVisible(True)
        self.axis_x.setMinorGridLineVisible(False)
        self.axis_x.setGridLineColor(QColor("#333344"))
        
        self.axis_y = QValueAxis()
        self.axis_y.setRange(0, 10)
        self.axis_y.setLabelsVisible(False)
        self.axis_y.setGridLineVisible(False)
        
        self.chart.addAxis(self.axis_x, Qt.AlignmentFlag.AlignBottom)
        self.chart.addAxis(self.axis_y, Qt.AlignmentFlag.AlignLeft)
        self.hit_error_series.attachAxis(self.axis_x)
        self.hit_error_series.attachAxis(self.axis_y)
        
        # Additional series for metrics (initially empty)
        self.metric_series = {}
        self.metric_indicators = {}
        
        # Add to chart view
        self.chart_view = QChartView(self.chart)
        self.chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.chart_view.setObjectName("chartView")
        graph_container_layout.addWidget(self.chart_view)
        
        graph_layout.addWidget(graph_container)
        layout.addWidget(graph_section, 1)  # Give graph section a stretch factor of the graph
        
        # Add a small spacer (just enough for the status bar)
        spacer = QWidget()
        spacer.setFixedHeight(10)
        layout.addWidget(spacer)
        
        return page
        
    def create_stat_card(self, title, value, color):
        card = QFrame()
        card.setObjectName("statCard")
        card.setProperty("cardColor", color)
        card.setStyleSheet(f"#statCard[cardColor='{color}'] {{ border-top: 3px solid {color}; }}")
        
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)  # Reduced padding
        layout.setSpacing(4)  # Reduced spacing
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        title_label = QLabel(title)
        title_label.setObjectName("statTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        value_label = QLabel(value)
        value_label.setObjectName("statValue")
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value_label.setAutoFillBackground(False)
        
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        return card
    
    def toggle_graph_metric(self, metric, enabled):
        # Get color for this metric from the action's stored data
        color_qcolor = None
        for action in self.graph_options.values():
            if action.text() == metric:
                color_data = action.data() # Should be the hex string like '#FF5D9E'
                if isinstance(color_data, str):
                    color_qcolor = QColor(color_data)
                break
        
        if color_qcolor is None:
            logger.warning(f"Could not find valid color data for metric: {metric}")
            return
            
        # Get the maximum Y value from the main hit error series for scaling vertical lines
        max_y = self.axis_y.max() if self.axis_y and self.axis_y.max() > 0 else 1.0

        # Remove existing series and indicator first (simplifies logic)
        if metric in self.metric_series:
            self.chart.removeSeries(self.metric_series[metric])
            # Also remove any extra series (like the second UR line)
            if "extra_series" in self.metric_series and metric in self.metric_series["extra_series"]:
                self.chart.removeSeries(self.metric_series["extra_series"][metric])
                del self.metric_series["extra_series"][metric]
            del self.metric_series[metric]
            
        if metric in self.metric_indicators:
            indicator = self.metric_indicators[metric]
            indicator.setParent(None)
            indicator.deleteLater()
            del self.metric_indicators[metric]
            
        # If enabling, create and add the new series based on stored data
        if enabled:
            series = None
            extra_series = None # For UR right line
            
            # --- Average Hit Offset / Tendency ---
            if metric == "Average Hit Offset" or metric == "Tendency":
                if self.last_analysis_avg_offset is not None:
                    avg_offset = self.last_analysis_avg_offset
                    series = QLineSeries()
                    series.setColor(color_qcolor)
                    # Use a slightly different pen style for Tendency vs Avg Offset if desired
                    pen_style = Qt.PenStyle.SolidLine if metric == "Average Hit Offset" else Qt.PenStyle.DotLine
                    pen_width = 2
                    series.setPen(QPen(color_qcolor, pen_width, pen_style))
                    series.append(avg_offset, 0)
                    series.append(avg_offset, max_y) # Draw line up to max Y of histogram
                    logger.debug(f"Drawing '{metric}' line at offset: {avg_offset:.2f}")
                else:
                    logger.warning(f"Cannot draw '{metric}': No average offset data available.")

            # --- Unstable Rate ---
            elif metric == "Unstable Rate":
                if self.last_analysis_ur is not None and self.last_analysis_avg_offset is not None:
                    avg_offset = self.last_analysis_avg_offset
                    stdev = self.last_analysis_ur / 10.0 # UR = stdev * 10
                    left_bound = avg_offset - stdev
                    right_bound = avg_offset + stdev
                    
                    # Left boundary line
                    series = QLineSeries()
                    series.setColor(color_qcolor)
                    series.setPen(QPen(color_qcolor, 2, Qt.PenStyle.DashLine))
                    series.append(left_bound, 0)
                    series.append(left_bound, max_y)
                    
                    # Right boundary line (extra series)
                    extra_series = QLineSeries()
                    extra_series.setColor(color_qcolor)
                    extra_series.setPen(QPen(color_qcolor, 2, Qt.PenStyle.DashLine))
                    extra_series.append(right_bound, 0)
                    extra_series.append(right_bound, max_y)
                    logger.debug(f"Drawing UR lines at: {left_bound:.2f} and {right_bound:.2f} (Avg: {avg_offset:.2f}, UR: {self.last_analysis_ur:.2f})")
                else:
                     logger.warning("Cannot draw 'Unstable Rate': No UR or average offset data available.")

            # --- Matched Hits ---
            elif metric == "Matched Hits":
                if self.last_analysis_hit_offsets:
                    series = QScatterSeries()
                    series.setColor(color_qcolor)
                    series.setMarkerSize(6)
                    # Use a fixed Y value in the middle of the graph for scatter points
                    mid_y = max_y / 2.0 
                    for offset in self.last_analysis_hit_offsets:
                         series.append(offset, mid_y + random.uniform(-max_y*0.1, max_y*0.1)) # Small random Y variation
                    logger.debug(f"Drawing 'Matched Hits' scatter plot with {len(self.last_analysis_hit_offsets)} points.")
                else:
                     logger.warning("Cannot draw 'Matched Hits': No hit offset data available.")

            # Add the successfully created series (if any)
            if series:
                self.chart.addSeries(series)
                series.attachAxis(self.axis_x)
                series.attachAxis(self.axis_y)
                self.metric_series[metric] = series

            if extra_series: # For UR
                self.chart.addSeries(extra_series)
                extra_series.attachAxis(self.axis_x)
                extra_series.attachAxis(self.axis_y)
                # Store extra series separately
                if "extra_series" not in self.metric_series:
                    self.metric_series["extra_series"] = {}
                self.metric_series["extra_series"][metric] = extra_series

            # Create and add indicator label only if series was actually created
            if series or extra_series:
                indicator = QLabel(metric)
                indicator.setObjectName("metricIndicator")
                # Use the original hex string for style sheet
                hex_color = color_qcolor.name() 
                indicator.setStyleSheet(f"#metricIndicator {{ background-color: {hex_color}; color: black; padding: 1px 4px; border-radius: 3px; }}")
                indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.center_container.layout().addWidget(indicator)
                self.metric_indicators[metric] = indicator

    def create_info_page(self):
        page = QWidget()
        page.setObjectName("infoPage") # Add object name for potential page-specific styling
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16) # Slightly reduced spacing between elements

        title = QLabel("Application Information") # More descriptive title
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        # --- Scroll Area for Content --- 
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("infoScroll")
        scroll.setFrameShape(QFrame.Shape.NoFrame) # Cleaner look

        scroll_content = QWidget()
        scroll_content.setObjectName("infoScrollContent")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(20) # Increased spacing between sections
        scroll_layout.setContentsMargins(5, 5, 15, 5) # Ensure right margin for scrollbar

        # --- Helper Function to Create Sections (Reduces repetition) ---
        def create_info_section(section_title, section_content, is_html=False):
            section_frame = QFrame()
            section_frame.setObjectName("infoSection") # Use object name for styling
            section_layout = QVBoxLayout(section_frame)
            section_layout.setSpacing(8)

            heading = QLabel(section_title)
            heading.setObjectName("infoHeading")
            section_layout.addWidget(heading)
            
            # Add separator line
            line = QFrame()
            line.setFrameShape(QFrame.Shape.HLine)
            line.setFrameShadow(QFrame.Shadow.Sunken)
            line.setObjectName("separator") # Use common separator style
            section_layout.addWidget(line)

            content_label = QLabel(section_content)
            content_label.setObjectName("infoContent")
            content_label.setWordWrap(True)
            content_label.setTextFormat(Qt.TextFormat.RichText if is_html else Qt.TextFormat.PlainText)
            content_label.setOpenExternalLinks(True) # Allow opening links in HTML
            section_layout.addWidget(content_label)

            return section_frame

        # --- Add Information Sections using the helper --- 

        # About Section
        about_text = ("This application automatically analyzes your osu! standard replays (.osr files) "
                      "to provide insights into your timing consistency and accuracy. It runs in the background, "
                      "monitors your Replays folder, processes new replays, and displays key performance metrics.")
        scroll_layout.addWidget(create_info_section("About This Analyzer", about_text))

        # Features Section (using HTML for bullet points)
        features_html = ("<ul>"
                         "<li><b>Automatic Monitoring & Analysis:</b> Detects and analyzes new replays saved in your configured osu! Replays folder.</li>"
                         "<li><b>Key Metrics Display:</b> Shows Average Hit Offset, Unstable Rate (UR), Tendency (Early/Late/On Time), Matched Hits, Score, and Star Rating.</li>"
                         "<li><b>Hit Error Distribution Graph:</b> Visualizes the distribution of your hit timing errors.</li>"
                         "<li><b>History Tracking:</b> Saves analysis results to a local CSV file (<code>analysis_stats.csv</code>) and displays them in the History tab with grouping and sorting.</li>"
                         "<li><b>System Tray Integration:</b> Option to minimize to tray and receive notifications.</li>"
                         "<li><b>osu! Process Integration (Optional):</b> Can automatically start/stop monitoring when osu! starts/stops (requires <code>psutil</code>).</li>"
                         "</ul>")
        scroll_layout.addWidget(create_info_section("Core Features", features_html, is_html=True))

        # Understanding Stats Section (using HTML)
        stats_html = ("<ul>"
                      "<li><b>Tendency:</b> A quick summary of whether you generally hit <b>EARLY</b> (avg offset &lt; -2ms), <b>LATE</b> (avg offset &gt; +2ms), or <b>ON TIME</b>.</li>"
                      "<li><b>Average Hit Offset:</b> Your average timing error in milliseconds (ms). Negative (-) means early, Positive (+) means late. Aim for closer to zero.</li>"
                      "<li><b>Unstable Rate (UR):</b> A measure of timing consistency (Standard Deviation of hit offsets * 10). Lower UR means more consistent timing.</li>"
                      "<li><b>Matched Hits:</b> The number of hit circles/slider heads successfully correlated between the replay and the beatmap data.</li>"
                      "<li><b>Star Rating (SR):</b> The difficulty rating of the beatmap, retrieved from the osu! database or .osu file.</li>"
                      "<li><b>Hit Error Graph:</b> Shows how many hits occurred at different timing offsets. The peak shows your most common timing error, and the spread relates to your UR.</li>"
                      "</ul>")
        scroll_layout.addWidget(create_info_section("Understanding the Metrics", stats_html, is_html=True))

        # Troubleshooting / Tips Section
        tips_html = ("<ul>"
                     "<li><b>Configuration:</b> Ensure all paths are set correctly in the Settings tab, especially the Replays folder and osu!.db path.</li>"
                     "<li><b>Map Not Found:</b> If a map isn't found, ensure your osu!.db is up-to-date or that the map exists in your Songs folder.</li>"
                     "<li><b>Analysis Errors:</b> Errors can occur with corrupted replays, very old beatmaps, or non-standard game modes. Check logs (enable DEBUG in settings) for details.</li>"
                     "<li><b>Incorrect Offset/UR:</b> Ensure the 'Replay Time Offset (ms)' setting is appropriate for your setup (often around -8ms, but varies). Default is -8.</li>"
                     "<li><b>Start/Stop with osu!:</b> This feature requires the <code>psutil</code> Python library (<code>pip install psutil</code>) and might not work reliably on all systems.</li>"
                     "</ul>")
        scroll_layout.addWidget(create_info_section("Troubleshooting & Tips", tips_html, is_html=True))

        scroll_layout.addStretch() # Push content upwards
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll) # Add scroll area to main page layout

        return page

    def create_history_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12) # Set smaller margins for this page
        layout.setSpacing(10)

        # --- Filter/Search and Sort Bar --- 
        controls_container = QWidget()
        controls_layout = QHBoxLayout(controls_container)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(8)

        # Search Label and Input
        controls_layout.addWidget(QLabel("Search:")) # Changed label
        self.history_filter_input = QLineEdit()
        self.history_filter_input.setPlaceholderText("Search table content...") # Changed placeholder
        self.history_filter_input.setObjectName("searchInput")
        self.history_filter_input.textChanged.connect(self.filter_history)
        controls_layout.addWidget(self.history_filter_input)

        # Sort ComboBox
        controls_layout.addWidget(QLabel("Sort By:"))
        self.history_sort_combo = QComboBox()
        self.history_sort_combo.setObjectName("sortComboBox")
        self.history_sort_combo.setMinimumWidth(150) # Give it some space
        # Populate sort options (Value: (column_index, sort_order)) - Use header index BEFORE removing ReplayFile
        # Original Headers: ['Timestamp', 'MapName', 'Mods', 'AvgOffsetMs', 'UR', 'MatchedHits', 'Score', 'StarRating', 'ReplayFile']
        sort_options = {
            "Date (Newest First)": (0, Qt.SortOrder.DescendingOrder),
            "Date (Oldest First)": (0, Qt.SortOrder.AscendingOrder),
            "Map Name (A-Z)": (1, Qt.SortOrder.AscendingOrder),
            "Map Name (Z-A)": (1, Qt.SortOrder.DescendingOrder),
            "Avg Offset (Lowest)": (3, Qt.SortOrder.AscendingOrder),
            "Avg Offset (Highest)": (3, Qt.SortOrder.DescendingOrder),
            "UR (Lowest)": (4, Qt.SortOrder.AscendingOrder),
            "UR (Highest)": (4, Qt.SortOrder.DescendingOrder),
            "Matched Hits (Lowest)": (5, Qt.SortOrder.AscendingOrder),
            "Matched Hits (Highest)": (5, Qt.SortOrder.DescendingOrder),
            "Score (Lowest)": (6, Qt.SortOrder.AscendingOrder),
            "Score (Highest)": (6, Qt.SortOrder.DescendingOrder),
            "Star Rating (Lowest)": (7, Qt.SortOrder.AscendingOrder),
            "Star Rating (Highest)": (7, Qt.SortOrder.DescendingOrder),
        }
        for text in sort_options:
            self.history_sort_combo.addItem(text, sort_options[text]) # Store tuple as item data
        
        self.history_sort_combo.currentIndexChanged.connect(self.filter_history) # Trigger sort/filter on change
        controls_layout.addWidget(self.history_sort_combo)

        # Removed Export/Import/Clear buttons
        # Removed Entry Count Label (will be moved to status bar)

        controls_layout.addStretch()
        layout.addWidget(controls_container)

        # --- History Tree (Changed from Table) --- 
        self.history_tree = QTreeWidget()
        self.history_tree.setObjectName("historyTree")
        self.history_tree.setAlternatingRowColors(True)
        self.history_tree.setRootIsDecorated(True)
        self.history_tree.setSortingEnabled(False)  # Disable sorting by clicking headers
        self.history_tree.setAnimated(True)
        self.history_tree.setHeaderLabels(self.history_headers)

        # Set column resize modes
        header = self.history_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # Timestamp
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)            # MapName (Stretch) - Restored
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # Mods
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # AvgOffsetMs
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # UR
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)  # MatchedHits
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)  # Score
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)  # StarRating - Back to ResizeToContents
        
        # Ensure the last section doesn't automatically stretch
        header.setStretchLastSection(False)

        layout.addWidget(self.history_tree)

        # Create the entry count label here but don't add it to this layout
        self.entry_count_label = QLabel(f"History Entries: {len(self.history_data)}")
        self.entry_count_label.setObjectName("historyStatsLabel")

        # Initial population
        self.populate_history_tree() # Call renamed function

        return page

    def populate_history_tree(self, filter_text=None): # Renamed method
        """Populates the history tree using self.history_data, applying filter, sort, and grouping."""
        # --- REMOVED redundant update of entry count label --- 

        if filter_text is None:
             filter_text = self.history_filter_input.text() if hasattr(self, 'history_filter_input') else ""

        if not hasattr(self, 'history_tree') or not hasattr(self, 'history_data') or not hasattr(self, 'history_sort_combo'):
             logger.error("Cannot populate history tree: tree, data, or sort combo missing.")
             return

        self.history_tree.setSortingEnabled(False) # Disable sorting during population
        self.history_tree.clear() # Clear existing items before populating
        self.history_tree.setRootIsDecorated(True) # Show expand arrows

        # --- Get Sort Criteria from ComboBox --- 
        sort_data = self.history_sort_combo.currentData()
        if sort_data and isinstance(sort_data, tuple) and len(sort_data) == 2:
             sort_col, sort_order = sort_data
        else:
             sort_col, sort_order = (0, Qt.SortOrder.DescendingOrder) # Default: Date Descending
             logger.warning("Could not read sort criteria from combo box, using default.")

        # --- Filter and Sort Data (Initial flat list) --- 
        filtered_sorted_data = self.filter_and_sort_data(filter_text, sort_col, sort_order)

        # --- Group Data by Map Name --- 
        grouped_data = defaultdict(list)
        for entry in filtered_sorted_data:
            # Use a tuple (MapName, Mods) as key for more precise grouping?
            # For now, just MapName
            map_name = entry.get('MapName', 'Unknown Map')
            grouped_data[map_name].append(entry)

        logger.debug(f"Grouped {len(filtered_sorted_data)} entries into {len(grouped_data)} map groups.")

        # --- Populate Tree with Grouping --- 
        items_to_add = []
        for map_name, entries in grouped_data.items():
            if not entries: continue

            # Find best score entry for this map
            best_entry = max(entries, key=lambda x: self._get_score_value(x.get('Score')))

            # Create top-level item for the best entry using the helper
            top_item = self._create_history_tree_item(best_entry)
            
            # --- Removed explicit check for None and debug logs ---
            # Re-add explicit check for None from helper
            if top_item is None:
                logger.error(f"Skipping map group '{map_name}' because its best entry failed to create a tree item.")
                continue # Skip this group

            # Make best entry bold
            font = top_item.font(0) # Get font for first column
            font.setBold(True)
            for col_index in range(self.history_tree.columnCount()):
                top_item.setFont(col_index, font)
            
            # Store the original entry dict with the item for later use/sorting if needed
            top_item.setData(0, Qt.ItemDataRole.UserRole + 1, best_entry)

            items_to_add.append(top_item)

            # Create child items for other entries (if any)
            if len(entries) > 1:
                other_entries = [e for e in entries if e != best_entry]
                # Sort children by the criteria selected in the combo box
                # (They are already sorted within the `entries` list from `filter_and_sort_data`)
                for entry in other_entries:
                    child_item = self._create_history_tree_item(entry)
                    child_item.setData(0, Qt.ItemDataRole.UserRole + 1, entry) # Store original entry
                    top_item.addChild(child_item)
            else:
                 # Hide expand arrow if only one entry for this map
                 top_item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicatorWhenChildless)
        
        # Add all top-level items at once (potentially faster than one by one)
        self.history_tree.addTopLevelItems(items_to_add)

    def _get_score_value(self, score_str):
        """Helper to convert score string to a sortable numeric value."""
        try:
            # Remove commas before converting to int
            return int(str(score_str).replace(',',''))
        except (ValueError, TypeError):
            return -1 # Treat N/A or invalid scores as lowest

    def _create_history_tree_item(self, entry):
        """Helper function to create and populate a QTreeWidgetItem from an entry dict."""
        try:
            item = QTreeWidgetItem()
            for col_index, header in enumerate(self.history_headers):
                value = entry.get(header, "N/A")
                icon_path = None
                item_text = str(value)

                # --- Formatting --- 
                if header == 'StarRating':
                    icon_path = os.path.join(icon_base_dir, 'star.svg')
                    try:
                        num_val = float(str(value).replace('*','').strip())
                        item_text = f"{num_val:.2f}"
                    except (ValueError, TypeError):
                        item_text = "N/A"
                elif header == 'Score':
                    try:
                        # Format with comma, using the helper ensures numeric value first
                        score_val = self._get_score_value(value)
                        item_text = f"{score_val:,}" if score_val != -1 else "N/A"
                    except (ValueError, TypeError):
                        item_text = "N/A"
                # Keep default item_text for other columns

                item.setText(col_index, item_text)

                # --- Icon --- 
                # Re-enabled icon setting
                if icon_path and os.path.exists(icon_path):
                    icon = QIcon(icon_path)
                    if not icon.isNull():
                        item.setIcon(col_index, icon)

                # --- Alignment --- 
                if header in ['AvgOffsetMs', 'UR', 'Score', 'StarRating', 'MatchedHits', 'Timestamp']:
                    item.setTextAlignment(col_index, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                elif header == 'MapName':
                    item.setTextAlignment(col_index, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                else: # Mods
                    item.setTextAlignment(col_index, Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                    
                # --- Set Size Hint for StarRating Column --- 
                # Removed sizeHint setting
                # if header == 'StarRating':
                #      item.setSizeHint(col_index, QSize(40, 0))

                # --- Sorting Data (store sortable values) --- 
                sort_value = None
                if header == 'Timestamp':
                    try: sort_value = datetime.strptime(str(value), '%Y-%m-%d %H:%M:%S')
                    except ValueError: sort_value = datetime.min
                elif header == 'Score':
                    sort_value = self._get_score_value(value)
                elif header in ['AvgOffsetMs', 'UR', 'StarRating', 'MatchedHits']:
                    try:
                        num_str = str(value).replace('+','').replace('ms','').replace('*','').replace(',','').strip()
                        sort_value = -float('inf') if num_str.upper() == "N/A" else float(num_str)
                    except ValueError:
                        sort_value = -float('inf')
                else: # MapName, Mods
                    sort_value = str(value).lower()
                
                item.setData(col_index, Qt.ItemDataRole.UserRole, sort_value)
                
            return item # Return the successfully created item
        except Exception as e:
            logger.error(f"Error creating tree item for entry: {entry}", exc_info=True)
            return None # Explicitly return None on error

    def filter_and_sort_data(self, filter_text, sort_col_index, sort_order):
        """Filters and sorts the self.history_data based on UI controls."""
        lower_filter = filter_text.lower().strip()

        # Filter
        if lower_filter:
            # Original filter logic
            filtered_data = [
                entry for entry in self.history_data
                if any(lower_filter in str(entry.get(header, "")).lower() for header in self.history_headers)
            ]
        else:
            filtered_data = list(self.history_data) # Work with a copy

        # Sort (Restored logic)
        if sort_col_index >= 0 and sort_col_index < len(self.history_headers):
            sort_key_name = self.history_headers[sort_col_index]

            # Correct sort key function handling different types
            def sort_key_func(entry):
                value = entry.get(sort_key_name, "N/A")
                if sort_key_name == 'Timestamp':
                    try: return datetime.strptime(str(value), '%Y-%m-%d %H:%M:%S')
                    except (ValueError, TypeError): return datetime.min
                elif sort_key_name == 'Score': # Use helper for score
                     return self._get_score_value(value)
                elif sort_key_name in ['AvgOffsetMs', 'UR', 'StarRating', 'MatchedHits']:
                    try:
                        num_str = str(value).replace('+','').replace('ms','').replace('*','').replace(',','').strip()
                        if num_str.upper() == "N/A": return -float('inf')
                        return float(num_str)
                    except (ValueError, TypeError): return -float('inf')
                return str(value).lower() # Default string sort

            reverse = (sort_order == Qt.SortOrder.DescendingOrder)
            try:
                # Sort the list in-place
                filtered_data.sort(key=sort_key_func, reverse=reverse)
            except Exception as e:
                 logger.error(f"Error during sorting history data (key={sort_key_name}): {e}", exc_info=True)
        else:
             logger.warning(f"Invalid sort column index received: {sort_col_index}")

        # Return the filtered (and potentially sorted) list
        return filtered_data

    def filter_history(self):
        """Slot called when the history filter input text changes."""
        # Trigger repopulate, which reads filter input and current sort state from combo box
        logger.debug("Filter input changed, repopulating history tree.")
        self.populate_history_tree()

    def export_history(self):
        """Exports the current history data (from memory) to a new CSV file."""
        if not self.history_data:
             QMessageBox.information(self, "Export History", "There is no history data to export.")
             return

        save_path, _ = QFileDialog.getSaveFileName(self, "Export History As...", "osu_analyzer_history_export.csv", "CSV Files (*.csv)")

        if save_path:
            try:
                with open(save_path, 'w', newline='', encoding='utf-8') as csvfile:
                     fieldnames = self.history_headers # Use current headers
                     writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore')
                     writer.writeheader()
                     # Use the current in-memory data (which might be filtered/sorted in UI but we export all)
                     writer.writerows(self.history_data)
                QMessageBox.information(self, "Export Successful", f"History exported successfully to:\n{save_path}")
                logger.info(f"History exported ({len(self.history_data)} entries) to {save_path}")
            except Exception as e:
                logger.error(f"Error exporting history to {save_path}: {e}", exc_info=True)
                QMessageBox.critical(self, "Export Error", f"Failed to export history:\n\n{e}")

    def import_history(self):
        """Imports history data from a CSV file, appending to the existing history."""
        open_path, _ = QFileDialog.getOpenFileName(self, "Import History From...", "", "CSV Files (*.csv)")

        if open_path:
            reply = QMessageBox.question(self, "Import History",
                                         "Importing will add entries from the selected file to your current history (in memory and in the main CSV file).\n"
                                         "Duplicate entries might be created if they already exist.\n\n"
                                         "Proceed with import?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)

            if reply == QMessageBox.StandardButton.Yes:
                imported_count = 0
                new_entries = []
                try:
                    with open(open_path, 'r', newline='', encoding='utf-8') as csvfile:
                         reader = csv.DictReader(csvfile)
                         if not reader.fieldnames or not all(h in reader.fieldnames for h in self.history_headers):
                              raise ValueError(f"Import file is missing required headers or has incorrect format. Expected headers similar to: {self.history_headers}")

                         for row in reader:
                             # Basic validation - ensure required fields exist?
                             # Create entry using defined headers, taking values from row or default
                             entry = {h: row.get(h, 'N/A') for h in self.history_headers}
                             new_entries.append(entry)
                             imported_count += 1

                    if new_entries:
                         # Append to existing data in memory
                         self.history_data.extend(new_entries)
                         # Re-sort data in memory (important!)
                         try:
                              self.history_data.sort(key=lambda x: datetime.strptime(x.get('Timestamp', '1970-01-01 00:00:00'), '%Y-%m-%d %H:%M:%S'), reverse=True)
                         except ValueError:
                              logger.warning("Could not sort history by timestamp after import.")
                         # Append all new entries to the main CSV file
                         self.append_entries_to_csv(new_entries)
                         # Refresh tree UI - Removed sort_col argument
                         self.populate_history_tree() # Use current sort
                         # Update entry count directly
                         if hasattr(self, 'entry_count_label'):
                             self.entry_count_label.setText(f"Entries: {len(self.history_data)}")

                         QMessageBox.information(self, "Import Successful", f"Successfully imported and appended {imported_count} entries.")
                         logger.info(f"Imported {imported_count} entries from {open_path}")
                    else:
                         QMessageBox.information(self, "Import History", "No valid entries found in the selected file.")

                except Exception as e:
                    logger.error(f"Error importing history from {open_path}: {e}", exc_info=True)
                    QMessageBox.critical(self, "Import Error", f"Failed to import history:\n\n{e}")

    def append_entries_to_csv(self, entries):
        """Appends a list of entries to the main stats CSV file."""
        if not entries:
            return
        if not hasattr(self, 'history_headers'):
             logger.error("Cannot append entries to CSV: history_headers not defined.")
             return

        file_exists = os.path.isfile(STATS_CSV_FILE)
        try:
            os.makedirs(os.path.dirname(STATS_CSV_FILE), exist_ok=True)
            with open(STATS_CSV_FILE, 'a', newline='', encoding='utf-8') as csvfile:
                fieldnames = self.history_headers # Use consistent headers
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore')
                if not file_exists or os.path.getsize(STATS_CSV_FILE) == 0:
                    # Should not happen if app ran before, but safe check
                    writer.writeheader()

                # Ensure entries match headers before writing
                filtered_entries = [{k: entry.get(k, 'N/A') for k in fieldnames} for entry in entries]
                writer.writerows(filtered_entries)
            logger.info(f"Appended {len(entries)} imported entries to {STATS_CSV_FILE}")
        except Exception as e:
            logger.error(f"Error appending imported entries to {STATS_CSV_FILE}: {e}", exc_info=True)
            # Don't necessarily show message box here, import summary is enough

    def clear_history(self):
        """Clears the history data and the CSV file after confirmation."""
        confirm = QMessageBox.question(self, "Confirm Clear",
                                     "Are you sure you want to clear the entire analysis history? This cannot be undone.",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)

        if confirm == QMessageBox.StandardButton.Yes:
            logger.info("Clearing history...")
            # Clear the CSV file (write only headers)
            try:
                with open(STATS_CSV_FILE, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(self.history_headers) # Write headers back
                logger.info(f"Cleared history file: {STATS_CSV_FILE}")
                
                # Clear the in-memory data
                self.history_data = []
                
                # Update the history view
                self.populate_history_tree()

                # --- REMOVED Debugging lines --- 
                
                # Update the entry count label by finding it
                label_to_update = self.findChild(QLabel, "historyStatsLabel")
                if label_to_update:
                    label_to_update.setText(f"Entries: {len(self.history_data)}")
                    # --- REMOVED processEvents call --- 
                else:
                     logger.error("Could not find QLabel with objectName 'historyStatsLabel' to update.")
                
                self.update_status("History cleared.")
                # Optionally clear analyzer stats too?
                # self.update_analyzer_stats({}) # Pass empty dict to reset

            except IOError as e:
                logger.error(f"Failed to clear history file: {e}")
                QMessageBox.critical(self, "Error", f"Failed to clear history file: {e}")
                self.update_status("Error clearing history.")

    def load_stylesheet(self):
        """Loads the QSS stylesheet."""
        try:
            # TODO: Ensure style.qss is in the correct relative path
            style_path = "style.qss"
            if not os.path.exists(style_path):
                 logger.warning(f"Stylesheet not found at expected path: {style_path}")
                 # Attempt to find it relative to the script's directory as fallback
                 script_dir = os.path.dirname(os.path.abspath(__file__))
                 fallback_path = os.path.join(script_dir, "style.qss")
                 if os.path.exists(fallback_path):
                      style_path = fallback_path
                      logger.info(f"Found stylesheet at fallback path: {style_path}")
                 else:
                      raise FileNotFoundError(f"Stylesheet not found at {style_path} or {fallback_path}")

            with open(style_path, "r") as f:
                style = f.read()
                self.setStyleSheet(style)
                logger.info(f"Stylesheet '{os.path.basename(style_path)}' loaded successfully.")
        except FileNotFoundError:
            logger.warning("Stylesheet 'style.qss' not found. Using default styles.")
            # Optionally apply a very basic default dark theme here if desired
        except Exception as e:
            logger.error(f"Error loading stylesheet: {e}")
            # Optionally show a warning message box to the user
            # QMessageBox.warning(self, "Stylesheet Error", f"Could not load stylesheet: {e}")

    def load_initial_config(self):
        """Loads configuration using backend function and updates internal state."""
        logger.info("Loading initial configuration...")
        try:
            created_default, config_data = load_config() # Call backend function
            self.config_data = config_data
            logger.info(f"Config loaded. Default created: {created_default}")

            # Emit signal after config_data is set, so UI can react
            # self.config_updated.emit(self.config_data) # TODO: Uncomment when update_ui_from_config exists

            if created_default:
                # Show message box only after the main window is potentially visible
                # Use QTimer.singleShot to delay the message box slightly
                # QTimer.singleShot(100, lambda:
                #     QMessageBox.information(self, "Configuration Created",
                #                             f"A default configuration file ('{os.path.basename(CONFIG_FILE)}') "
                #                             f"has been created in:\n{os.path.dirname(CONFIG_FILE)}\n\n"
                #                             f"Please go to the Settings page and configure your osu! paths.")
                # )
                # Update status bar immediately
                self.statusLabel.setText("Default config created. Please configure paths in Settings.")
                # Switch to settings page automatically
                logger.info("Default config created. Switching to Settings page.")
                # Use QTimer to ensure the switch happens after __init__ completes
                QTimer.singleShot(0, lambda: self.switch_page(2))

        except Exception as e:
            logger.critical(f"FATAL: Failed to load configuration: {e}")
            # Show message box immediately as this might prevent app from working
            QMessageBox.critical(self, "Configuration Error", f"Failed to load configuration file.\nError: {e}\nPlease check the file or delete it to recreate a default.")
            # Decide if app should exit or continue with defaults
            # For now, let it continue but things will be broken.
            self.statusLabel.setText("CRITICAL: Config load failed!")
            self.config_data = { # Fallback defaults
                'replays_folder': '', 'songs_folder': '', 'osu_db_path': '',
                'log_level': 'INFO', 'replay_offset': -8, # Add other expected keys with defaults
                'monitor_replays': True, 'auto_analyze': True
            }
            # self.config_updated.emit(self.config_data) # Emit even with fallback data?

        except Exception as e:
            logger.exception("Unexpected exception occurred during load_initial_config") # Log full traceback
            QMessageBox.critical(self, "Config Load Error", f"An unexpected error occurred while loading configuration:\n\n{e}")
            # Decide if app should exit or continue with defaults
            # For now, let it continue but things will be broken.
            self.statusLabel.setText("CRITICAL: Config load failed!")
            self.config_data = { # Fallback defaults
                'replays_folder': '', 'songs_folder': '', 'osu_db_path': '',
                'log_level': 'INFO', 'replay_offset': -8, # Add other expected keys with defaults
                'monitor_replays': True, 'auto_analyze': True
            }
            # self.config_updated.emit(self.config_data) # Emit even with fallback data?

    @pyqtSlot(dict)
    def update_ui_from_config(self, config_data):
        """Populates the settings page UI elements from the loaded config data."""
        # Check if UI elements exist before trying to update them
        # This prevents errors if this is called before the UI is fully built
        if not hasattr(self, 'settings_btn'): # Use settings_btn as a proxy for UI readiness
            logger.debug("update_ui_from_config called before UI is ready. Skipping.")
            return

        logger.info("Updating Settings UI from configuration data.")
        try:
            # Paths
            if hasattr(self, 'replays_folder_input'):
                self.replays_folder_input.setText(config_data.get('replays_folder', ''))
            if hasattr(self, 'songs_folder_input'):
                self.songs_folder_input.setText(config_data.get('songs_folder', ''))
            if hasattr(self, 'osu_db_input'):
                self.osu_db_input.setText(config_data.get('osu_db_path', ''))

            # Analysis Settings
            if hasattr(self, 'replay_offset_input'):
                self.replay_offset_input.setText(str(config_data.get('replay_offset', -8)))
            if hasattr(self, 'monitor_replays_checkbox'): # Assuming checkbox name from previous structure
                 monitor_enabled = config_data.get('monitor_replays', True)
                 self.monitor_replays_checkbox.setChecked(monitor_enabled)
            if hasattr(self, 'auto_analyze_checkbox'): # Assuming checkbox name
                 auto_analyze_enabled = config_data.get('auto_analyze', True)
                 self.auto_analyze_checkbox.setChecked(auto_analyze_enabled)
            # --- ADDED: Update Log Level ComboBox ---
            if hasattr(self, 'log_level_combo'):
                log_level = config_data.get('log_level', 'INFO').upper()
                index = self.log_level_combo.findText(log_level, Qt.MatchFlag.MatchFixedString)
                if index >= 0:
                    self.log_level_combo.setCurrentIndex(index)
                else:
                    logger.warning(f"Loaded log level '{log_level}' not found in combo box. Defaulting display.")
                    # Optionally set to default index, e.g., INFO
                    default_index = self.log_level_combo.findText('INFO', Qt.MatchFlag.MatchFixedString)
                    if default_index >= 0: self.log_level_combo.setCurrentIndex(default_index)
            # --- END ADDED ---

            # --- ADDED: Update Behavior Checkboxes --- 
            if hasattr(self, 'minimize_to_tray_checkbox'):
                 minimize = config_data.get('minimize_to_tray', True) # Default True
                 self.minimize_to_tray_checkbox.setChecked(minimize)
            if hasattr(self, 'launch_minimized_checkbox'):
                 launch_min = config_data.get('launch_minimized', False) # Default False
                 self.launch_minimized_checkbox.setChecked(launch_min)
            if hasattr(self, 'start_stop_with_osu_checkbox'):
                 start_stop = config_data.get('start_stop_with_osu', False) # Default False
                 self.start_stop_with_osu_checkbox.setChecked(start_stop)
                 # Ensure checkbox is enabled/disabled based on psutil availability
                 self.start_stop_with_osu_checkbox.setEnabled(PSUTIL_AVAILABLE)
            # --- END ADDED --- 

            # History Settings (if they exist)
            if hasattr(self, 'save_history_checkbox'):
                 save_hist = config_data.get('save_history', True)
                 self.save_history_checkbox.setChecked(save_hist)
            if hasattr(self, 'history_days_slider') and hasattr(self, 'history_days_label'):
                 days = config_data.get('keep_history_days', 30)
                 # Clamp value to slider range if necessary
                 min_val = self.history_days_slider.minimum()
                 max_val = self.history_days_slider.maximum()
                 clamped_days = max(min_val, min(days, max_val))
                 self.history_days_slider.setValue(clamped_days)
                 if clamped_days == max_val:
                      self.history_days_label.setText("Never delete")
                 else:
                      self.history_days_label.setText(f"{clamped_days} days")

            # General Settings (if they exist) - Moved Behavior here for consistency?
            # ... existing general updates (Placeholder, none currently) ...

            logger.debug("Settings UI updated successfully.")

        except Exception as e:
             logger.error(f"Error updating settings UI from config: {e}", exc_info=True)

    def attempt_load_database(self):
        """Attempts to load the osu! database if the path is valid."""
        db_path = self.config_data.get('osu_db_path', '')
        if db_path and os.path.isfile(db_path):
            self.statusLabel.setText("Loading osu!.db...")
            QApplication.processEvents() # Allow UI to update
            try:
                self.osu_db = load_osu_database(db_path) # Use backend function
                self.statusLabel.setText("osu!.db loaded successfully.")
                logger.info("osu!.db loaded via attempt_load_database.")
            except Exception as e:
                logger.error(f"Failed to load osu!.db: {e}")
                self.statusLabel.setText("Error loading osu!.db.")
                QMessageBox.warning(self, "Database Error", f"Failed to load osu!.db from:\n{db_path}\n\nError: {e}\n\nBeatmap lookups will fail.")
                self.osu_db = None
        elif db_path:
             logger.warning(f"osu!.db path configured but not found: {db_path}")
             self.statusLabel.setText("osu!.db path invalid.")
        else:
             logger.warning("osu!.db path not configured.")
             self.statusLabel.setText("osu!.db path not set.")

    def maybe_start_monitor(self):
        """Starts the replay monitor thread if enabled and path is valid."""
        # Use get() with default True for monitor_replays if key is missing
        should_monitor = self.config_data.get('monitor_replays', True)
        logger.debug(f"Checking monitor status. Config says: {should_monitor}")

        if should_monitor:
            replays_path = self.config_data.get('replays_folder', '')
            if replays_path and os.path.isdir(replays_path):
                self.start_monitor_thread(replays_path)
            elif replays_path:
                logger.warning("Replays folder path configured but invalid. Cannot start monitoring.")
                self.statusLabel.setText("Replays folder invalid. Monitoring disabled.")
                self.stop_monitor_thread() # Ensure it's stopped if path becomes invalid
            else:
                logger.warning("Replays folder path not configured. Cannot start monitoring.")
                self.statusLabel.setText("Replays folder not set. Monitoring disabled.")
                self.stop_monitor_thread() # Ensure it's stopped if path becomes invalid
        else:
             logger.info("Replay monitoring is disabled in settings.")
             self.statusLabel.setText("Monitoring disabled.")
             self.stop_monitor_thread() # Ensure monitor is stopped if setting is disabled

    def start_monitor_thread(self, path):
        """Stops existing monitor and starts a new one."""
        if self.monitor_thread and self.monitor_thread.isRunning():
            logger.debug(f"Monitor thread already running for path {self.monitor_thread.path_to_watch}. Restarting for {path} if different.")
            if self.monitor_thread.path_to_watch == path:
                 logger.debug("Monitor path hasn't changed. Not restarting.")
                 # Ensure status label is correct
                 if self.statusLabel.text() != "Monitoring for new replays...":
                      self.statusLabel.setText("Monitoring for new replays...")
                 return # Don't restart if path is the same

        self.stop_monitor_thread() # Ensure any previous instance is stopped

        logger.info(f"Starting replay monitor for path: {path}")
        try:
            self.monitor_thread = MonitorThread(path)
            self.monitor_thread.new_replay_found.connect(self.handle_new_replay) # Connect the signal
            # Optional: connect finished/error signals if MonitorThread emits them
            # self.monitor_thread.finished.connect(self.on_monitor_finished)
            # self.monitor_thread.error.connect(self.on_monitor_error) # Assuming MonitorThread has an error signal
            self.monitor_thread.start()
            self.statusLabel.setText("Monitoring for new replays...")
        except Exception as e:
             logger.error(f"Failed to start MonitorThread: {e}", exc_info=True)
             self.statusLabel.setText("Error starting monitor thread!")
             QMessageBox.critical(self, "Monitor Error", f"Could not start the replay monitor thread.\nError: {e}")
             self.monitor_thread = None # Ensure it's None if start fails

    def stop_monitor_thread(self):
        """Stops the replay monitor thread if it's running."""
        if self.monitor_thread and self.monitor_thread.isRunning():
            logger.info("Stopping replay monitor thread...")
            try:
                self.monitor_thread.stop() # Call the thread's stop method
                # Wait a short time for the thread to finish gracefully
                if not self.monitor_thread.wait(2000): # Wait up to 2 seconds
                    logger.warning("Monitor thread did not stop gracefully after 2 seconds. Terminating.")
                    self.monitor_thread.terminate() # Force stop if needed
                    self.monitor_thread.wait() # Wait after terminate
                logger.info("Monitor thread stopped.")
                # Only update status if monitoring was truly disabled, not just restarting
                # if not self.config_data.get('monitor_replays', True):
                #      self.statusLabel.setText("Monitoring stopped.")
            except Exception as e:
                 logger.error(f"Error stopping monitor thread: {e}", exc_info=True)
                 # Update status even if stop fails?
                 self.statusLabel.setText("Error stopping monitor!")
        else:
             logger.debug("Stop monitor requested, but thread was not running or doesn't exist.")

        self.monitor_thread = None # Clear reference

    @pyqtSlot(str)
    def handle_new_replay(self, replay_path):
        """Handles the signal when a new replay file is detected."""
        logger.info(f"New replay detected by monitor: {replay_path}")
        # Use get() with default True for auto_analyze
        if self.config_data.get('auto_analyze', True):
            self.start_analysis(replay_path)
        else:
            logger.info("Auto-analysis disabled. Replay not processed automatically.")
            # Optional: Show a notification or update UI to indicate manual analysis needed
            self.statusLabel.setText(f"New replay found: {os.path.basename(replay_path)} (Auto-analysis disabled)")

    def start_analysis(self, replay_path):
        """Starts the analysis process for a given replay file."""
        if not self.osu_db:
            QMessageBox.warning(self, "Database Not Loaded", "Cannot analyze replay: osu!.db is not loaded. Please check settings.")
            logger.warning("Analysis cancelled: osu!.db not loaded.")
            self.statusLabel.setText("Analysis cancelled: osu!.db not loaded.") # Update status
            return

        if self.analysis_thread and self.analysis_thread.isRunning():
            # Maybe allow queuing later?
            QMessageBox.warning(self, "Analysis Busy", "An analysis is already in progress. Please wait.")
            logger.warning("Analysis cancelled: Another analysis is running.")
            return

        logger.info(f"Starting analysis for: {replay_path}")
        self.statusLabel.setText(f"Analyzing: {os.path.basename(replay_path)}...")
        QApplication.processEvents() # Ensure UI updates

        # Create worker and thread
        self.analysis_worker = AnalysisWorker(replay_path) # Pass replay path
        self.analysis_thread = QThread(self) # Parent thread to main window for management
        self.analysis_worker.moveToThread(self.analysis_thread)

        # Connect signals from worker to slots in this MainWindow
        self.analysis_worker.analysis_complete.connect(self.handle_analysis_complete)
        self.analysis_worker.status_update.connect(self.update_status)
        self.analysis_worker.error_occurred.connect(self.handle_analysis_error)

        # Connect thread signals
        self.analysis_thread.started.connect(self.analysis_worker.run)
        # Ensure thread quits after worker is done
        self.analysis_worker.analysis_complete.connect(self.analysis_thread.quit)
        self.analysis_worker.error_occurred.connect(lambda e: self.analysis_thread.quit()) # Quit on error too
        # Clean up worker and thread objects after thread finishes
        self.analysis_thread.finished.connect(self.analysis_worker.deleteLater)
        self.analysis_thread.finished.connect(self.analysis_thread.deleteLater)
        # Clear references after cleanup
        self.analysis_thread.finished.connect(lambda: setattr(self, 'analysis_worker', None))
        self.analysis_thread.finished.connect(lambda: setattr(self, 'analysis_thread', None))
        self.analysis_thread.finished.connect(lambda: logger.debug("Analysis thread finished and cleaned up."))

        # Start the thread
        self.analysis_thread.start()
        logger.debug("Analysis thread started.")

    @pyqtSlot(dict)
    def handle_analysis_complete(self, results):
        """Handles the results from the analysis worker."""
        replay_name = results.get('replay_name', 'N/A')
        logger.info(f"Analysis complete for: {replay_name}")
        self.statusLabel.setText(f"Analysis complete: {replay_name}")

        # --- Store results for graph metrics ---
        self.last_analysis_avg_offset = results.get("avg_offset") # Can be None
        self.last_analysis_ur = results.get("ur")                 # Can be None
        self.last_analysis_hit_offsets = results.get("hit_offsets", []) # Default to empty list
        logger.debug(f"Stored analysis results: AvgOffset={self.last_analysis_avg_offset}, UR={self.last_analysis_ur}, NumOffsets={len(self.last_analysis_hit_offsets)}")

        # --- Update UI ---
        self.update_analyzer_stats(results) # Updates text cards
        self.update_analyzer_graph(results) # Update graph with actual data

        # --- Add to History (this already calls populate_history_tree) --- 
        self.add_history_entry(results)

        # --- REMOVED Redundant call to refresh History Tree --- 
        # self.populate_history_tree() 

        # TODO: Play notification sound if enabled
        # if self.config_data.get('notification_sound', True):
        #     # Play sound
        #     pass

        # Set status back to monitoring if monitor is active
        if self.monitor_thread and self.monitor_thread.isRunning():
             self.statusLabel.setText("Monitoring for new replays...")
        elif not self.config_data.get('monitor_replays', True):
             self.statusLabel.setText("Monitoring disabled.")
        else:
             self.statusLabel.setText("Ready.") # Default ready state

    @pyqtSlot(str)
    def handle_analysis_error(self, error_message):
        """Handles errors reported by the analysis worker."""
        logger.error(f"Analysis Error: {error_message}")
        # Limit error message length for status bar
        status_error = error_message[:150] + "..." if len(error_message) > 150 else error_message
        self.statusLabel.setText(f"Analysis Error: {status_error}")
        QMessageBox.warning(self, "Analysis Error", f"An error occurred during analysis:\n\n{error_message}")
        # Reset status after showing error?
        # Set status back to monitoring if monitor is active
        if self.monitor_thread and self.monitor_thread.isRunning():
             self.statusLabel.setText("Monitoring for new replays...")
        elif not self.config_data.get('monitor_replays', True):
             self.statusLabel.setText("Monitoring disabled.")
        else:
             self.statusLabel.setText("Error during analysis. Ready.")

    @pyqtSlot(str)
    def update_status(self, message):
        """Updates the status bar label from worker status updates."""
        self.statusLabel.setText(message)
        logger.info(f"Status Update from Worker: {message}")

    def create_settings_page(self): # Modified to use backend load/save & simplify
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24) # Set default margins for this page
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(20)

        title = QLabel("Settings")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        # Create scroll area for settings
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setObjectName("settingsScrollArea")
        scroll_area.setFrameShape(QFrame.Shape.NoFrame) # No frame for scroll area

        # Create settings container widget within scroll area
        settings_container = QWidget()
        settings_layout = QVBoxLayout(settings_container)
        settings_layout.setSpacing(15) # Spacing between sections
        settings_layout.setContentsMargins(0, 0, 5, 0) # Add small right margin for scrollbar space

        # --- Paths Section ---
        paths_section = self.create_settings_section("Paths")
        paths_layout = paths_section.layout() # Get the QVBoxLayout from the section

        # Replays Folder
        replays_layout = QHBoxLayout()
        replays_layout.addWidget(QLabel("osu! Replays Folder:"))
        # Use correct attribute name: self.replays_folder_input
        self.replays_folder_input = QLineEdit()
        self.replays_folder_input.setObjectName("settingInput")
        self.replays_folder_input.setPlaceholderText("Path to your osu! Replays directory")
        replays_browse_btn = QPushButton("Browse...")
        replays_browse_btn.setObjectName("settingButton") # Style hint
        replays_browse_btn.clicked.connect(self.browse_replays_folder)
        replays_layout.addWidget(self.replays_folder_input)
        replays_layout.addWidget(replays_browse_btn)
        paths_layout.addLayout(replays_layout)

        # Songs Folder
        songs_layout = QHBoxLayout()
        songs_layout.addWidget(QLabel("osu! Songs Folder:"))
        # Use correct attribute name: self.songs_folder_input
        self.songs_folder_input = QLineEdit()
        self.songs_folder_input.setObjectName("settingInput")
        self.songs_folder_input.setPlaceholderText("Path to your osu! Songs directory")
        songs_browse_btn = QPushButton("Browse...")
        songs_browse_btn.setObjectName("settingButton")
        songs_browse_btn.clicked.connect(self.browse_songs_folder)
        songs_layout.addWidget(self.songs_folder_input)
        songs_layout.addWidget(songs_browse_btn)
        paths_layout.addLayout(songs_layout)

        # osu!.db File
        db_layout = QHBoxLayout()
        db_layout.addWidget(QLabel("osu!.db File Path:"))
        # Use correct attribute name: self.osu_db_input
        self.osu_db_input = QLineEdit()
        self.osu_db_input.setObjectName("settingInput")
        self.osu_db_input.setPlaceholderText("Path to your osu!.db file (in osu! install folder)")
        db_browse_btn = QPushButton("Browse...")
        db_browse_btn.setObjectName("settingButton")
        db_browse_btn.clicked.connect(self.browse_db_file)
        db_layout.addWidget(self.osu_db_input)
        db_layout.addWidget(db_browse_btn)
        paths_layout.addLayout(db_layout)

        settings_layout.addWidget(paths_section)

        # --- Analysis Section --- 
        analysis_section = self.create_settings_section("Analysis & Logging") # <-- Changed Title
        analysis_layout = analysis_section.layout()

        # Replay Time Offset
        offset_layout = QHBoxLayout()
        offset_layout.addWidget(QLabel("Replay Time Offset (ms):"))
        # Use correct attribute name: self.replay_offset_input
        self.replay_offset_input = QLineEdit()
        self.replay_offset_input.setObjectName("settingInput")
        # Allow integer input, backend expects int
        self.replay_offset_input.setValidator(QIntValidator(-200, 200)) # Integer between -200 and 200
        self.replay_offset_input.setToolTip("Adjust if replays seem consistently early/late (e.g., -8). Integer value.")
        self.replay_offset_input.setMaximumWidth(80) # Smaller width for integer input
        # Do not connect textChanged - save only on button press
        offset_layout.addWidget(self.replay_offset_input)
        offset_layout.addStretch()
        analysis_layout.addLayout(offset_layout)

        # --- ADDED: Log Level Dropdown ---
        log_level_layout = QHBoxLayout()
        log_level_layout.addWidget(QLabel("Logging Level:"))
        self.log_level_combo = QComboBox()
        self.log_level_combo.setObjectName("settingComboBox") # Style hint
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.log_level_combo.setToolTip("Set the detail level for log messages (DEBUG is most verbose).")
        # Find default index for INFO
        default_log_index = self.log_level_combo.findText('INFO')
        if default_log_index >= 0:
             self.log_level_combo.setCurrentIndex(default_log_index)
        log_level_layout.addWidget(self.log_level_combo)
        log_level_layout.addStretch()
        analysis_layout.addLayout(log_level_layout)
        # --- END ADDED ---

        # Monitor Replays Checkbox
        # Use correct attribute name: self.monitor_replays_checkbox
        self.monitor_replays_checkbox = QCheckBox("Monitor Replays Folder for New Files")
        self.monitor_replays_checkbox.setObjectName("settingCheckbox") # Style hint
        self.monitor_replays_checkbox.setToolTip("Automatically detect new .osr files in the Replays folder.")
        # Do not connect toggled - save only on button press
        analysis_layout.addWidget(self.monitor_replays_checkbox)

        # Auto-Analyze Checkbox
        # Use correct attribute name: self.auto_analyze_checkbox
        self.auto_analyze_checkbox = QCheckBox("Automatically Analyze New Replays")
        self.auto_analyze_checkbox.setObjectName("settingCheckbox")
        self.auto_analyze_checkbox.setToolTip("If monitoring is enabled, automatically start analysis when a new replay is found.")
        # Do not connect toggled - save only on button press
        analysis_layout.addWidget(self.auto_analyze_checkbox)

        settings_layout.addWidget(analysis_section)

        # --- ADDED: Behavior Section --- 
        behavior_section = self.create_settings_section("Behavior")
        behavior_layout = behavior_section.layout()

        self.minimize_to_tray_checkbox = QCheckBox("Minimize to system tray instead of closing")
        self.minimize_to_tray_checkbox.setObjectName("settingCheckbox")
        self.minimize_to_tray_checkbox.setToolTip("If enabled, closing the window will minimize the application to the system tray.")
        behavior_layout.addWidget(self.minimize_to_tray_checkbox)

        self.launch_minimized_checkbox = QCheckBox("Launch minimized to tray on PC startup")
        self.launch_minimized_checkbox.setObjectName("settingCheckbox")
        self.launch_minimized_checkbox.setToolTip("If enabled, the application window will not be shown on launch.\nRequires manually adding the app to your OS startup programs.")
        behavior_layout.addWidget(self.launch_minimized_checkbox)

        self.start_stop_with_osu_checkbox = QCheckBox("Start/Stop automatically with osu! (Experimental)")
        self.start_stop_with_osu_checkbox.setObjectName("settingCheckbox")
        tooltip_text = "If enabled, the analyzer will attempt to start when osu!.exe starts and close when osu!.exe closes.\nRequires the 'psutil' library to be installed."
        if not PSUTIL_AVAILABLE:
             tooltip_text += "\n(psutil not found - this feature is currently disabled)"
             self.start_stop_with_osu_checkbox.setEnabled(False) # Disable checkbox if psutil is missing
        self.start_stop_with_osu_checkbox.setToolTip(tooltip_text)
        behavior_layout.addWidget(self.start_stop_with_osu_checkbox)

        settings_layout.addWidget(behavior_section)
        # --- END ADDED --- 

        # --- History Management Section --- 
        history_section = self.create_settings_section("History Management")
        history_layout = history_section.layout()
        history_buttons_layout = QHBoxLayout()
        
        export_button = QPushButton("Export History")
        export_button.setObjectName("secondaryButton")
        export_button.setToolTip("Export all history entries to a CSV file.")
        export_button.clicked.connect(self.export_history)
        history_buttons_layout.addWidget(export_button)

        import_button = QPushButton("Import History")
        import_button.setObjectName("secondaryButton")
        import_button.setToolTip("Import and append entries from a CSV file.")
        import_button.clicked.connect(self.import_history)
        history_buttons_layout.addWidget(import_button)
        
        clear_button = QPushButton("Clear History")
        clear_button.setObjectName("dangerButton")
        clear_button.setToolTip("Permanently delete all history entries.")
        clear_button.clicked.connect(self.clear_history)
        history_buttons_layout.addWidget(clear_button)

        history_buttons_layout.addStretch()
        history_layout.addLayout(history_buttons_layout)
        settings_layout.addWidget(history_section)

        # --- Save Button --- (Moved out of sections)
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        save_button = QPushButton("Save Settings")
        save_button.setObjectName("primaryButton") # Style hint for emphasis
        save_button.clicked.connect(self.save_all_settings) # Connect to the save method
        button_layout.addWidget(save_button)

        settings_layout.addLayout(button_layout)
        settings_layout.addStretch() # Push sections up

        # Set the container widget for the scroll area
        scroll_area.setWidget(settings_container) # Restore scroll area
        layout.addWidget(scroll_area) # Restore scroll area
        # layout.addWidget(settings_container) # Remove direct adding

        # Initial population happens via update_ui_from_config called in __init__
        return page

    # Helper to create section frames (minor styling)
    def create_settings_section(self, title):
        section_frame = QFrame()
        section_frame.setObjectName("settingsSection")
        # section_frame.setFrameShape(QFrame.Shape.StyledPanel) # Example frame shape
        # section_frame.setFrameShadow(QFrame.Shadow.Raised) # Example shadow
        section_layout = QVBoxLayout(section_frame)
        section_layout.setSpacing(10)
        section_layout.setContentsMargins(15, 10, 15, 15)

        title_label = QLabel(title)
        title_label.setObjectName("settingsSectionTitle")
        section_layout.addWidget(title_label)

        # Optional separator line
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setObjectName("separator")
        section_layout.addWidget(line)

        return section_frame

    # --- Settings Page Actions ---

    def browse_replays_folder(self):
        # Use the current input value as starting directory if valid
        start_dir = self.replays_folder_input.text()
        if not os.path.isdir(start_dir): start_dir = ""
        folder = QFileDialog.getExistingDirectory(self, "Select osu! Replays Folder", start_dir)
        if folder:
            self.replays_folder_input.setText(folder.replace('/', '\\')) # Normalize path separators

    def browse_songs_folder(self):
        start_dir = self.songs_folder_input.text()
        if not os.path.isdir(start_dir): start_dir = ""
        folder = QFileDialog.getExistingDirectory(self, "Select osu! Songs Folder", start_dir)
        if folder:
            self.songs_folder_input.setText(folder.replace('/', '\\'))

    def browse_db_file(self):
        start_dir = os.path.dirname(self.osu_db_input.text())
        if not os.path.isdir(start_dir): start_dir = ""
        # Use correct filter name
        file, _ = QFileDialog.getOpenFileName(self, "Select osu!.db File", start_dir, "osu! Database (osu!.db)")
        if file:
            self.osu_db_input.setText(file.replace('/', '\\'))

    def save_all_settings(self):
        # ... logging and hasattr checks ...

        # --- Corrected Try Block Start ---
        try:
            # Gather values from UI
            replays_f = self.replays_folder_input.text().strip()
            songs_f = self.songs_folder_input.text().strip()
            db_path = self.osu_db_input.text().strip()
            log_level = self.log_level_combo.currentText()
            offset_str = self.replay_offset_input.text().strip()
            monitor = self.monitor_replays_checkbox.isChecked()
            auto_analyze = self.auto_analyze_checkbox.isChecked()
            minimize_tray = self.minimize_to_tray_checkbox.isChecked()
            launch_min = self.launch_minimized_checkbox.isChecked()
            start_stop_osu = self.start_stop_with_osu_checkbox.isChecked() if PSUTIL_AVAILABLE else False

            # Basic Validation
            error_messages = []
            if not replays_f or not os.path.isdir(replays_f):
                 error_messages.append("- Replays folder path is invalid or empty.")
            if not songs_f or not os.path.isdir(songs_f):
                 error_messages.append("- Songs folder path is invalid or empty.")
            if not db_path or not os.path.isfile(db_path):
                 error_messages.append("- osu!.db file path is invalid or empty.")
            try:
                time_offset = int(offset_str)
                if not (-200 <= time_offset <= 200):
                     raise ValueError("Offset out of range (-200 to 200)")
            except ValueError:
                 error_messages.append("- Replay Time Offset must be a valid integer between -200 and 200.")
            
            # No need to re-validate log_level from ComboBox
            # if log_level not in ["DEBUG", "INFO", "WARNING", "ERROR"]:
            #      error_messages.append("- Invalid Log Level selected.")
            #      log_level = "INFO" # Fallback

            if error_messages:
                 msg = "Please correct the following errors:\n\n" + "\n".join(error_messages)
                 QMessageBox.warning(self, "Invalid Settings", msg)
                 logger.warning(f"Settings validation failed: {error_messages}")
                 return

            # --- Convert offset here, AFTER validation --- 
            # time_offset = int(offset_str) # Already converted in the try-except block above

            # Call Backend Save
            logger.debug(f"Calling backend save_settings with: ... L='{log_level}', O={time_offset}, Tray={minimize_tray}, LaunchMin={launch_min}, StartStop={start_stop_osu}")
            success, result = save_settings(replays_f, songs_f, db_path, log_level, time_offset, 
                                          minimize_tray, launch_min, start_stop_osu)

            if success:
                logger.info("Settings saved successfully via backend.")
                QMessageBox.information(self, "Settings Saved", "Settings saved successfully.")

                # Update internal state and UI
                old_db_path = self.config_data.get('osu_db_path')
                self.config_data['replays_folder'] = replays_f
                self.config_data['songs_folder'] = songs_f
                self.config_data['osu_db_path'] = db_path
                self.config_data['replay_offset'] = time_offset
                self.config_data['monitor_replays'] = monitor
                self.config_data['auto_analyze'] = auto_analyze
                self.config_data['log_level'] = log_level
                self.config_data['minimize_to_tray'] = minimize_tray
                self.config_data['launch_minimized'] = launch_min
                self.config_data['start_stop_with_osu'] = start_stop_osu
                # --- END ADDED ---

                # Emit signal to potentially update other UI parts if needed
                self.config_updated.emit(self.config_data)

                # --- Handle Post-Save Actions --- #
                path_changed = result # Backend save returns True/False for path_changed on success
                db_path_changed = (old_db_path != db_path)

                if db_path_changed:
                    logger.info("osu!.db path changed, attempting reload.")
                    self.attempt_load_database() # Reload the database

                # Handle monitor restart logic based on path change or setting toggle
                monitor_running = self.monitor_thread is not None and self.monitor_thread.isRunning()

                if path_changed and monitor:
                    logger.info("Replays path changed, restarting monitor.")
                    self.start_monitor_thread(replays_f) # stop_monitor is called inside start_monitor
                elif monitor and not monitor_running:
                    logger.info("Monitor setting enabled, starting monitor.")
                    self.maybe_start_monitor()
                elif not monitor and monitor_running:
                    logger.info("Monitor setting disabled, stopping monitor.")
                    self.stop_monitor_thread()
                    self.statusLabel.setText("Monitoring disabled.") # Update status bar
                else:
                     logger.debug("Monitor state unchanged or already correct.")
                     # Update status bar in case it was showing an error
                     if monitor and monitor_running:
                          self.statusLabel.setText("Monitoring for new replays...")
                     elif not monitor:
                          self.statusLabel.setText("Monitoring disabled.")

            else:
                # Error occurred during backend save (result is error message string)
                error_msg = result
                logger.error(f"Failed to save settings via backend: {error_msg}")
                QMessageBox.critical(self, "Save Error", f"Failed to save settings:\n\n{error_msg}")

        except Exception as e:
            logger.exception("Unexpected exception occurred during save_all_settings") # Log full traceback
            QMessageBox.critical(self, "Save Error", f"An unexpected error occurred while saving settings:\n\n{e}")

    # --- Application Close Event --- 
    def closeEvent(self, event):
        """Handle window close event: Ask to minimize/quit or just quit."""
        should_minimize_setting = self.config_data.get('minimize_to_tray', False)
        tray_available = self.tray_icon is not None and QSystemTrayIcon.isSystemTrayAvailable()

        if should_minimize_setting and tray_available:
            # Ask the user what to do, mapping Yes->Minimize, No->Quit
            reply = QMessageBox.question(self, 'Minimize or Quit?', # Changed title slightly
                                       "Do you want to minimize to the system tray (Yes) or quit the application (No)?", # Clarified mapping
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel, # Use Yes/No/Cancel
                                       QMessageBox.StandardButton.Cancel) # Default button is Cancel
            
            if reply == QMessageBox.StandardButton.Yes: # User chose Yes (Minimize)
                event.ignore() # Don't close
                self.hide()    # Hide the window
                self.tray_icon.showMessage(
                    "osu! Replay Analyzer", "Minimized to tray.", 
                    QSystemTrayIcon.MessageIcon.Information, 2000
                )
                logger.info("Window hidden to system tray by user choice (Yes).")
            elif reply == QMessageBox.StandardButton.No: # User chose No (Quit)
                logger.info("Close event accepted by user choice (No -> Quit). Stopping threads...")
                self.stop_osu_process_monitor() # Stop osu! monitor first
                self.stop_monitor_thread() # Stop replay monitor
                self.stop_analysis_thread_on_quit() # Stop analysis
                logger.info("Exiting application via user choice (No -> Quit).")
                event.accept() # Accept the close event to quit
            else: # User chose Cancel or closed the dialog
                event.ignore() # Don't do anything
                logger.debug("Close event cancelled by user.")
        else:
            # Minimize setting is off or tray not available, proceed with normal quit
            logger.info("Close event triggered (Minimize setting off or tray unavailable). Stopping threads and quitting...")
            self.stop_osu_process_monitor()
            self.stop_monitor_thread()
            self.stop_analysis_thread_on_quit()
            logger.info("Exiting application via closeEvent (standard quit).")
            event.accept()

    # --- Load History from CSV --- 
    def load_history_from_csv(self):
        """Loads history data from the CSV file."""
        history = []
        if not os.path.isfile(STATS_CSV_FILE):
            logger.warning(f"History file not found: {STATS_CSV_FILE}. No history loaded.")
            return history # Return empty list

        try:
            with open(STATS_CSV_FILE, 'r', newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                # Check if headers exist and match expected format
                # Use self.history_headers (defined in __init__) for consistency
                # REMOVED fallback definition
                # if not hasattr(self, 'history_headers'):
                #      # Define headers if they weren't created yet (should match create_history_page)
                #      self.history_headers = ['Timestamp', 'MapName', 'Mods', 'AvgOffsetMs', 'UR', 'MatchedHits', 'Score', 'StarRating']
                #      logger.warning("history_headers defined within load_history_from_csv as it didn't exist yet.")

                # Compare reader fieldnames against the dynamic self.history_headers
                if not reader.fieldnames or not all(h in reader.fieldnames for h in self.history_headers):
                     logger.error(f"History file {STATS_CSV_FILE} has missing or incorrect headers.")
                     logger.error(f"Expected headers (approx): {self.history_headers}")
                     logger.error(f"Found headers in file: {reader.fieldnames}")
                     # Don't show popup here, handle gracefully
                     return history # Return empty list if headers mismatch

                for row in reader:
                    # Basic validation or cleaning could happen here if needed
                    # Create entry using defined headers, taking values from row or default
                    entry = {h: row.get(h, "N/A") for h in self.history_headers}
                    history.append(entry)

            logger.info(f"Loaded {len(history)} entries from {STATS_CSV_FILE}")
            # Sort by timestamp descending (most recent first) - assuming Timestamp format is sortable
            try:
                 history.sort(key=lambda x: datetime.strptime(x.get('Timestamp', '1970-01-01 00:00:00'), '%Y-%m-%d %H:%M:%S'), reverse=True)
            except ValueError:
                 logger.warning("Could not sort history by timestamp due to invalid format.")
                 # Fallback sort or no sort?

        except Exception as e:
            logger.error(f"Error loading history from {STATS_CSV_FILE}: {e}", exc_info=True)
            # Don't show popup here either
            # QMessageBox.warning(self, "History Load Error", f"Could not load history from:\n{STATS_CSV_FILE}\n\nError: {e}")
            return [] # Return empty list on error
        return history

    def add_history_entry(self, results):
        """Adds a new entry to the history data and saves it.
           Refreshes the history view.
        """
        logger.debug(f"Adding history entry: {results}")
        
        # Prepare the entry dictionary in the correct format/order for CSV/Table
        # Use the defined headers to ensure order and presence of keys
        entry_dict = {header: None for header in self.history_headers}
        
        entry_dict['Timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        # Map results keys to header keys carefully
        entry_dict['MapName'] = results.get('map_name', 'N/A') # Key from results dict
        entry_dict['Mods'] = results.get('mods', 'N/A')
        entry_dict['AvgOffsetMs'] = f"{results.get('avg_offset', 0):+.2f}" if results.get('avg_offset') is not None else "N/A"
        entry_dict['UR'] = f"{results.get('ur', 0):.2f}" if results.get('ur') is not None else "N/A"
        entry_dict['MatchedHits'] = results.get('matched_hits', 0)
        entry_dict['Score'] = results.get('score', 0)
        entry_dict['StarRating'] = f"{results.get('star_rating', 0):.2f}" if results.get('star_rating') is not None else "N/A"

        # --- Append to in-memory list FIRST ---
        self.history_data.append(entry_dict)
        
        # --- Update the count label by finding it --- 
        label_to_update = self.findChild(QLabel, "historyStatsLabel")
        if label_to_update:
            label_to_update.setText(f"Entries: {len(self.history_data)}")
            # QApplication.processEvents() # Let's remove this from here, keep it in clear_history for test
        else:
             logger.error("Could not find QLabel with objectName 'historyStatsLabel' to update.")
        # --- End Update ---

        # --- Save the single new entry to CSV ---
        if not self.save_single_history_entry_to_csv(entry_dict):
             logger.error("Failed to save the new history entry to CSV.")
             # Optionally inform user, but maybe too noisy?

        # --- Refresh the history view ---
        # Important: Filter text needs to be reapplied!
        current_filter = self.history_filter_input.text() if hasattr(self, 'history_filter_input') else None
        self.populate_history_tree(filter_text=current_filter) 

        logger.info(f"Added new history entry for map: {entry_dict['MapName']}")

    def save_single_history_entry_to_csv(self, entry_dict):
        """Appends a single analysis result entry to the stats CSV file."""
        if not hasattr(self, 'history_headers'):
             logger.error("Cannot save history entry: history_headers not defined.")
             return False # Return False on failure

        file_exists = os.path.isfile(STATS_CSV_FILE)
        try:
            # Ensure directory exists (redundant if backend.py already does it, but safe)
            os.makedirs(os.path.dirname(STATS_CSV_FILE), exist_ok=True)
            with open(STATS_CSV_FILE, 'a', newline='', encoding='utf-8') as csvfile:
                fieldnames = self.history_headers # Use defined headers
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore')
                if not file_exists or os.path.getsize(STATS_CSV_FILE) == 0:
                    writer.writeheader()
                    logger.info(f"Created/found empty stats file: {STATS_CSV_FILE}")

                # Ensure the entry dict only contains keys defined in fieldnames
                filtered_entry = {k: entry_dict.get(k, 'N/A') for k in fieldnames}
                writer.writerow(filtered_entry)
                logger.info(f"Saved single entry to {STATS_CSV_FILE}")
                return True # <-- ADDED: Return True on success
        except IOError as e:
            logger.error(f"IOError writing single entry to stats file {STATS_CSV_FILE}: {e}")
            QMessageBox.warning(self, "History Save Error", f"Could not save analysis result to:\n{STATS_CSV_FILE}\n\nError: {e}")
            return False # Return False on failure
        except Exception as e:
            logger.error(f"Unexpected error saving single stat entry: {e}", exc_info=True)
            QMessageBox.warning(self, "History Save Error", f"An unexpected error occurred saving the analysis result:\n{e}")
            return False # Return False on failure

    def update_analyzer_stats(self, results):
        """Updates the stat cards and title on the analyzer page."""
        if not hasattr(self, 'stat_cards'):
            logger.warning("Attempted to update analyzer stats, but stat cards don't exist.")
            return

        # Extract data from results dict
        tendency = results.get("tendency", "N/A")
        avg_offset = results.get("avg_offset")
        score = results.get("score", "N/A")
        ur = results.get("ur")
        matched_hits = results.get("matched_hits", "N/A")
        sr = results.get("star_rating")
        map_name = results.get("map_name", "Map Name Unavailable") # Get map name

        # Update song title label
        # Check if song_title label exists (assuming it's set in create_analyzer_page)
        if hasattr(self, 'song_title_label'): # Check attribute existence
            self.song_title_label.setText(map_name)
        else:
            # Find the label if not stored as attribute (less ideal)
            try:
                song_title_widget = self.findChild(QLabel, "songTitle")
                if song_title_widget:
                    song_title_widget.setText(map_name)
                    self.song_title_label = song_title_widget # Store for future use
                else:
                     logger.warning("Song title label not found for update (neither attribute nor by name).")
            except Exception as e:
                 logger.warning(f"Error finding song title label: {e}")

        # Format values for display
        offset_str = f"{avg_offset:+.2f} ms" if avg_offset is not None else "N/A"
        score_str = f"{score:,}" if isinstance(score, (int, float)) else str(score)
        ur_str = f"{ur:.2f}" if ur is not None else "N/A"
        hits_str = str(matched_hits)
        sr_str = f"{sr:.2f}*" if sr is not None else "N/A"

        # Update card value labels using the stored references
        def update_card_value(stat_name, value_str):
            card_info = self.stat_cards.get(stat_name)
            if card_info and isinstance(card_info, dict) and 'value_label' in card_info:
                card_info['value_label'].setText(value_str)
            else:
                logger.warning(f"Could not find value label for stat card: {stat_name}")

        update_card_value("Tendency", tendency)
        update_card_value("Average Hit Offset", offset_str)
        update_card_value("Score", score_str)
        update_card_value("Unstable Rate", ur_str)
        update_card_value("Matched Hits", hits_str)
        update_card_value("Star Rating", sr_str)

        # TODO: Update colors based on values (UR, Offset) using settings
        # self.update_card_colors(ur, avg_offset)

        # TODO: Update Graph - Needs implementation if graph is to be dynamic per replay
        # self.update_analyzer_graph(results)

        logger.info("Analyzer page stats updated.")

    def create_stat_card(self, title, value, color_hex):
        card_frame = QFrame()
        card_frame.setObjectName("statCard")
        card_frame.setProperty("cardColor", color_hex) # Custom property for QSS
        card_layout = QVBoxLayout(card_frame)
        card_layout.setContentsMargins(15, 10, 15, 10) # Adjust padding
        card_layout.setSpacing(4) # Reduce spacing

        title_label = QLabel(title)
        title_label.setObjectName("statTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        value_label = QLabel(str(value)) # Ensure value is string
        value_label.setObjectName("statValue")
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card_layout.addWidget(title_label)
        card_layout.addWidget(value_label)

        # Refresh style after setting property
        # Note: QSS might need '!important' or more specific selectors if this doesn't work
        # card_frame.setStyleSheet(card_frame.styleSheet()) # Force style refresh
        card_frame.style().unpolish(card_frame)
        card_frame.style().polish(card_frame)

        # Return dict containing references to labels for updating
        return {"frame": card_frame, "title_label": title_label, "value_label": value_label}

    def _get_score_value(self, score_str):
        """Helper to convert score string to a sortable numeric value."""
        try:
            return int(str(score_str).replace(',', ''))
        except (ValueError, TypeError):
            return -1 # Treat N/A or invalid scores as lowest

    def _create_history_tree_item(self, entry):
        """Helper function to create and populate a QTreeWidgetItem from an entry dict."""
        try:
            item = QTreeWidgetItem()
            for col_index, header in enumerate(self.history_headers):
                value = entry.get(header, "N/A")
                icon_path = None
                item_text = str(value)

                # --- Formatting --- 
                if header == 'StarRating':
                    icon_path = os.path.join(icon_base_dir, 'star.svg')
                    try:
                        num_val = float(str(value).replace('*','').strip())
                        item_text = f"{num_val:.2f}"
                    except (ValueError, TypeError):
                        item_text = "N/A"
                elif header == 'Score':
                    try:
                        # Format with comma, using the helper ensures numeric value first
                        score_val = self._get_score_value(value)
                        item_text = f"{score_val:,}" if score_val != -1 else "N/A"
                    except (ValueError, TypeError):
                        item_text = "N/A"
                # Keep default item_text for other columns

                item.setText(col_index, item_text)

                # --- Icon --- 
                # Re-enabled icon setting
                if icon_path and os.path.exists(icon_path):
                    icon = QIcon(icon_path)
                    if not icon.isNull():
                        item.setIcon(col_index, icon)

                # --- Alignment --- 
                if header in ['AvgOffsetMs', 'UR', 'Score', 'StarRating', 'MatchedHits', 'Timestamp']:
                    item.setTextAlignment(col_index, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                elif header == 'MapName':
                    item.setTextAlignment(col_index, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                else: # Mods
                    item.setTextAlignment(col_index, Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                    
                # --- Set Size Hint for StarRating Column --- 
                # Removed sizeHint setting
                # if header == 'StarRating':
                #      item.setSizeHint(col_index, QSize(40, 0))

                # --- Sorting Data (store sortable values) --- 
                sort_value = None
                if header == 'Timestamp':
                    try: sort_value = datetime.strptime(str(value), '%Y-%m-%d %H:%M:%S')
                    except ValueError: sort_value = datetime.min
                elif header == 'Score':
                    sort_value = self._get_score_value(value)
                elif header in ['AvgOffsetMs', 'UR', 'StarRating', 'MatchedHits']:
                    try:
                        num_str = str(value).replace('+','').replace('ms','').replace('*','').replace(',','').strip()
                        sort_value = -float('inf') if num_str.upper() == "N/A" else float(num_str)
                    except ValueError:
                        sort_value = -float('inf')
                else: # MapName, Mods
                    sort_value = str(value).lower()
                
                item.setData(col_index, Qt.ItemDataRole.UserRole, sort_value)
                
            return item # Return the successfully created item
        except Exception as e:
            logger.error(f"Error creating tree item for entry: {entry}", exc_info=True)
            return None # Explicitly return None on error

    def filter_history(self):
        """Slot called when the history filter input text changes."""
        # Trigger repopulate, which reads filter input and current sort state from combo box
        logger.debug("Filter input changed, repopulating history tree.")
        self.populate_history_tree()

    # --- Tray Icon Methods --- 
    def create_tray_icon(self):
        self.tray_icon = None # Initialize to None
        # Use the tray-specific icon primarily
        icon_path = os.path.join(icon_base_dir, 'analyzer_tray.svg')
        if not os.path.exists(icon_path):
             # Fallback to the main analyzer icon if tray icon not found
             icon_path = os.path.join(icon_base_dir, 'analyzer.svg')
             logger.warning(f"Tray icon 'analyzer_tray.svg' not found, falling back to main icon: {icon_path}")
             
        if not os.path.exists(icon_path):
             logger.error(f"Icon for tray ('analyzer_tray.svg' or 'analyzer.svg') not found at {icon_path}. Cannot create system tray icon.")
             return

        self.tray_icon = QSystemTrayIcon(QIcon(icon_path), self)
        self.tray_icon.setToolTip("osu! Replay Analyzer")

        # Create context menu
        tray_menu = QMenu(self)
        show_action = QAction("Show Analyzer", self)
        quit_action = QAction("Quit Analyzer", self)

        show_action.triggered.connect(self.showNormal) # Show the main window
        quit_action.triggered.connect(self.quit_application) # Quit properly

        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)

        # Connect activation signal (e.g., left-click)
        self.tray_icon.activated.connect(self.handle_tray_activation)

        # Show the tray icon initially if supported
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.show()
            logger.info("System tray icon created and shown.")
        else:
             logger.warning("System tray not available on this platform. Tray icon functionality disabled.")
             self.tray_icon = None # Set back to None if not available

    def handle_tray_activation(self, reason):
        # Show window on left-click, context menu handles right-click
        if reason == QSystemTrayIcon.ActivationReason.Trigger: # Trigger is usually left click
             self.showNormal()
             self.activateWindow() # Bring to front

    def quit_application(self):
        """Ensures application quits properly, stopping threads."""
        logger.info("Quit action triggered from tray menu.")
        self.stop_monitor_thread() # Stop monitor first
        self.stop_analysis_thread_on_quit() # Stop analysis if running
        QApplication.instance().quit() # Use instance().quit()
        
    # Renamed original stop_analysis for clarity
    def stop_analysis_thread_on_quit(self):
         if self.analysis_thread and self.analysis_thread.isRunning():
             logger.info("Analysis is currently running. Requesting worker stop for quit...")
             if hasattr(self.analysis_worker, 'stop') and callable(getattr(self.analysis_worker, 'stop')):
                  try:
                       logger.debug("Calling worker.stop() for quit")
                       self.analysis_worker.stop()
                  except Exception as e:
                       logger.error(f"Error calling worker.stop() on quit: {e}")
             logger.info("Waiting briefly for analysis thread to finish before quit...")
             if not self.analysis_thread.wait(1000): # Shorter wait on quit
                  logger.warning("Analysis thread did not finish gracefully on quit. Terminating.")
                  self.analysis_thread.terminate()
                  self.analysis_thread.wait()
             else:
                  logger.info("Analysis thread finished gracefully before quit.")

    # --- osu! Process Monitor Management --- 
    def maybe_start_osu_process_monitor(self):
        should_monitor = self.config_data.get('start_stop_with_osu', False)
        logger.debug(f"Checking osu! process monitor status. Config says: {should_monitor}")
        if should_monitor and PSUTIL_AVAILABLE:
            if not self.osu_process_monitor_thread or not self.osu_process_monitor_thread.isRunning():
                logger.info("Starting osu! process monitor thread...")
                self.osu_process_monitor_thread = OsuProcessMonitorThread()
                self.osu_process_monitor_thread.osu_running_status.connect(self.handle_osu_status_change)
                self.osu_process_monitor_thread.start()
            else:
                logger.debug("osu! process monitor thread already running.")
        else:
             if not PSUTIL_AVAILABLE and should_monitor:
                   logger.warning("Cannot start osu! process monitor: psutil not available.")
             elif not should_monitor:
                  logger.info("osu! process monitoring is disabled in settings.")
             self.stop_osu_process_monitor() # Ensure it's stopped if disabled or unavailable
             
    def stop_osu_process_monitor(self):
        if self.osu_process_monitor_thread and self.osu_process_monitor_thread.isRunning():
            logger.info("Stopping osu! process monitor thread...")
            self.osu_process_monitor_thread.stop()
            if not self.osu_process_monitor_thread.wait(2000): # Wait 2s
                logger.warning("osu! process monitor thread did not stop gracefully. Terminating.")
                self.osu_process_monitor_thread.terminate()
                self.osu_process_monitor_thread.wait()
            logger.info("osu! process monitor thread stopped successfully.")
        else:
             logger.debug("Stop osu! process monitor requested, but thread was not running or doesn't exist.")
        self.osu_process_monitor_thread = None
        
    @pyqtSlot(bool)
    def handle_osu_status_change(self, is_running):
        logger.info(f"Handling osu! status change. Currently running: {is_running}")
        # Only act if the main setting is enabled
        if self.config_data.get('start_stop_with_osu', False):
            if is_running:
                logger.info("osu! started. Ensuring replay monitor is active (if enabled).")
                # If osu! starts, make sure the replay monitor is running (respecting its own setting)
                self.maybe_start_monitor() 
            else:
                # --- Reverted Logic --- 
                logger.info("osu! stopped. Stopping replay monitor.")
                # If osu! stops, stop the replay monitor regardless of its setting
                self.stop_monitor_thread()
                # Optional: Hide the main window?
                # if self.config_data.get('minimize_to_tray', False) and self.tray_icon:
                #     self.hide()
                #     self.tray_icon.showMessage("osu! Replay Analyzer", "osu! closed. Analyzer hidden.", QSystemTrayIcon.MessageIcon.Information, 1500)
                # --- End Reverted Logic ---
        else:
             logger.debug("Ignoring osu! status change because 'Start/Stop with osu!' setting is disabled.")

    def update_analyzer_graph(self, results):
        """Updates the hit error graph with data from analysis results."""
        hit_offsets = results.get('hit_offsets')

        if not hit_offsets or len(hit_offsets) < 2: # Need at least 2 points for stdev/meaningful graph
            logger.warning("Not enough hit offset data to update graph.")
            self.hit_error_series.clear() # Clear previous data if any
            # Optionally set axes to default range or hide graph?
            self.axis_x.setRange(-20, 20)
            self.axis_y.setRange(0, 1) # Low range for empty data
            return

        try:
            # --- Histogram Calculation ---
            bin_width = 2 # ms per bin
            min_offset = min(hit_offsets)
            max_offset = max(hit_offsets)
            
            # Determine reasonable graph bounds (e.g., -50ms to +50ms, or based on data range)
            # Let's use a fixed range for now for simplicity, can adjust later
            graph_min_x = -30 
            graph_max_x = 30 
            
            # Calculate number of bins needed
            num_bins = int((graph_max_x - graph_min_x) / bin_width) + 1
            bins = [0] * num_bins
            bin_edges = [graph_min_x + i * bin_width for i in range(num_bins + 1)]

            # Populate bins
            for offset in hit_offsets:
                # Find the correct bin index
                bin_index = int((offset - graph_min_x) / bin_width)
                # Clamp index to valid range
                bin_index = max(0, min(bin_index, num_bins - 1)) 
                bins[bin_index] += 1

            # --- Update Chart Series ---
            self.hit_error_series.clear()
            max_bin_count = 0
            for i in range(num_bins):
                bin_center = graph_min_x + (i + 0.5) * bin_width
                self.hit_error_series.append(bin_center, bins[i])
                if bins[i] > max_bin_count:
                    max_bin_count = bins[i]

            # --- Update Axes ---
            self.axis_x.setRange(graph_min_x - bin_width, graph_max_x + bin_width) # Add padding
            # Set Y range slightly above max count for visibility
            self.axis_y.setRange(0, max_bin_count * 1.1 if max_bin_count > 0 else 1) 
            
            logger.info(f"Updated analyzer graph. Max bin count: {max_bin_count}")

        except Exception as e:
            logger.error(f"Error updating analyzer graph: {e}", exc_info=True)
            self.hit_error_series.clear() # Clear graph on error

if __name__ == '__main__':
    app = QApplication(sys.argv)

    # --- Load configuration *before* creating the window --- 
    config_data_for_launch = {}
    try:
        _, config_data_for_launch = load_config() # Use backend loader
    except Exception as e:
        # Log critical error, show message box, and potentially exit or use defaults
        logging.critical(f"FATAL: Failed to load initial configuration for launch check: {e}", exc_info=True)
        QMessageBox.critical(None, "Configuration Error", 
                           f"Failed to load configuration file.\\nError: {e}\\nPlease check the file or delete it to recreate a default. App might not function correctly.")
        # Set fallback defaults if loading fails, to allow app to potentially open
        config_data_for_launch = {
            'replays_folder': '', 'songs_folder': '', 'osu_db_path': '',
            'log_level': 'INFO', 'replay_offset': -8, 
            'minimize_to_tray': True, 'launch_minimized': False, 'start_stop_with_osu': False
        }

    # Check the launch setting
    launch_minimized = config_data_for_launch.get('launch_minimized', False)
    
    # --- Create the main window --- 
    logger.info("Creating MainWindow instance...")
    window = MainWindow() # MainWindow now loads its own config in __init__
    logger.info("MainWindow instance created.")

    # --- Show window or just tray icon --- 
    if launch_minimized and window.tray_icon:
         logger.info("Launch minimized enabled. Showing only tray icon.")
         # Tray icon is already shown in create_tray_icon if available
         # Optionally show a notification
         window.tray_icon.showMessage(
                "osu! Replay Analyzer",
                "Launched minimized to tray.",
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )
    else:
        logger.info("Showing main window on launch.")
        logger.info("Calling window.show()...")
        window.show()
        logger.info("window.show() called.")

    logger.info("Starting app.exec()...")
    exit_code = app.exec()
    logger.info(f"app.exec() finished with exit code: {exit_code}")
    sys.exit(exit_code) 
# -*- mode: python ; coding: utf-8 -*-
import sys, os

# Get the site-packages path for osrparse metadata
# WARNING: This assumes a standard Python install layout. Adjust if using venv differently.
python_dir = os.path.dirname(sys.executable)
site_packages_path = os.path.join(python_dir, 'Lib', 'site-packages')
# TODO: Verify osrparse version installed if needed, hardcoding 7.0.1 for now based on pip show
osrparse_metadata_name = 'osrparse-7.0.1.dist-info'
osrparse_metadata_path = os.path.join(site_packages_path, osrparse_metadata_name)

a = Analysis(
    ['main_app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('backend.py', '.'),
        ('osu_db.py', '.'),
        ('osu_string.py', '.'),
        ('path_util.py', '.'),
        ('array_adapter.py', '.'),
        ('beatmapparser.py', '.'),
        ('slidercalc.py', '.'),
        ('curve.py', '.'),
        ('icons', 'icons'),
        ('style.qss', '.'),
        (osrparse_metadata_path, osrparse_metadata_name)
    ],
    hiddenimports=[
        'osrparse',
        'construct',
        'enum',
        'psutil',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.QtCharts',
        'PyQt6.sip',
        'watchdog.observers',
        'watchdog.events',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='OsuAnalyzer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    onefile=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icons\\analyzer.png'
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='OsuAnalyzer',
)

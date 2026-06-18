# PyInstaller spec file for WF Riven Roller
# Run: pyinstaller build.spec

import os
from PyInstaller.utils.hooks import collect_data_files, collect_all

block_cipher = None

# Collect data files for heavy ML libraries
datas = []
datas += collect_data_files("easyocr")
datas += collect_data_files("sentence_transformers")
datas += collect_data_files("chromadb")
datas += collect_data_files("torch", include_py_files=False)

# Bundle our own data directory
datas += [
    ("data/good_rolls.xlsx",       "data"),
    ("data/stat_aliases.json",     "data"),
    ("data/stat_aliases_loader.py","data"),
]

# Bundle config skeleton (will be populated on first run)
datas += [
    ("config",  "config"),
]

hiddenimports = [
    "easyocr",
    "chromadb",
    "chromadb.api.segment",
    "sentence_transformers",
    "torch",
    "torchvision",
    "sklearn",
    "sklearn.metrics",
    "PyQt5.QtCore",
    "PyQt5.QtGui",
    "PyQt5.QtWidgets",
    "mss",
    "pyautogui",
    "openpyxl",
    "rapidfuzz",
    "cv2",
    "numpy",
    "PIL",
]

a = Analysis(
    ["main.py"],
    pathex=[os.path.abspath(".")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["matplotlib", "jupyter", "notebook", "IPython"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WFRivenRoller",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,         # No console window
    icon=None,             # Add icon path here if desired
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="WFRivenRoller",
)

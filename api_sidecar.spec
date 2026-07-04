# PyInstaller spec for the rivenforge FastAPI sidecar.
# Run: pyinstaller api_sidecar.spec

import os

from PyInstaller.utils.hooks import collect_all, collect_data_files

block_cipher = None

datas = [
    ("data/riven_index.json", "data"),
    ("data/stat_aliases.json", "data"),
    ("data/stat_aliases_loader.py", "data"),
    ("data/tfidf_model.json", "data"),
    ("config", "config"),
]

datas += collect_data_files("fastapi")
datas += collect_data_files("starlette")
datas += collect_data_files("uvicorn")

# windows-capture (WGC backend) is a compiled Rust extension (.pyd) — collect_all
# grabs its binary + data so the frozen sidecar can import it. It's optional at
# runtime (guarded), but bundling it is what enables background window capture.
_wc_datas, _wc_binaries, _wc_hidden = collect_all("windows_capture")
datas += _wc_datas

hiddenimports = [
    "api.app",
    "api.events",
    "api.schemas",
    "api.sessions",
    "core.analysis",
    "core.automation",
    "core.bg_input",
    "core.capture",
    "core.capture_wgc",
    "core.contracts",
    "core.hotkey",
    "core.models",
    "core.ocr",
    "core.ocr_pipeline",
    "core.parser",
    "core.profile_schema",
    "core.roller",
    "core.roll_logger",
    "core.rules",
    "core.stat_registry",
    "core.vision",
    "data.stat_aliases_loader",
    "rag.ingest",
    "rag.rag",
    "rag.wfm",
    "fastapi",
    "starlette",
    "uvicorn",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "multipart",
    "mss",
    "dxcam",
    "winocr",
    "win32api",
    "win32con",
    "win32gui",
    "win32process",
    "pyautogui",
    "openpyxl",
    "rapidfuzz",
    "cv2",
    "numpy",
    "PIL",
    "windows_capture",
]
hiddenimports += _wc_hidden

a = Analysis(
    ["api_sidecar.py"],
    pathex=[os.path.abspath(".")],
    binaries=list(_wc_binaries),
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "PyQt5",
        "easyocr",
        "torch",
        "torchvision",
        "sentence_transformers",
        "chromadb",
        "matplotlib",
        "jupyter",
        "notebook",
        "IPython",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    exclude_binaries=False,
    name="rivenforge-api",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    icon=None,
)

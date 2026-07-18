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
]

# NOTE: config/ is deliberately NOT bundled. It holds the maintainer's own
# runtime files — user_config.json (personal weapon/profiles) and license.key
# — which are gitignored and must never ship. Bundling them baked "quatz" and a
# valid license into every installer. A fresh install now starts from the
# built-in defaults in data_util._DEFAULTS (empty weapon, no profiles) and
# writes its own config to %LOCALAPPDATA%\rivenforge\ on first run.

datas += collect_data_files("fastapi")
datas += collect_data_files("starlette")
datas += collect_data_files("uvicorn")

# windows-capture (WGC backend) is a compiled Rust extension (.pyd) — collect_all
# grabs its binary + data so the frozen sidecar can import it. It's optional at
# runtime (guarded), but bundling it is what enables background window capture.
_wc_datas, _wc_binaries, _wc_hidden = collect_all("windows_capture")
datas += _wc_datas

# cryptography ships a compiled Rust extension (_rust.pyd) plus bundled OpenSSL.
# collect_all grabs those binaries so license verification actually works in the
# frozen build — without them core.license fails CLOSED and locks out every key.
_cr_datas, _cr_binaries, _cr_hidden = collect_all("cryptography")
datas += _cr_datas

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
    "core.license",
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
    # License verification. core.license imports these lazily inside functions
    # and fails CLOSED if they're missing — so an unbundled backend would lock
    # every legitimate key out of the frozen build.
    "cryptography",
    "cryptography.hazmat.primitives.asymmetric.ed25519",
    "cryptography.hazmat.bindings._rust",
]
hiddenimports += _wc_hidden
hiddenimports += _cr_hidden

a = Analysis(
    ["api_sidecar.py"],
    pathex=[os.path.abspath(".")],
    binaries=list(_wc_binaries) + list(_cr_binaries),
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

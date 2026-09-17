# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.building.osx import BUNDLE
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

SPECDIR = Path(SPECPATH)
STUDIO = SPECDIR.parent
REPO = STUDIO.parent
ICON = SPECDIR / "AppIcon.icns"
BUILD_INFO = SPECDIR / "build_info.json"

SKIP_PARTS = {
    ".git",
    ".gitignore",
    ".playwright-mcp",
    ".pytest_cache",
    "README.md",
    "TROUBLESHOOTING.md",
    "diagnostic-tool.js",
    "__pycache__",
    "node_modules",
    "sample-listing.json",
    "studio-build.js",
    "tests",
}


def tree(src: Path, dest_root: str) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    if not src.exists():
        return entries
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(src)
        if any(part in SKIP_PARTS or part.startswith(".") for part in rel.parts):
            continue
        entries.append((str(path), str(Path(dest_root) / rel.parent)))
    return entries


datas = [
    *tree(STUDIO / "dist", "dist"),
    *tree(REPO / "skills" / "list-this", "skills/list-this"),
    *tree(REPO / "vendoo-extension", "vendoo-extension"),
    *collect_data_files("webview"),
]
SEED = STUDIO / "data" / "category-trees-seed.json.gz"
if SEED.is_file():
    datas.append((str(SEED), "data"))
if BUILD_INFO.is_file():
    datas.append((str(BUILD_INFO), "."))

hiddenimports = [
    *collect_submodules("vendoo_studio"),
    *collect_submodules("webview"),
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "keyring.backends.macOS",
    "sqlalchemy.dialects.sqlite",
]

a = Analysis(
    [str(STUDIO / "server" / "vendoo_studio" / "desktop.py")],
    pathex=[str(STUDIO / "server")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "watchfiles"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="List This Studio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="List This Studio",
)
app = BUNDLE(
    coll,
    name="List This Studio.app",
    icon=str(ICON) if ICON.exists() else None,
    bundle_identifier="local.listthis.studio",
    info_plist={
        "CFBundleName": "List This Studio",
        "CFBundleDisplayName": "List This Studio",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.productivity",
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
    },
)

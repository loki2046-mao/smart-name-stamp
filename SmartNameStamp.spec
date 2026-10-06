# -*- mode: python ; coding: utf-8 -*-
# Shared PyInstaller build recipe for macOS (.app) and Windows (.exe folder).
# Build with:  pyinstaller --noconfirm SmartNameStamp.spec

from PyInstaller.utils.hooks import collect_data_files

APP_NAME = "SmartNameStamp"

# Bundle the open-source font and its license next to the engine.
datas = [
    ("assets/fonts/NotoSansCJKsc-Regular.otf", "assets/fonts"),
    ("assets/fonts/NotoSansCJK-LICENSE.txt", "assets/fonts"),
]
# Bundle OpenCV's Haar cascade XML files so face avoidance keeps working.
datas += collect_data_files("cv2")

a = Analysis(
    ["smart_name_stamp_gui.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=["smart_name_stamp"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "tkinter.test"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

# Only meaningful on macOS; ignored on Windows/Linux.
app = BUNDLE(
    coll,
    name=APP_NAME + ".app",
    icon=None,
    bundle_identifier="com.lokimao.smartnamestamp",
    info_plist={
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": "图片命名压字",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1.0.0",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
    },
)

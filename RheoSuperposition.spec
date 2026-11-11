# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['launcher.py'],
    pathex=['src'],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={'matplotlib': {'backends': 'TkAgg'}},
    runtime_hooks=[],
    excludes=['pytest', '_pytest'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='RheoSuperposition',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['RheoSuperposition_icns.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='RheoSuperposition',
)
app = BUNDLE(
    coll,
    name='RheoSuperposition.app',
    icon='RheoSuperposition_icns.icns',
    bundle_identifier=None,
    version="5.0.5",
    info_plist={"CFBundleShortVersionString": "5.0.5", "CFBundleVersion": "5.0.5"},
)

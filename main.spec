# -*- mode: python ; coding: utf-8 -*-
import os
import site

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

datas = []
binaries = []
hiddenimports = []

for package_name in ('selenium', 'webdriver_manager'):
    hiddenimports += collect_submodules(package_name)
    datas += collect_data_files(package_name, include_py_files=True)
    binaries += collect_dynamic_libs(package_name)


a = Analysis(
    ['main.py'],
    pathex=[os.getcwd(), *site.getsitepackages()],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='main',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

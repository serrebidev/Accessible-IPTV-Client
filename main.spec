# -*- mode: python ; coding: utf-8 -*-

import os
import sys

import chardet.pipeline

block_cipher = None
chardet_pipeline_path = os.path.dirname(chardet.pipeline.__file__)

# Hidden imports for networking and casting stacks
hidden_imports = [
    'pychromecast',
    'zeroconf',
    'aiohttp',
    'async_upnp_client',
    'pyatv',
    'miniaudio',
    'netifaces',
    'pydantic',
    'srptools',
    'tinytag',
    'tabulate',
    'defusedxml',
    'didl_lite',
    'voluptuous',
    'chacha20poly1305_reuseable',
    'requests',
    'vlc',
    'psutil',
    'cryptography',
    'chardet.pipeline.ascii__mypyc',
    'chardet.pipeline.confusion__mypyc',
    'chardet.pipeline.escape__mypyc',
    'chardet.pipeline.magic__mypyc',
    'chardet.pipeline.orchestrator__mypyc',
    'chardet.pipeline.statistical__mypyc',
    'chardet.pipeline.structural__mypyc',
    'chardet.pipeline.utf1632__mypyc',
    'chardet.pipeline.utf8__mypyc',
    'chardet.pipeline.validity__mypyc',
]

# Explicitly add some submodules that PyInstaller might miss
hidden_imports += [
    'pychromecast.controllers',
    'pychromecast.controllers.media',
    'async_upnp_client.client_factory',
    'async_upnp_client.aiohttp',
    'async_upnp_client.profiles.dlna',
    'async_upnp_client.search',
    'async_upnp_client.ssdp',
    'pyatv.conf',
    'pyatv.const',
    'pyatv.convert',
]

a = Analysis(
    ['main.py'],
    pathex=[chardet_pipeline_path],
    binaries=[],
    datas=[
        ('iptvclient.conf', '.'),
        ('init.mp4', '.'),
        ('ffmpeg.exe', '.'),
        ('update_helper.bat', '.'),
        ('update_helper.ps1', '.'),
        ('update_helper_launcher.vbs', '.'),
    ],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='IPTVClient',
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
    icon=None, # Add icon if available
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='iptvclient',
)

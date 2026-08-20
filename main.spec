# -*- mode: python ; coding: utf-8 -*-

import os
import sys

import chardet.pipeline

block_cipher = None
chardet_pipeline_path = os.path.dirname(chardet.pipeline.__file__)

# chardet ships its pipeline as mypyc-compiled extensions, and the module naming
# changed across releases: 7.0.x emitted a separate "<name>__mypyc" shared module
# that only gets imported at runtime (invisible to static analysis), while 7.3+
# compiles straight over "<name>". Hard-coding either scheme makes PyInstaller log
# "Hidden import not found" ERRORs on the other, which would mask a real missing
# import. Discover what this interpreter actually has instead.
chardet_pipeline_hiddenimports = []
for _fn in sorted(os.listdir(chardet_pipeline_path)):
    if not _fn.endswith(('.pyd', '.so')):
        continue
    _mod = _fn.split('.')[0]
    chardet_pipeline_hiddenimports.append('chardet.pipeline.' + _mod)
    # The 7.0.x-style companion module, only when it is really present.
    if not _mod.endswith('__mypyc'):
        _companion = _mod + '__mypyc'
        for _cand in os.listdir(chardet_pipeline_path):
            if _cand.split('.')[0] == _companion:
                chardet_pipeline_hiddenimports.append('chardet.pipeline.' + _companion)
                break
chardet_pipeline_hiddenimports = sorted(set(chardet_pipeline_hiddenimports))
print('main.spec: chardet %s pipeline hidden imports -> %d module(s)'
      % (getattr(chardet, '__version__', '?'), len(chardet_pipeline_hiddenimports)))

# Always (re)compile translations from the .po sources so a release can never ship a
# stale .mo. Pure standard library (no GNU gettext / Babel needed).
try:
    _spec_dir = SPECPATH  # PyInstaller-injected: directory containing this spec
except NameError:
    _spec_dir = os.getcwd()
sys.path.insert(0, os.path.join(_spec_dir, 'tools'))
import i18n_tools
i18n_tools.cmd_compile()

# Ship every locale/<lang>/LC_MESSAGES/*.mo preserving the directory layout so
# i18n.locale_dir() (sys._MEIPASS/locale) finds them at runtime.
locale_datas = []
for _root, _dirs, _files in os.walk('locale'):
    for _fn in _files:
        if _fn.endswith('.mo'):
            locale_datas.append((os.path.join(_root, _fn), _root))

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
] + chardet_pipeline_hiddenimports

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
        ('init.mp4', '.'),
        ('ffmpeg.exe', '.'),
        ('update_helper.bat', '.'),
        ('update_helper.ps1', '.'),
    ] + locale_datas,
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

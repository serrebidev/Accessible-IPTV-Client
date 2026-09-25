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

# The offline User Guide, one Markdown file per language. user_guide.guide_dir()
# reads it from sys._MEIPASS/docs/help, and F1 help has nothing to show without it.
_help_dir = os.path.join(_spec_dir, 'docs', 'help')
help_datas = [(os.path.join(_help_dir, _fn), os.path.join('docs', 'help'))
              for _fn in sorted(os.listdir(_help_dir)) if _fn.endswith('.md')]
if not any(os.path.basename(src) == 'en.md' for src, _dest in help_datas):
    raise SystemExit('main.spec: docs/help/en.md (the English user guide) is missing')

# Hidden imports for networking and casting stacks
hidden_imports = [
    'pychromecast',
    'zeroconf',
    'aiohttp',
    'pyatv',
    'soco',
    # Caster's casting engine and protocol clients (tools/sync_caster.py).
    # casting.py imports them lazily, so name them for the analysis.
    'caster_engine',
    'caster_extras',
    'caster_devices',
    'caster_config',
    'miniaudio',
    'pydantic',
    'srptools',
    'tinytag',
    'tabulate',
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
    'pychromecast.models',
    'pychromecast.const',
    'pyatv.conf',
    'pyatv.const',
    'pyatv.convert',
]

# Windows ships the LFS ffmpeg.exe and the PowerShell update helper. macOS
# (tools/build_macos.sh) bundles Homebrew's ffmpeg and VLC.app's libVLC and
# plugins; main.py points PATH and python-vlc at them when frozen.
platform_binaries = []
platform_datas = []
if sys.platform == 'win32':
    platform_datas += [('ffmpeg.exe', '.'), ('update_helper.ps1', '.')]
elif sys.platform == 'darwin':
    import shutil
    _ffmpeg = os.environ.get('IPTV_FFMPEG') or shutil.which('ffmpeg')
    _vlc = os.path.join(os.environ.get('IPTV_VLC_APP', '/Applications/VLC.app'), 'Contents', 'MacOS')
    _missing = [p for p in (_ffmpeg or 'ffmpeg', os.path.join(_vlc, 'lib', 'libvlc.dylib'),
                            os.path.join(_vlc, 'plugins')) if not os.path.exists(p)]
    if _missing:
        raise SystemExit('main.spec: macOS build needs ffmpeg and VLC.app; missing: ' + ', '.join(_missing))
    platform_binaries += [
        (_ffmpeg, '.'),
        (os.path.join(_vlc, 'lib', 'libvlc.dylib'), os.path.join('vlc', 'lib')),
        (os.path.join(_vlc, 'lib', 'libvlccore.dylib'), os.path.join('vlc', 'lib')),
    ]
    # Not VLC's Mac GUI (needs Sparkle) or notifications (needs Growl), and not
    # plugins.dat: re-signing the plugins makes that cache stale.
    _skip = {'libmacosx_plugin.dylib', 'libosx_notifications_plugin.dylib', 'plugins.dat'}
    platform_datas += [(os.path.join(_vlc, 'plugins', _fn), os.path.join('vlc', 'plugins'))
                       for _fn in sorted(os.listdir(os.path.join(_vlc, 'plugins'))) if _fn not in _skip]

a = Analysis(
    ['main.py'],
    pathex=[chardet_pipeline_path],
    binaries=platform_binaries,
    datas=[
        ('CHANGELOG.md', '.'),
        ('init.mp4', '.'),
    ] + platform_datas + locale_datas + help_datas,
    hiddenimports=hidden_imports,
    hookspath=[os.path.join(SPECPATH, 'pyinstaller_hooks')],
    hooksconfig={},
    runtime_hooks=[],
    # caster_extras (vendored from Caster) lazily imports Caster's own GUI
    # module and its WASAPI capture library for screen and PC-audio casting,
    # which this app does not use. Excluded so they are not reported missing.
    # Optional imports in rich, dotenv and pydantic pull in IPython (and with it
    # jedi, parso and black) and pydantic.mypy pulls in mypy: developer tools the
    # app never runs, which bloated the bundle.
    excludes=['caster', 'pyaudiowpatch',
              'IPython', 'jedi', 'parso', 'black', 'mypy', 'matplotlib_inline'],
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

# macOS: app bundle (tools/build_macos.sh zips it).
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='AccessibleIPTVClient.app',
        bundle_identifier='com.serrebidev.accessibleiptvclient',
        info_plist={
            'NSHighResolutionCapable': True,
            'NSLocalNetworkUsageDescription': 'Accessible IPTV Client finds and casts to devices on your network.',
            'NSBonjourServices': ['_googlecast._tcp', '_airplay._tcp', '_raop._tcp'],
        },
    )

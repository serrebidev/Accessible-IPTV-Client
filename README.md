# Accessible IPTV Client

A vibe-coded, keyboard-first IPTV player for Windows and Linux, built to work well with screen readers and hold up on large playlists and EPGs.

[![Join SerrebiProjects on Telegram](https://img.shields.io/badge/Telegram-SerrebiProjects-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/SerrebiProjects)

**Have a question, hit a bug, or want early word on new releases?** Join the [SerrebiProjects Telegram group](https://t.me/SerrebiProjects) — the community hub for Accessible IPTV Client and my other projects, and the fastest place to get help.

## Features

- Screen reader friendly (NVDA, JAWS, Narrator, Orca).
- M3U/M3U+ playlists, Xtream Codes, and Stalker Portal sources.
- Built-in player (libVLC via python-vlc) or an external player (VLC, MPC-HC, MPV, etc.).
- Channel groups, fast channel search, and EPG search.
- XMLTV EPG support (`.xml` and `.xml.gz`), including large multi-million-row guides.
- Catch-up/timeshift playback for channels that support it.
- Casting support, plus optional system tray minimize.
- Multilingual interface (English and Hungarian) with automatic OS-language detection and a manual selector under **Options > Language**.
- Built-in updater on Windows that verifies SHA-256 and Authenticode before applying an update.

## Download and install

Grab the latest build from the [Releases page](https://github.com/serrebidev/Accessible-IPTV-Client/releases).

**Windows installer (recommended)**

1. Download `AccessibleIPTVClient-Setup-vX.Y.Z.exe`.
2. Run it and approve the elevation prompt. It installs to Program Files, adds a Start Menu entry, and updates itself in place.

**Windows portable**

1. Download `AccessibleIPTVClient-vX.Y.Z.zip` (or `IPTVClient.zip`).
2. Extract it anywhere and run `IPTVClient.exe` — no installation required.

**Linux**

No packaged build yet — run it from source (below).

Installed builds keep your settings, EPG database, schedules, and cache in `%APPDATA%\AccessibleIPTVClient`. Portable builds keep the settings file (`iptvclient.conf`) next to `IPTVClient.exe` and fall back to the same `%APPDATA%` folder for everything else. Uninstalling leaves your data untouched.

## Run from source (Windows or Linux)

1. Install Python 3.11+.
2. Install dependencies: `pip install -r requirements.txt`
3. If you want the built-in player, install VLC 3.0+ (python-vlc loads libVLC from your VLC install).
4. Launch it: `python main.py`

## Keyboard shortcuts

### Main window

- **Ctrl+M** — Playlist Manager
- **Ctrl+E** — EPG Manager
- **Ctrl+I** — Import EPG to database
- **Ctrl+Q** — Exit
- **Enter** — Play selected channel
- **Context Menu / Apps key** — Channel options (including Catch-up if available)

### Built-in player

- **Space** — Play/Pause
- **Up / Down** — Adjust volume (2% steps)
- **Ctrl+Up / Ctrl+Down** — Adjust volume (5% steps)
- **F11** — Toggle fullscreen
- **Escape** — Exit fullscreen
- **Tab** — Navigate between controls

## EPG notes

- During EPG import, a detailed log is written to `iptvclient_epg_debug.log` — in `%APPDATA%\AccessibleIPTVClient` on Windows, or your system temp directory elsewhere.
- `.xml.gz` guides are supported and go through a safe download/verify workflow.

## Built-in player buffering

The internal player sizes its network buffer dynamically. You can tune it in `iptvclient.conf`:

- `internal_player_buffer_seconds` (default ~2s)
- `internal_player_max_buffer_seconds` (default ~18s)
- `internal_player_variant_max_mbps` (HLS quality cap in Mbps, 0 = no cap)

Lower values start faster; higher values are more tolerant of jitter.

## Languages and translations

The interface is translatable with GNU gettext. By default the app follows your OS language and falls back to English; override this under **Options > Language** (Automatic / English / Hungarian). The choice is saved to `iptvclient.conf` (`language`) and applies fully after a restart.

Translations live in `locale/<lang>/LC_MESSAGES/iptvclient.po`. The tooling is pure Python — no GNU gettext, Babel, or polib required:

```bash
python tools/i18n_tools.py extract   # refresh locale/iptvclient.pot from the source
python tools/i18n_tools.py update    # merge new strings into every .po (keeps translations)
python tools/i18n_tools.py compile   # compile every .po -> .mo
```

To contribute a new language:

1. Run `python tools/i18n_tools.py update` (or copy `locale/iptvclient.pot`) to create `locale/<code>/LC_MESSAGES/iptvclient.po`, then translate the `msgstr` lines.
2. Run `python tools/i18n_tools.py compile`.
3. Add `(code, "Native name")` to `_LANGUAGE_LABELS` in `i18n.py` so it appears in the menu.
4. Open a pull request. Keep every `{placeholder}` exactly as it appears in the English source.

Hungarian translation and screen-reader testing contributed by the community (see issue [#2](https://github.com/serrebidev/Accessible-IPTV-Client/issues/2)).

## Building

See [`BUILD.md`](BUILD.md) for the full release pipeline — PyInstaller packaging, Authenticode signing, and the Program Files installer.

```bat
build.bat build       # build the app
build.bat dry-run     # preview the next version bump and release notes
build.bat release     # bump version, build, sign, zip, tag, push, and create a GitHub Release
```

Release prerequisites: `gh` CLI authenticated (`gh auth login`), and a code signing certificate installed with `signtool.exe` available (or set `SIGNTOOL_PATH`).

## Contributing

Pull requests are welcome. If Accessible IPTV Client has been useful to you, open a PR with a fix or feature and I'll review it.

## Community and support

Report bugs and request features in [Issues](https://github.com/serrebidev/Accessible-IPTV-Client/issues). For questions, feedback, and release news, join the [SerrebiProjects Telegram group](https://t.me/SerrebiProjects).

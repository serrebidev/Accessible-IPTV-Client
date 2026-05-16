You are a professional Windows Python developer with a decade of IPTV app experience. Always fully investigate things before applying a fix. If you learn anything new that affects future work on this repo, write it in this file.

You are root on this Windows machine and can install and use whatever is needed with winget, PowerShell, Chocolatey, pip, or other package managers.

Make sure the PyInstaller spec file includes all runtime requirements, dynamic imports, binary assets, and needed submodules for the build.

When building, always check for warnings, errors, and dependency mismatches in the build output. If any are found, fix them before proceeding. Never ship a build that had unresolved warnings or errors.

## Project Overview

Project = Accessible IPTV Client, a wxPython GUI focused on playlist loading, EPG import/search/matching, accessible channel browsing, internal/external playback, casting, and Windows self-updates.

`main.py` creates the main frame, tray icon, playlist/EPG managers, channel/group/search UI, background playlist and EPG work, player launching, casting actions, and update checks. `options.py` owns config persistence, cache paths, database paths, and config normalization.

## Architecture

- **main.py**: Main wx frame (`IPTVClient`), tray restore behavior, playlist and EPG managers, channel list population, group filtering, search including EPG search, catch-up dialog, internal/external player launch, casting menu actions, and update prompts.
- **internal_player.py**: Built-in libVLC player with adaptive buffering, stream preflight checks, live/catch-up option handling, automatic reconnect logic, fullscreen (F11), play/pause/stop controls, accessible control names, and volume slider. Volume uses 2% normal steps and 5% Ctrl+Up/Down steps.
- **sitecustomize.py**: Compatibility shim only. It re-exports the canonical `InternalPlayerFrame` from `internal_player.py` and must not grow separate player logic.
- **playlist.py**: Playlist parsing plus XMLTV import/search/matching. The EPG database is SQLite in `tempfile.gettempdir()` via `options.get_db_path()`, uses WAL and busy timeouts, logs debug details to `iptvclient_epg_debug.log` in the temp directory, and handles XML/GZip downloads with resume plus HTTP 416 fallback.
- **providers.py**: Xtream Codes and Stalker Portal clients for building playlist/EPG URLs, handling auth/session state, and surfacing `ProviderError`.
- **options.py**: JSON config persistence. Reads portable/app, cwd, user config, and frozen `_MEIPASS` candidates; writes to the app/cwd path when possible and otherwise the user config path. Also provides cache path hashing, default config values, config clamping, and canonical naming helpers.
- **casting.py**: Persistent background asyncio loop for cast operations. Supports Chromecast, DLNA/UPnP, and AirPlay when optional libraries are installed.
- **stream_proxy.py**: Local stream proxy for casting. Handles direct byte proxying, HLS remux/transcode, Chromecast-safe HLS output, radio/audio mode, Python-to-FFmpeg piping for provider auth headers, bootstrap HLS startup, and best-effort Windows Firewall rules.
- **updater.py**, **update_helper.bat**, **update_helper.ps1**, **update_helper_launcher.vbs**: Windows packaged-app updater. Uses a GitHub release manifest, SHA-256 validation, Authenticode verification with pinned thumbprints, hidden helper launch, backup, rollback, and local config preservation.
- **main.spec**, **tools/release.py**, **build.bat**, **build_exe.bat**: Build and release pipeline. `build.bat` delegates to `build_exe.bat`; `build_exe.bat` delegates core work to `tools/release.py`.

## Key Features

- Screen reader accessible UI for NVDA, JAWS, Narrator, and Orca-oriented workflows.
- M3U/M3U Plus playlists, Stalker Portal providers, and Xtream Codes providers.
- XMLTV EPG support from `.xml` and `.xml.gz` sources.
- EPG matching tuned for Australia, Canada, Ireland, UK, and US channel naming patterns.
- Built-in VLC player with adaptive buffering, preflight errors, live stream reconnect handling, and accessible controls.
- External player support for VLC, MPV, MPC-HC, and custom player paths.
- Chromecast, DLNA/UPnP, and AirPlay casting when dependencies and devices are available.
- Catch-up/timeshift playback for supported channels.
- Channel grouping, channel search, and EPG search.
- System tray minimize/restore support.
- Windows packaged auto-update support.
- Cross-platform source app support for Windows and Linux, with the release pipeline focused on Windows.

## Config File (`iptvclient.conf`)

Important keys include `playlists`, `epgs`, `media_player`, `custom_player_path`, `internal_player_buffer_seconds`, `internal_player_max_buffer_seconds`, `internal_player_variant_max_mbps`, `epg_enabled`, `epg_auto_import_interval_hours`, `minimize_to_tray`, `show_player_on_enter`, and `auto_check_updates`.

`iptvclient.conf` is user-local runtime configuration. Do not bundle a local repo `iptvclient.conf` into public releases.

## Dependencies

Runtime requirements are defined in `requirements.txt`: `wxPython`, `python-vlc`, `pychromecast`, `async-upnp-client`, and `pyatv`. `pytest` is listed for development/testing.

The standalone Windows build also explicitly collects dynamic modules and metadata in `main.spec`, including casting/network stacks, VLC, updater/signing dependencies, `psutil`, and chardet mypyc modules. Keep `main.spec` in sync whenever imports or optional runtime features change.

## Current Release Build Rules

- Use `build.bat release` for public releases. `build.bat` calls `build_exe.bat`, which calls `tools/release.py`; running `build.bat` with no argument performs a local build only.
- Releases must be non-draft and marked latest.
- Never delete old non-draft releases unless the user explicitly asks. It is okay to delete leftover draft releases.
- Never ship a release when PyInstaller reports unresolved warnings, missing imports, dependency mismatches, failed validation, or build errors.
- Do not bundle local `iptvclient.conf`. `main.spec` excludes it, and `tools/release.py` must fail the build if any packaged `iptvclient.conf` is found.
- `ffmpeg.exe` is tracked through Git LFS. Before releasing, ensure it is the real executable, not a small LFS pointer file. `tools/release.py` validates both the source and packaged `ffmpeg.exe` by size, pointer detection, and `ffmpeg -version`.
- `tools/release.py` runs PyInstaller through a limited Task Scheduler task when the current process is elevated, avoiding PyInstaller's elevated-token deprecation warning.
- `tools/release.py` creates the update manifest asset required by the auto-updater. Required manifest fields include `version`, `asset_filename`, `download_url`, `sha256`, and `release_notes_summary`.
- PowerShell/Batch release quoting matters on Windows. In batch files, `git describe --tags --abbrev=0` must be written as `--abbrev^=0` inside `for /f`. Inside a quoted `powershell -Command`, use a normal pipeline character (`|`), not `^|`.
- When cleaning GitHub draft releases from PowerShell, decode JSON first and filter explicit draft booleans with `Where-Object { $_.isDraft -eq $true }`; do not pipe raw JSON array output directly into a truthy object filter.

## Current Learnings

- `wx.LogError` uses printf-style formatting. Escape literal percent signs before passing user/provider text into it.
- `sitecustomize.py` must remain a shim. The internal player implementation belongs in `internal_player.py` only.
- EPG auto-import should be based on usable joined EPG data and source freshness, not just the presence or mtime of `epg.db`. `_ensure_db_tuned()` must not create an empty placeholder database.
- EPG matching must account for country-specific channel aliases and suffixes, especially AU/CA/IE/UK/US sources. IPTV-org style XMLTV IDs with `@` suffixes need expansion for better channel matching.
- XMLTV downloads can resume, but HTTP 416 means the local partial file is already complete or invalid for that source; the downloader has fallback logic for this and should keep it.
- Live stream VLC options should allow late-frame dropping/skipping so playback can catch up to real time. Catch-up/VOD can use stricter frame options.
- Current internal-player live buffering targets are intentionally low-latency: roughly 2.0-3.5 seconds depending on stream hints, bounded by user config. Xtream-style refresh should wait for sustained buffering instead of restarting on tiny blips.
- Some Xtream-style live TS servers end the HTTP response periodically. Live `.ts`/MPEG-TS handling should reopen cleanly without consuming normal reconnect-attempt budget.
- VLC can start muted with dummy/hidden interfaces. `_schedule_volume_apply()` explicitly unmutes before applying volume.
- `CastingManager` needs one persistent background asyncio loop. Do not return to per-action event loops for libraries like `pyatv` and `aiohttp`.
- Chromecast compatibility depends on the proxy paths in `stream_proxy.py`: MPEG-TS detection, HLS remux/transcode, bootstrap HLS, clean segment settings, and audio transcode/direct-proxy choices.
- The stream proxy's Windows Firewall rule is best effort. Failure to run `netsh` should log a warning and not block casting.
- Auto-update is for packaged Windows builds. The helper script uses PowerShell parameter names (`-ParentPid`, `-InstallDir`, `-StagingDir`, `-BackupDir`, `-ExeName`), not GNU-style flags.
- Authenticode verification must use Windows PowerShell 5.1 with a clean environment because PowerShell Core module paths can break `Get-AuthenticodeSignature` from Python subprocesses.
- Update installs preserve a user's existing `iptvclient.conf` from backup when present. This is different from bundling a repo config file in a release, which must not happen.
- PyInstaller hidden imports for chardet mypyc modules are required for clean builds in the current environment.

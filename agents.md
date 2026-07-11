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
- **updater.py**, **update_helper.bat**, **update_helper.ps1**: Windows packaged-app updater. Uses a GitHub release manifest, SHA-256 validation, Authenticode verification with pinned thumbprints, a fully silent helper launch (no console window) driven from an accessible `wx.ProgressDialog`, backup, rollback, and local config preservation. Every update subprocess goes through `updater.run_hidden`/`updater.popen_hidden` so nothing flashes a console.
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

## Internationalization (i18n)

- **i18n.py** is a self-contained, standard-library-only (gettext) translation layer. It installs `_()` and `ngettext()` as Python builtins (the documented `gettext.install` idiom) so any module can call `_("text")`. Modules that use it also do `from i18n import gettext as _` at the top, both to keep static analysis happy and because the function consults the *currently active* catalogue on every call (so switching language at startup works without re-importing).
- User-facing strings throughout `main.py`, `internal_player.py`, `playlist.py`, `options.py`, `providers.py`, `updater.py`, and `external_player.py` are wrapped in `_()`. Dynamic text uses translatable templates with `.format()` (e.g. `_("Casting to {device}...").format(device=name)`) — never f-strings, because gettext/xgettext cannot extract an f-string.
- **`_` is also a throwaway/`lambda _:` parameter name all over this codebase.** That is fine in scopes that never call `_()`. Where a handler both takes a `_` parameter (or unpacks `url, _ = ...`) *and* needs to translate, the local was renamed (`_event`, `_unused`). If you add a `_()` call inside a function whose event/throwaway is named `_`, rename that local or you will call a non-callable.
- Strings that double as internal keys are NOT translated as keys: the `"All Channels"` group sentinel and the `media_player` config values (`"Built-in Player"`, `"Custom"`, brand names in `PLAYER_KEYS`) stay English internally; only their *display* is wrapped (`_(label)` in the menu, `_("All Channels")` in the group list, with `on_group_select` matching both the translated and English forms).
- **No `wx.Locale`.** It flips the process `LC_NUMERIC`, which would break the `2.5`-style floats fed to libVLC options and config. Translate via gettext only; wx stock button labels (OK/Cancel) stay in wx's own language.
- Language preference lives in `iptvclient.conf` under `language` ("auto"/"en"/"hu"...), defaulted in `options.load_config`. `IPTVClient.__init__` calls `i18n.init_from_config(self.config)` *before* building the UI. The **Options > Language** submenu (built in both the Windows/macOS menubar and the Linux button-menu) writes the setting and prompts for a restart (existing menus/labels are not rebuilt live).
- Catalogues live under `locale/<lang>/LC_MESSAGES/iptvclient.{po,mo}` plus the `locale/iptvclient.pot` template. English is the source language (no catalogue needed — gettext returns the msgid). Hungarian (`hu`) ships translated.
- **`tools/i18n_tools.py`** is dependency-free tooling (pure-Python AST extractor + pure-Python `.mo` compiler — no GNU gettext/Babel/polib needed):
  - `python tools/i18n_tools.py extract` — rebuild `locale/iptvclient.pot` from `_()`/`ngettext()` calls.
  - `python tools/i18n_tools.py update` — fold new POT strings into each existing `.po`, keeping translations.
  - `python tools/i18n_tools.py compile` — compile every `.po` → `.mo`.
  - `all` — extract + update + compile. After editing any `.po`, recompile; `tests/test_i18n.py::test_committed_mo_matches_po` fails if the committed `.mo` is stale, and `test_translation_placeholders_match_source` fails if a translation drops a `{token}`.
- **`main.spec` recompiles every `.po` → `.mo` at build time** (via `i18n_tools.cmd_compile()`) and bundles `locale/<lang>/LC_MESSAGES/*.mo` as datas, so a release can never ship a stale or missing catalogue. `i18n.locale_dir()` resolves to `sys._MEIPASS/locale` when frozen.
- To add a language: `python tools/i18n_tools.py update` to create/seed `locale/<code>/LC_MESSAGES/iptvclient.po` (or copy the `.pot`), translate the msgstrs, `compile`, then add `(code, "Native name")` to `i18n._LANGUAGE_LABELS` and `code` to `SHIPPED_CATALOGS`.

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

- Windows installer builds use Inno Setup with a `.windows-installed` marker in Program Files. Installed/runtime mutable state belongs under `%APPDATA%\AccessibleIPTVClient`; Program Files should contain only application binaries and bundled assets, and installed auto-updates should use the signed setup EXE rather than replacing Program Files directly.
- `wx.LogError` uses printf-style formatting. Escape literal percent signs before passing user/provider text into it.
- `sitecustomize.py` must remain a shim. The internal player implementation belongs in `internal_player.py` only.
- Startup must stay lazy: do not run FFmpeg probes/installs, import casting stacks (`pychromecast`, `async_upnp_client`, `pyatv`), start the stream proxy/firewall rule, or import the built-in VLC player during `main.py` import or `IPTVClient.__init__`. Initialize those only when recording, casting, or built-in playback is actually requested.
- EPG auto-import should be based on usable joined EPG data and source freshness, not just the presence or mtime of `epg.db`. `_ensure_db_tuned()` must not create an empty placeholder database.
- EPG matching must account for country-specific channel aliases and suffixes, especially AU/CA/IE/UK/US sources. IPTV-org style XMLTV IDs with `@` suffixes need expansion for better channel matching.
- XMLTV downloads can resume, but HTTP 416 means the local partial file is already complete or invalid for that source; the downloader has fallback logic for this and should keep it.
- Live stream VLC options should allow late-frame dropping/skipping so playback can catch up to real time. Catch-up/VOD can use stricter frame options.
- Current internal-player live buffering targets are intentionally low-latency: roughly 2.0-3.5 seconds depending on stream hints, bounded by user config. Xtream-style refresh should wait for sustained buffering instead of restarting on tiny blips.
- Some Xtream-style live TS servers end the HTTP response periodically. Live `.ts`/MPEG-TS handling should reopen cleanly without consuming normal reconnect-attempt budget.
- VLC can start muted with dummy/hidden interfaces. `_schedule_volume_apply()` explicitly unmutes before applying volume.
- `CastingManager` needs one persistent background asyncio loop. Do not return to per-action event loops for libraries like `pyatv` and `aiohttp`.
- Chromecast compatibility depends on the proxy paths in `stream_proxy.py`: MPEG-TS detection, HLS remux/transcode, bootstrap HLS, clean segment settings, and audio transcode/direct-proxy choices.
- Chromecast HLS proxying must normalize channel HTTP metadata before `urllib` requests. Do not pass `_extra` header lists through to `urllib.request.Request`; expand them into normal string header names/values first.
- The bundled FFmpeg 8.x HLS muxer does not accept `-hls_version`; let FFmpeg write the playlist version from the selected HLS muxer options.
- When rewriting FFmpeg HLS playlists for Chromecast, preserve FFmpeg's media playlist tags and only rewrite segment URIs. Injecting duplicate `#EXT-X-TARGETDURATION` or an out-of-place `#EXT-X-DISCONTINUITY` can make Chromecast reject the load before requesting segments.
- Chromecast can get stuck polling the playlist after starting from the bootstrap HLS segment. Prefer waiting several seconds for FFmpeg's real playlist, and only serve bootstrap after upstream media bytes have arrived; no-data startup failures should return a temporary failure instead of fake playback.
- Chromecast HLS video should use a Chromecast-safe H.264/AAC profile. Copying HEVC/H.265 video into MPEG-TS HLS can make Chromecast fetch the first segment and then stop with `idleReason='ERROR'`.
- Chromecast recasts of the same stream need a fresh HLS session URL and no-cache playlist/segment responses. Reusing the same moving live playlist/content ID can make Chromecast resume at the live edge and stall after a few segments.
- Chromecast recasts or channel changes should stop previous fresh Chromecast HLS converters immediately. Letting old HLS converters run until timeout can keep upstream network and FFmpeg CPU active during the next cast.
- Hisense/Chromecast receivers may request early HLS segments after a long startup delay. Do not rely on FFmpeg `delete_segments`/`hls_delete_threshold` for the Chromecast path; keep a proxy-managed backlog so delayed segment requests do not 404.
- Some FFmpeg startup HLS segments can be large enough to pass a size check but still contain incomplete AAC metadata such as zero channels or an unspecified sample rate. For Chromecast-safe HLS, drop the first few startup segments and require a stable playlist window before serving it.
- If Chromecast startup filtering drops every currently available HLS segment, do not fall back to serving the unfiltered playlist. Treat it as not ready until at least one post-startup segment is available.
- Chromecast startup segment filtering must key off absolute FFmpeg segment numbers such as `seg_1.ts` through `seg_3.ts`. Do not drop the first entries of every later sliding HLS playlist window.
- Some live TS upstreams close HTTP responses while the channel is still live. The Chromecast HLS pump should reopen the upstream after EOF once media data has been received instead of closing FFmpeg stdin.
- Audio/radio proxy FFmpeg processes must terminate when the client disconnects. Stale transcoders can keep consuming CPU and cause Chromecast video buffering.
- The stream proxy's Windows Firewall rule is best effort. Failure to run `netsh` should log a warning and not block casting.
- Auto-update is for packaged Windows builds. The helper script uses PowerShell parameter names (`-ParentPid`, `-InstallDir`, `-StagingDir`, `-BackupDir`, `-ExeName`), not GNU-style flags.
- Automatic update checks should be throttled and use short metadata timeouts; interactive update checks/downloads may use longer waits. Do not schedule passive GitHub checks before the initial playlist load has yielded UI.
- Authenticode verification must use Windows PowerShell 5.1 with a clean environment because PowerShell Core module paths can break `Get-AuthenticodeSignature` from Python subprocesses.
- Installed updates keep `iptvclient.conf` in `%APPDATA%\AccessibleIPTVClient`; portable zip updates preserve or migrate `iptvclient.conf` beside `IPTVClient.exe`. This is different from bundling a repo config file in a release, which must not happen.
- PyInstaller hidden imports for chardet mypyc modules are required for clean builds in the current environment.
- AirPlay casting must go through `stream_proxy.py` for the same reasons as Chromecast: provider auth headers are lost otherwise, and Apple TV requires HLS for live MPEG-TS. Video routes through `get_transcoded_url(..., transcode_profile="chromecast_h264")` and is passed to `stream.play_url`. Audio routes through `get_audio_url` and `stream.stream_file`; pyatv >= 0.16 accepts `http(s)://` URLs there via `InternetSource`.
- Audio-only AirPlay receivers (HomePod-style devices) advertise AirPlay + RAOP but no Companion service. They raise `pyatv.exceptions.NotSupportedError` on `play_url`. Detect with `get_service(Protocol.Companion)` and fall back to RAOP `stream_file` via the audio proxy URL so radio still casts.
- `stream_file` is a long-running coroutine — wrap it in an `asyncio.Task` on the CastingManager's background loop and cancel it from `stop()`/`disconnect()`. Awaiting it inline would block every subsequent cast operation.
- When `CastingManager.play()` raises, `main.py:_launch_stream` must call `self.caster.disconnect()` before reporting the error. Otherwise the user is pinned to a dead device and every channel change re-attempts the same failing cast.
- Chromecast's Cast SDK manifest fetch has an internal timeout of ~8–10 seconds; the proxy MUST NOT hold the `/transcode/.../stream.m3u8` GET open longer than that or the receiver fires `MEDIA_LOAD_FAILED` → IDLE/ERROR within ~5s, before any segment ever ships. Current tuning: base 8s + 4s extended ceiling for the inner wait. If FFmpeg isn't ready in that window but upstream bytes ARE arriving, serve the bootstrap playlist (1s black segment) so the receiver gets a valid response immediately and re-polls — this beats 503 even though Chromecast can briefly poll the bootstrap before transitioning. The bootstrap path applies to fresh-session profiles like `chromecast_h264` too; the older "skip bootstrap for fresh sessions" rule caused worse failures than the get-stuck-on-bootstrap edge case it was avoiding.
- 503 from the proxy playlist endpoint is reserved for genuine failures only (no upstream data arriving at all). `can_serve_bootstrap()` must return True before any bootstrap fallback is served, so streams that are truly unreachable still fail clearly instead of looping on a black segment.
- `pychromecast.MediaController.block_until_active` returns when the receiver accepts the launch, not when playback begins. After it returns, poll `media_controller.status` for up to ~20 seconds and raise `PlaybackError` if the state stays IDLE or hits `idle_reason == "ERROR"`. Do NOT treat `INTERRUPTED` as terminal — Chromecast uses it as a transitional state while the HLS player loads, and slow upstreams routinely stay INTERRUPTED for 10–15s before transitioning to BUFFERING.
- PyInstaller `--noconsole` / `console=False` builds set `sys.stderr` (and `sys.stdout`) to `None`. `http.server.BaseHTTPRequestHandler.log_message` writes directly to `sys.stderr`, so its default implementation raises `AttributeError: 'NoneType' object has no attribute 'write'` on the FIRST line of every response (send_response → log_request → log_message). The exception propagates, the handler thread dies, and clients see an empty reply / `curl: (52) Empty reply from server`. `StreamProxyHandler` MUST override both `log_message` and `log_error` to route through the project's `LOG` (or swallow) so the bundled exe can actually serve responses. Source-tree runs hide this bug because a console stderr exists.
- `tests/test_i18n.py` requires the Hungarian catalogue to be fully translated. After adding user-facing strings and running `python tools/i18n_tools.py all`, fill every new `locale/hu/LC_MESSAGES/iptvclient.po` `msgstr` before compiling, or the i18n test will fail.
- FFmpeg 8.x on Windows can treat finite MPEG-TS HTTP fixture responses as connection resets even with Content-Length. For recorder/DVR end-to-end tests, prefer explicit BaseHTTPRequestHandler live-style fixtures that repeat a small MPEG-TS file, catch BrokenPipeError/ConnectionResetError/OSError, and stop FFmpeg with an explicit recording duration.
- Do not patch update manifest JSON with PowerShell `Set-Content`; it can write a UTF-8 BOM, and same-name GitHub release asset replacements may be served from cache for a while. Prefer regenerating manifests through `tools/release.py` or explicitly writing UTF-8 without BOM.

- Large existing EPG databases can make _ensure_db_tuned() a multi-second operation when an index is missing (observed 5.6 GB epg.db, 16M programmes, 14s index creation). Never run EPG DB tuning before the main frame is shown; keep it deferred/background or tied to actual EPG import/query work.
- Keep `_ensure_db_tuned()` index creation consistent with `EPGDatabase._create_tables()`: never recreate the redundant `(channel_id, start)` index after the database layer drops it, because rebuilding it over a multi-gigabyte EPG can saturate disk/CPU during startup and make unrelated UI actions such as search appear frozen.
- Replacing virtual channel-list search/group rows must clear the active selected/focused item state even when its numeric index remains in range. During a shrink, change the native item count while the old model still supplies every remaining row, then swap the model; during a grow, install the new model before increasing the count. This prevents NVDA/MSAA from querying stale or out-of-range virtual rows.
- `build.bat release` prepends a readable version/date entry to `CHANGELOG.md` from the generated release notes before the version commit and tag. Keep `CHANGELOG.md` staged with `app_meta.py`; historical entries were reconstructed from the Forgejo mirror.

<!-- claude-memory:begin (managed by sync-claude-memory.py; canonical files live in C:\Users\admin\.claude - edit there, not here) -->
## Memories (shared from ~/.claude - project: c--Users-admin-git-Accessible-IPTV-Client)
@C:\Users\admin\.claude\projects\c--Users-admin-git-Accessible-IPTV-Client\memory\MEMORY.md
@C:\Users\admin\.claude\projects\c--Users-admin-git-Accessible-IPTV-Client\memory\epg-import-robustness.md
@C:\Users\admin\.claude\projects\c--Users-admin-git-Accessible-IPTV-Client\memory\epg-source-support-vs-integration.md
@C:\Users\admin\.claude\projects\c--Users-admin-git-Accessible-IPTV-Client\memory\hungarian-localization.md
@C:\Users\admin\.claude\projects\c--Users-admin-git-Accessible-IPTV-Client\memory\large-playlist-optimization.md
@C:\Users\admin\.claude\projects\c--Users-admin-git-Accessible-IPTV-Client\memory\nvda-search-crash-fix.md
@C:\Users\admin\.claude\projects\c--Users-admin-git-Accessible-IPTV-Client\memory\pytest-basetemp-permission-workaround.md
@C:\Users\admin\.claude\projects\c--Users-admin-git-Accessible-IPTV-Client\memory\release-workflow.md
@C:\Users\admin\.claude\projects\c--Users-admin-git-Accessible-IPTV-Client\memory\search-freeze-during-epg-import.md
@C:\Users\admin\.claude\projects\c--Users-admin-git-Accessible-IPTV-Client\memory\startup-cpu-fixes.md
@C:\Users\admin\.claude\projects\c--Users-admin-git-Accessible-IPTV-Client\memory\subagent-worktree-resume-caveat.md
<!-- claude-memory:end -->

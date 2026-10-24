You are a professional Windows Python developer with a decade of IPTV app experience. Always fully investigate things before applying a fix. If you learn anything new that affects future work on this repo, write it in the matching file under `docs/learnings/`, or here when every run needs it.

Saved player buffer durations are explicit user choices. Preserve them on load; new defaults apply to missing values. Cover 2, 4, and 12 seconds in config round-trip tests.

Live playback starts on half a second and then fills the buffer at full speed. Filling must never slow playback down: a rate under 1.0 was the only way to grow a cushion locally, it made speech drag, and the buffer worth having is the one the server hands over ahead of real time. The player therefore never touches the media player's rate (2026-10-17); `tests/test_live_cushion.py` guards that, and the Android app's Cushion.kt paired with a server-side bank is the model. The default maximum is 30 seconds; migrate the old saved 18-second maximum to 30 so it cannot cap the cushion. Other saved maximums and base durations stay explicit choices.

Dispatcharr channels keep the saved buffer alone: it restreams from its own server-side buffer, so a stall reconnects without the client raising its cache. Detection is free from the playlist header - `catchup-timezone` is an attribute Dispatcharr introduced in its XC `/live/` M3U (`_parse_m3u_return` marks every channel of such a playlist with `dispatcharr`), and its XC API says `user_info.message = "Dispatcharr XC API"` if a provider is ever added as Xtream instead. The marker reaches `InternalPlayerFrame.play(dispatcharr=...)` and stops `_schedule_restart` from stepping the cache up for a live stream; it must not affect how fast anything plays, and archive streams still grow.

Keep the half-second first-start cache separate from the saved buffer and full-cache recovery; saved buffer durations remain explicit choices. Both A/V and 500 ms presentation-clock watchdogs wait 10 seconds, and startup grace includes the cache duration. Prolonged buffering uses backed-off recovery with gradual cache increases, never the fast TS-ended refresh path. A bigger client cache delays first sound. For bursty restreamed sources, use already-banked server history instead: Dispatcharr's eight-second startup-position cap bypassed its configured 15-second SceneTime reserve, and PCR pacing did not build more afterward. A local real-libVLC test started within one second with a two-second client cache; an injected eight-second source gap paused playback with eight seconds of server history but not with 15. Cold sources and outages beyond the available reserve can still pause.

Normal live TS segment rollovers also use the half-second opening cache. They are not stalls: reopening every segment with the full saved recovery cache adds avoidable delay (25 seconds at the default). Actual stall recovery and archive playback still use the saved cache. Recording-relay history must be bounded by elapsed time as well as bytes; two MiB can represent minutes of low-bitrate audio. Slow relay readers must discard expired history rather than keep old chunks while dropping new ones. Neither mechanism alone establishes the cause of a delay reported during ordinary fresh playback with a saved half-second cache.

You are root on this Windows machine and can install and use whatever is needed with winget, PowerShell, Chocolatey, pip, or other package managers.

Make sure the PyInstaller spec file includes all runtime requirements, dynamic imports, binary assets, and needed submodules for the build.

When building, always check for warnings, errors, and dependency mismatches in the build output. If any are found, fix them before proceeding. Never ship a build that had unresolved warnings or errors.

## Agent skills

### Issue tracker

GitHub issues on the fork `thebetterfarhan/Accessible-IPTV-Client` (pass `--repo`, since `gh` infers the upstream `origin`). See `docs/agents/issue-tracker.md`.

### Triage labels

Default canonical roles: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Project Overview

Project = Accessible IPTV Client, a wxPython GUI focused on playlist loading, EPG import/search/matching, accessible channel browsing, internal/external playback, casting, and Windows self-updates.

`main.py` creates the main frame, tray icon, playlist/EPG managers, channel/group/search UI, background playlist and EPG work, player launching, casting actions, and update checks. `options.py` owns config persistence, cache paths, database paths, and config normalization.

## Architecture

- **main.py**: Main wx frame (`IPTVClient`), tray restore behavior, playlist and EPG managers, channel list population, group filtering, search including EPG search, catch-up dialog, internal/external player launch, casting menu actions, and update prompts. The frame borrows `UiMixin` (`client_ui.py`, the window and menu construction), `M3uCacheMixin` (`client_m3u.py`, playlist parsing and its cache) and `EpgRoutingMixin` (`client_epg.py`, guide rows and live/catch-up URL choice), plus `RecordingReportsMixin` (`client_recording.py`, what is said when a recording finishes); dialogs without their own module live here. Pure helpers sit outside it: `playlist_headers.py` (M3U header/EPG attributes), `catchup_urls.py` (catch-up and timeshift URLs, ffmpeg failure reasons), `dialog_utils.py`, `app_links.py`, plus `dialogs_misc.py` and `channel_widgets.py` for dialogs and controls that never call `message_box`. A moved name stays re-exported from `main` when tests or tools read it there.
- **internal_player.py**: Built-in libVLC player with adaptive buffering, stream preflight checks, live/catch-up option handling, automatic reconnect logic, fullscreen (F11), play/pause/stop controls, accessible control names, and volume slider. Volume uses 2% normal steps and 5% Ctrl+Up/Down steps.
- **sitecustomize.py**: Compatibility shim only. It re-exports the canonical `InternalPlayerFrame` from `internal_player.py` and must not grow separate player logic.
- **playlist.py**: XMLTV import/search/matching and the guide-to-playlist matcher. The EPG database is SQLite in `tempfile.gettempdir()` via `options.get_db_path()`, uses WAL and busy timeouts, logs debug details to `iptvclient_epg_debug.log` in the temp directory, and handles XML/GZip downloads with resume plus HTTP 416 fallback. Parsing an M3U text lives in `client_m3u.py` (`M3uCacheMixin`); `main._parse_m3u_return` is the same function.
- **channel_names.py**: Single source of truth for channel-name normalization and country/group detection (`STRIP_TAGS`, `NOISE_WORDS`, `group_synonyms`, `canonicalize_name`, `strip_noise_words`, `extract_group`). Stdlib-only and dependency-free so both `playlist.py` and `options.py` can import it without a cycle (`playlist` already imports `options`). `playlist.py` re-exports these names for existing callers. Never re-implement or copy these helpers into another module: the UI and the EPG database must normalize names identically or matching silently fails.
- **channel_identity.py**: Which guide channel a playlist channel is. Stdlib-only and wx-free: `expand_tvg_id_candidates` (XMLTV id variants), `guide_indexes` (the guide's channels by id, by name and by noise-stripped name, every channel kept per key in guide order), and `match_guide_channel` (tvg-id first as identity, then names with the number rule). Parsing a playlist's M3U text stays in `client_m3u.py`; the guide-to-playlist matcher stays in `playlist.py`.
- **providers.py**: Xtream Codes and Stalker Portal clients for building playlist/EPG URLs, handling auth/session state, and surfacing `ProviderError`. `get_account_info()` on each client returns the provider's subscription record (`player_api.php` with no action for Xtream; `type=account_info&action=get_main_info` for Stalker).
- **account_info.py**: Provider account status (File > Account Info). wx-free: discovers accounts (configured providers plus accounts autodetected from `get.php?username=…` playlist URLs and `/live/USER/PASS/1234.ts` channel URLs), fetches them, and formats a flat `Label: value` report. The dialog itself is `main.AccountInfoDialog`.
- **options.py**: JSON config persistence. Reads portable/app, cwd, user config, and frozen `_MEIPASS` candidates; writes to the app/cwd path when possible and otherwise the user config path. Also provides cache path hashing, default config values, and config clamping. Name-normalization helpers live in `channel_names.py`, not here.
- **favorites.py**: Favorite-channel identity. Stdlib-only and wx-free: builds the provider-stable key a favorite is stored under, filters the playlist by those keys, and owns the `Favorites` category sentinel. Never key a favorite on the resolved stream URL.
- **user_guide.py** and **docs/help/<lang>.md**: the offline User Guide and F1 context help. `user_guide.py` is wx-free: it renders a small Markdown subset to plain text, splits it into sections by `{#topic-id}` heading anchors, picks the guide for `i18n.resolved_language()` and falls back to English (whole file, and per topic). `main.UserGuideDialog` shows it in one read-only `TE_RICH2` text box with a Topics list and Find. Controls and dialogs carry a `help_topic` (class attribute, `user_guide.set_help_topic`, or a callable for controls whose meaning changes); menu items are mapped with `user_guide.set_menu_help(owner, item_or_menu, topic)`. `tests/test_user_guide.py` fails when code asks for a topic `en.md` does not have. `main.spec`, `tools/build_deb.py` and `tools/release.py` all ship/verify `docs/help`.
- **power.py**: "Shut down when recording is finished". Stdlib-only and wx-free: the per-platform shutdown commands and the `should_shutdown` rule. `main.py` owns the menu item, the confirmation and the cancellable countdown.
- **casting.py**: Persistent background asyncio loop for cast operations. Supports Chromecast, DLNA/UPnP, and AirPlay when optional libraries are installed.
- **stream_proxy.py**: Local stream proxy for casting. Handles direct byte proxying, HLS remux/transcode, Chromecast-safe HLS output, radio/audio mode, Python-to-FFmpeg piping for provider auth headers, bootstrap HLS startup, and best-effort Windows Firewall rules.
- **updater.py**, **update_helper.ps1**: Windows packaged-app updater. The app starts the helper with Windows PowerShell directly (never through `cmd /c`, which splits a helper path containing a space) and grants it foreground rights so its status window and the installer's UAC prompt are really shown. Uses a GitHub release manifest, SHA-256 validation, Authenticode verification with pinned thumbprints, a fully silent helper launch (no console window) driven from an accessible `wx.ProgressDialog`, backup, rollback, and local config preservation. Every update subprocess goes through `updater.run_hidden`/`updater.popen_hidden` so nothing flashes a console.
`tools/smoke_favorites_shutdown.py` and `tools/smoke_virtual_list_nvda.py` are GUI smoke tools for the wx behaviour pytest cannot reach (menu items, virtual-list focus events, real libVLC construction). Run them after touching the channel list, the favorites category, the player's audio-track menu or the shutdown countdown.

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
- Provider account status (expiry, trial flag, connection limits) for configured and autodetected accounts, under File > Account Info.
- Channel grouping, channel search, and EPG search.
- System tray minimize/restore support.
- Windows packaged auto-update support.
- Cross-platform source app support for Windows, Linux and macOS, with the release pipeline focused on Windows. The macOS app (`tools/build_macos.sh`, `main.spec` BUNDLE) bundles Homebrew's ffmpeg and VLC.app's libVLC and plugins; `main.py` puts the bundle on PATH and sets `PYTHON_VLC_LIB_PATH`/`PYTHON_VLC_MODULE_PATH` when frozen, because Finder-launched apps get no Homebrew PATH. The in-app updater stays Windows-only (macOS gets the existing "only supported on Windows builds" message). It is built only by the cloud release, on macOS runners.

## Config File (`iptvclient.conf`)

Important keys include `playlists`, `epgs`, `media_player`, `custom_player_path`, `internal_player_buffer_seconds`, `internal_player_max_buffer_seconds`, `internal_player_variant_max_mbps`, `epg_enabled`, `epg_auto_import_interval_hours`, `minimize_to_tray`, `show_player_on_enter`, `auto_check_updates`, `favorites`, `preferred_audio_tracks`, `prefer_audio_description`, and `shutdown_after_recordings`.

`favorites` is a list of `favorites.channel_key()` strings, `preferred_audio_tracks` a list of track-name/language keywords in priority order. Both are clamped by `options.normalize_channel_and_audio_settings()` on every load and save, so a hand-edited config cannot crash startup.

`iptvclient.conf` is user-local runtime configuration. Do not bundle a local repo `iptvclient.conf` into public releases.

## Casting

Casting is Caster's code (github.com/serrebidev/Caster), not a re-implementation. `caster_engine.py` (the GUI-free top of Caster's `caster.py`: probing, HLS relay, TsSource, Device), `caster_extras.py`, `caster_devices.py` and `caster_config.py` are generated by `python tools/sync_caster.py` from a Caster checkout (default `../Caster`). Never edit them here: fix Caster, then sync. `casting.py` is this app's replacement for Caster's `MainFrame` play/stop/recovery logic: Chromecast, AirPlay (RAOP audio, no pairing), UPnP/DLNA, Sonos, Roku and Kodi.

- Channel headers: the engine and receivers fetch URLs with their own headers, so a channel with headers goes through the stream proxy's `/g/` header gateway (`StreamProxy.get_gateway_url`). The gateway keeps the upstream path so relative playlist URIs resolve through it, and rewrites absolute ones.
- One-stream providers: pass `exclusive=True` to `CastingManager.play`; probing, codec detection and the relay then run one after another with `catchup_direct.settle_media_session()` between them.
- Chromecast fresh transcode sessions need unique IDs: Windows `time.time_ns()` can repeat. Use `secrets.token_hex` and keep the existing converter retirement when a fresh session replaces the old one.
- Speakers (Sonos, audio-only UPnP renderers) get a TV channel as MP3 through the proxy's audio path.
- Live tests (`tests/test_cast_live.py`, `IPTV_RUN_LIVE_CAST_TESTS=1`) may only target R&B Room (Cast name "RB Room").
- Debian: pyatv needs compiled modules, so the Architecture: all `.deb` cannot carry it. postinst builds `/usr/lib/accessible-iptv-client/venv` (`--system-site-packages`) and pip-installs the casting libraries; the launcher prefers that Python; postrm removes it. `tools/deb_smoke_test.sh` checks it.

## Dependencies

Runtime requirements are defined in `requirements.txt`: `wxPython`, `python-vlc`, `pychromecast`, `pyatv`, `zeroconf`, `soco`, and `chardet>=7.0.0`. `pytest` is listed for development/testing.

`chardet` is pinned because `main.spec` does `import chardet.pipeline` at spec-parse time and bundles its mypyc modules by name. That subpackage only exists in chardet 7.0.0+; on 6.x or earlier the release build dies with `ModuleNotFoundError` before PyInstaller starts. Anything `main.spec` imports directly must be pinned in `requirements.txt`.

The standalone Windows build also explicitly collects dynamic modules and metadata in `main.spec`, including casting/network stacks, VLC, updater/signing dependencies, `psutil`, and chardet mypyc modules. Keep `main.spec` in sync whenever imports or optional runtime features change.

## Internationalization (i18n)

- **i18n.py** is a self-contained, standard-library-only (gettext) translation layer. It installs `_()`, `ngettext()` and `N_()` as Python builtins (the documented `gettext.install` idiom) so any module can call `_("text")`. Modules that use it also do `from i18n import gettext as _` at the top, both to keep static analysis happy and because the function consults the *currently active* catalogue on every call (so switching language at startup works without re-importing).
- User-facing strings throughout `main.py`, `client_ui.py`, `dialogs_misc.py`, `channel_widgets.py`, `catchup_urls.py`, `client_epg.py`, `client_recording.py`, `internal_player.py`, `playlist.py`, `options.py`, `providers.py`, `updater.py`, and `external_player.py` are wrapped in `_()`. Dynamic text uses translatable templates with `.format()` (e.g. `_("Casting to {device}...").format(device=name)`) — never f-strings, because gettext/xgettext cannot extract an f-string.
- **`_` is also a throwaway/`lambda _:` parameter name all over this codebase.** That is fine in scopes that never call `_()`. Where a handler both takes a `_` parameter (or unpacks `url, _ = ...`) *and* needs to translate, the local was renamed (`_event`, `_unused`). If you add a `_()` call inside a function whose event/throwaway is named `_`, rename that local or you will call a non-callable.
- Strings that double as internal keys are NOT translated as keys: the `"All Channels"` group sentinel and the `media_player` config values (`"Built-in Player"`, `"Custom"`, brand names in `PLAYER_KEYS`) stay English internally; only their *display* is wrapped (`_(label)` in the menu, `_("All Channels")` in the group list, with `on_group_select` matching both the translated and English forms).
- **A deferred `_(variable)` still needs the msgid extracted.** `i18n.N_()` is the marker for that: it returns its argument unchanged (so the key stays English) but the extractor records the string, so the later `_(label)` has something to look up. `PLAYER_KEYS[0]` uses `N_("Built-in Player")` for exactly this reason — the other entries are brand names that are the same in every language. If you add another indirectly-translated key, wrap it in `N_()` or it will silently stay English in all catalogues.
- **No `wx.Locale`.** It flips the process `LC_NUMERIC`, which would break the `2.5`-style floats fed to libVLC options and config. Translate via gettext only; wx stock button labels (OK/Cancel) stay in wx's own language.
- Language preference lives in `iptvclient.conf` under `language` ("auto"/"en"/"hu"...), defaulted in `options.load_config`. `IPTVClient.__init__` calls `i18n.init_from_config(self.config)` *before* building the UI. The **Options > Language** submenu (built in both the Windows/macOS menubar and the Linux button-menu) writes the setting and prompts for a restart (existing menus/labels are not rebuilt live).
- Catalogues live under `locale/<lang>/LC_MESSAGES/iptvclient.{po,mo}` plus the `locale/iptvclient.pot` template. English is the source language (no catalogue needed — gettext returns the msgid). Thirteen catalogues ship fully translated (`i18n.SHIPPED_CATALOGS`): `es ar pt fr de ru tr it pl hi zh ja hu`.
- **`tools/i18n_tools.py`** is dependency-free tooling (pure-Python AST extractor + pure-Python `.mo` compiler — no GNU gettext/Babel/polib needed):
  - `python tools/i18n_tools.py extract` — rebuild `locale/iptvclient.pot` from `_()`/`gettext()`/`N_()`/`ngettext()` calls.
  - `python tools/i18n_tools.py update` — fold new POT strings into each existing `.po`, keeping translations.
  - `python tools/i18n_tools.py compile` — compile every `.po` → `.mo`.
  - `python tools/i18n_tools.py notes` — rebuild `locale/release_notes.pot` from the newest three CHANGELOG entries and fold it into every language's `release_notes.po` (may stay partly untranslated; see the release-notes learning below).
  - `all` — extract + update + notes + compile. After editing any `.po`, recompile; `tests/test_i18n.py::test_committed_mo_matches_po` fails if the committed `.mo` is stale, and `test_translation_placeholders_match_source` fails if a translation drops a `{token}`.
- **`main.spec` recompiles every `.po` → `.mo` at build time** (via `i18n_tools.cmd_compile()`) and bundles `locale/<lang>/LC_MESSAGES/*.mo` as datas, so a release can never ship a stale or missing catalogue. `i18n.locale_dir()` resolves to `sys._MEIPASS/locale` when frozen.
- To add a language: `python tools/i18n_tools.py update` to create/seed `locale/<code>/LC_MESSAGES/iptvclient.po` (or copy the `.pot`), translate the msgstrs, `compile`, then add `(code, "Native name")` to `i18n._LANGUAGE_LABELS` and `code` to `SHIPPED_CATALOGS`.

## Current Release Build Rules

- Use `build.bat release` for public releases. `build.bat` calls `build_exe.bat`, which calls `tools/release.py`; running `build.bat` with no argument performs a local build only.
- Each `release_notes.po` msgstr is that one language's text. v1.145.0 shipped two bullets whose msgstr in all 12 languages was the Python repr of a `{lang: text}` dict, so What's New read the whole table aloud; when filling translations by script, write `table[lang]`, never the table. `audit_notes` now rejects a msgstr shaped like a language table.
- Every release is gated by a translation audit of every shipped language except Hungarian (`tools/translation_audit.py`, exempt by the maintainer's request). `release.py release` runs `translation_audit.require_complete()` before it writes `app_meta.py` or `CHANGELOG.md`, and `dry-run` prints the same report. It fails on: an `iptvclient` string that is missing, empty, an English copy not listed in `locale/identical_ok.json`, or drops a `{placeholder}`; a `docs/help/<lang>.md` whose anchored sections or per-section bullet/paragraph counts differ from `en.md`, that still contains an English line, or whose `docs/help-sync.json` stamp (git blob id of `en.md`) is not the current `en.md`; an empty What's New bullet among the three releases the new version will show, including its own bullets. Workflow before releasing: `python tools/translation_audit.py` to see problems; after translating English guide changes (the failure prints the `git diff <old> <new>` of `en.md`), `python tools/translation_audit.py mark-help-synced <langs>`; commit everything; then `python tools/translation_audit.py prepare-notes` adds the upcoming release's bullets to each `release_notes.po`, translate them and run `build.bat release` **without committing them** (the release sync keeps them and the release commit stages `locale/`; committed extra msgids would fail `test_committed_notes_catalogues_cover_the_current_window`). Every commit, `chore:` included, becomes a bullet, so do not commit after `prepare-notes`.
- Starting the release from an agent shell: run `cmd /d /c "<repo>\build.bat release > <log> 2>&1"` from PowerShell, using the full path to `build.bat`. From Git Bash, `cmd //c "build.bat release"` opens an idle prompt, builds nothing and still exits 0. The bare name `build.bat` is "not recognized" from PowerShell's cmd. The log stays empty until the run ends (~10 minutes), so confirm with `gh release list` afterwards.
- Releases must be non-draft and marked latest.
- On this host `build.bat release` does every platform: Windows locally, then `release_other_platforms()` in `tools/release.py` dispatches `.github/workflows/macos-release.yml` (Apple Silicon runner) and builds, lints and smoke-tests the `.deb` over `ssh root@serrebiradio.com` with `tools/build_deb_remote.sh` (debian:trixie containers, ~2 min; `LINUX_BUILD_HOST` overrides the host), uploads it and waits for the macOS zip. If that half fails after publishing, rerun it: `python -c "import sys; sys.path.insert(0, 'tools'); import release; release.release_other_platforms('X.Y.Z')"`. `debian-package.yml` no longer fires on a published release, so the host never builds the `.deb` twice. Never use `cloud-release.yml` from this host.
- Muse agent and cloud agents ONLY (never on this host, never while `build.bat release` runs; both bump from the latest tag): `.github/workflows/cloud-release.yml` runs the same `build.bat release` on a GitHub Windows runner (LFS checkout, Inno Setup, signed from the `WINDOWS_CODESIGN_PFX`/`WINDOWS_CODESIGN_PASSWORD` secrets, verified against that thumbprint), then dispatches `debian-package.yml` with `release_tag` (a release published with GITHUB_TOKEN starts no workflow) and checks the `.deb` and `/releases/latest`; one `macos-15` (Apple Silicon) job runs `tools/build_macos.sh` on the same commit and attaches `AccessibleIPTVClient-vX.Y.Z-macos-arm64.zip` (the script checks the bundled ffmpeg and libVLC work alone and that the app stays up 15 s). Translations: run `prepare-notes`, translate, and push ONLY the `locale/` changes to a scratch branch such as `release-notes/next`, never main; `-f translations_branch=<branch>` lays them over main uncommitted, as on the host. Delete the branch after the release. `gh workflow run cloud-release.yml -f dry_run=true` builds and prints the audit, publishing nothing. Watch with `gh run watch <id> --exit-status`. Use a `Changelog: skip` footer on CI-only commits.
- `cloud-release.yml`'s linux job must watch the debian-package.yml run it dispatched: it reads the run id from the URL `gh workflow run` prints, falling back to the dispatch whose run name is "Debian Package <tag>" (debian-package.yml `run-name`), so neither an older run nor a concurrent dispatch for another tag can be picked. `gh run list --limit 1` returned an older finished run for v1.145.1, so the job checked the release before the .deb was uploaded and reported a false failure on a complete release.
- Never delete old non-draft releases unless the user explicitly asks. It is okay to delete leftover draft releases.
- Never ship a release when PyInstaller reports unresolved warnings, missing imports, dependency mismatches, failed validation, or build errors.
- Do not bundle local `iptvclient.conf`. `main.spec` excludes it, and `tools/release.py` must fail the build if any packaged `iptvclient.conf` is found.
- `ffmpeg.exe` is tracked through Git LFS. Before releasing, ensure it is the real executable, not a small LFS pointer file. `tools/release.py` validates both the source and packaged `ffmpeg.exe` by size, pointer detection, and `ffmpeg -version`.
- `tools/release.py` runs PyInstaller through a limited Task Scheduler task when the current process is elevated, avoiding PyInstaller's elevated-token deprecation warning.
- `tools/release.py` creates the update manifest asset required by the auto-updater. Required manifest fields include `version`, `asset_filename`, `download_url`, `sha256`, and `release_notes_summary`.
- PowerShell/Batch release quoting matters on Windows. In batch files, `git describe --tags --abbrev=0` must be written as `--abbrev^=0` inside `for /f`. Inside a quoted `powershell -Command`, use a normal pipeline character (`|`), not `^|`.
- When cleaning GitHub draft releases from PowerShell, decode JSON first and filter explicit draft booleans with `Where-Object { $_.isDraft -eq $true }`; do not pipe raw JSON array output directly into a truthy object filter.
- A release run can die partway and leave the repo half-released. The window is between the commit and the tag in `git_commit_and_tag`: a `chore(release): vX.Y.Z` commit exists, but there is no tag, nothing is pushed, and there is no GitHub release, while the built and signed assets already sit in `dist/release/`. Diagnose with `git tag --list`, `gh release list`, and `git rev-list --left-right --count HEAD...origin/main`.
- Recover an aborted release by finishing it, not by repeating it. Re-running `build.bat release` fails by design in `update_changelog` with `CHANGELOG.md already contains vX.Y.Z`, and resetting the release commit only forces a rebuild that reproduces identical artifacts and re-signs them for nothing. Create the missing tag, then call `git_push` and `gh_release_create` from `tools/release.py` with the assets already on disk. The asset dict keys are `asset_path`, `latest_path`, `manifest_path`, `notes_path`, and `installer_path`; `gh_release_create` already calls `ensure_release_published_latest` and `delete_draft_releases`, so the published result matches a normal run. Only reuse assets whose manifest version and hashes match the current `HEAD`.

## Where the learnings live

The bullets below used to sit here, 100 KB of them, loaded on every run.
They are unchanged, one file per subject, and this list is the index:
read the file that names the code you are about to change, and grep
`docs/learnings/` for the module, symbol or error before you conclude
anything is missing.

- **docs/learnings/casting-and-proxy.md** - Casting and the stream proxy. 30 entries.
- **docs/learnings/recording-and-catchup.md** - Recording and catch-up. 26 entries.
- **docs/learnings/updates-and-release.md** - Updates, release and translations. 30 entries.
- **docs/learnings/ui-and-accessibility.md** - UI and accessibility. 34 entries.
- **docs/learnings/epg-and-matching.md** - EPG, playlists and channel matching. 64 entries.
- **docs/learnings/playback.md** - Playback (libVLC, buffering, subtitles). 28 entries.
- **docs/learnings/tooling-and-process.md** - Tooling, tests and process. 5 entries.

## Agent skills

### Issue tracker

Issues are tracked in this repo's GitHub Issues, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

# Reminders and recording storage: validation

Base: v1.150.48, commit `47c737d6` (after merged PR #100).

Final broad local Linux regression: **2615 passed, 162 skipped, 5 deselected**, no failures (58.74 s). The affected reminders/storage/recorder/DVR/localization/Debian selection: **167 passed, 6 skipped**, no failures. Ruff and whitespace checks pass. All 797 extracted application messages have translations and matching placeholders in all 13 translated locales. Compiled MO singular translations are checked by GNU gettext round-trip. The Hungarian guide retains the original topic IDs in their original order. The final Hungarian UI terms, 25 new strings and added help paragraphs were reviewed after implementation; two untranslated current Hungarian release-note bullets from #99/#100 were also completed.

The broad run uses the same external headless collection helper as previous local checks: fixtures requiring `wx_app` are skipped, and `tests/test_player_transport_gui.py` is ignored because this host has no graphical display. Five existing cases are deselected:

- `test_internal_player.py::test_the_focus_leaves_the_audio_track_choice_before_it_is_disabled` — native GUI focus requires a display.
- `test_startup_lazy.py::test_config_read_candidates_do_not_create_user_config_dir` — host config path/APPDATA behavior differs from that case's contract.
- `test_updater.py::test_update_helper_actually_starts_from_a_path_with_a_space` — native Windows updater execution is unavailable here.
- `test_stream_proxy.py::test_the_proxy_handlers_are_daemon_threads` — required test network interface unavailable in this host.
- `test_epg_database.py::test_a_live_imports_lock_is_not_stolen` — host PID/process visibility differs from the fixture assumptions.

The helper and exclusions are not committed. No repository CI selection, skips, audit rules or capability gates are weakened. Skipped GUI/native/optional cases are not counted as successful runtime acceptance.

Tests cover exact lead deadlines, zero lead, restart/redelivery/expiry, acknowledgements, no automatic channel switch, explicit playback of a uniquely resolved current channel, source isolation, ambiguous matches, duplicate update, cancel/delete, maximum capacity, malformed inputs, preserved corrupt files, failed atomic saves, clock reversal, native-modal deferral and pending-reminder exit cancellation. Storage tests cover exact byte boundaries, zero policy, malformed configuration, permission/unknown-capacity/file destinations, owned-probe cleanup, failure before buffer acquisition/FFmpeg, serialized concurrent starts and actual DVR failure state without a phantom recording ID.

Native acceptance still required: Windows/frozen builds, JAWS/NVDA column/button announcements and long-label wrapping; wake/resume, tray operation and forced exit; native EPG/modal notification interactions; read-only, disconnected, external and network output volumes; real provider recordings/downloads and local-buffer sharing. OS filesystem calls may be delayed by a disconnected volume, particularly in existing synchronous manual-start paths. The preflight floor is not a reservation, duration prediction or guarantee of space for the full capture. Reminders do not wake the machine and do not automatically track EPG schedule changes.

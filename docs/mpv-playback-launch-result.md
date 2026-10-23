# Report MPV process-start failures separately from subtitle availability

This focused follow-up addresses the P2 finding on PR #83:
https://github.com/serrebidev/Accessible-IPTV-Client/pull/83#discussion_r4361553230

Tested base: `70f874bfcbe9d3e85a6158625d03978b294ab50a`, main at v1.150.38.

## Trigger and corrected behavior

Starting normal MPV without an executable, choosing a stale Custom MPV path, or failing both process-start paths used to return an accepted asynchronous request and report only that subtitle speech was unavailable. The main window could then remember the channel as played, even though no process existed.

The launcher now reports a separate process-start result. The main window shows its existing localized Launch Error dialog for a failed owned MPV start, cancels that failed session and does not update recently played/previous-channel history. An owned process with an unavailable subtitle helper remains a successful playback launch; its caption status stays separate.

Success means that a process was created and accepted by the owner, or that the existing synchronous handoff succeeded. It is not proof of media decoding, stream availability or physical audio delivery.

## API and threading

`ExternalPlayerLauncher.launch(..., playback_result_cb=callback)` retains the two-value return contract:

- Synchronous failure returns `(False, error)`. The caller handles that error; the callback is not also called for the same failure.
- Synchronous success returns `(True, "")` and invokes `callback(True, "")` once, if supplied.
- Asynchronous MPV returns `(True, "")` when its worker was scheduled. Its later callback reports success/error after process creation and ownership registration. A worker-start exception returns a synchronous failure.
- Debounced or obsolete requests do not generate another completion. A failed owned request releases its debounce key so an immediate retry is possible.

For application-owned MPV the result is dispatched through `SubtitleSessionController.dispatch`, which validates the playback token immediately before invoking it on the UI dispatcher. The launch-generation guard is checked at delivery as well. A channel/player transition invalidates old callbacks, so an old error cannot cancel a new session or record an old channel.

Standalone callers without a session supply their own callback/thread-marshalling policy; the application's UI always supplies a session. Callback exceptions are logged and cannot turn an already-started process into a new fallback launch.

## Fallback and scope

Helper setup failure can still use the explicitly owned playback-only MPV. It is successful process startup with subtitle speech unavailable. If both process-start paths fail, the result is a playback error. Exceptions from the primary helper path are allowed to try that owned fallback. Before creating it, generation/token checks reject obsolete work.

Late subtitle-handshake failure after process creation does not send another playback-start failure and does not start a second process. Existing Lua, IPC, file scheduling, output routing, speech/device policies and translation resources are unchanged.

Existing localized messages are reused. Missing executable detail is specific; if the adapter supplied no error text, the existing translated "No error details were reported." message is used. Low-level exceptions remain in the application log.

## Verification

- Final broad local Linux run: **2187 passed, 158 skipped, 4 deselected**, no failures.
- Focused launch/session/debounce/application-wiring selection: **50 passed**.
- Translation audit plus the new launch-result file: **31 passed**.
- Ruff, Python compilation and `git diff --check` passed.

Cases cover a missing MPV, stale Custom path, both starts failing, an unexpected helper exception, a working playback-only fallback, ordinary adapter ownership before subtitle readiness, later handshake failure, old queued results, callback exceptions, immediate retry, synchronous player success/failure, worker-start failure, a real missing-executable `Popen` failure, background failure after session replacement, UI error delivery, deferred live history and catch-up history exclusion.

The broad run uses an external local harness to skip GUI fixture cases because this Linux host has no desktop. It excludes `test_player_transport_gui.py` and deselects the existing slow Windows updater helper, direct GUI focus test, Linux/Windows APPDATA assumption and unchanged stream-proxy listener test (`EADDRNOTAVAIL` here). Native SAPI, Windows pipes and the restricted full MPV IPC test skip where unsupported. These local exceptions are not changes to repository CI; no tests or CI gates are removed by the patch.

Windows CI must run on this new PR before treating it as Windows-verified. Manually test a missing MPV, a Custom path with spaces/Unicode, a permission/process-start failure and a healthy MPV whose subtitle helper is unavailable. Confirm one accessible error, unchanged live history on failure, immediate retry and no obsolete modal after changing player/channel.

No release, version bump, automatic merge, help rewrite or catalogue update is included.

# Bug Triage Report

**Date**: 2026-10-20
**Repository**: Accessible-IPTV-Client
**Scope**: the whole application, not one module.

The previous report (2026-02-01) is gone. Every finding in it had been fixed
long ago - the lambda closure over `e`, the unbound `conn`, the optional
casting imports, the unused variables - and its "no formal test suite found"
was already wrong: the suite has ~1950 tests.

## Fixed in this pass

| Severity | Where | Defect | What the user saw |
|---|---|---|---|
| BLOCKER | `updater.py` | the Authenticode pin was read from the update manifest, which travels with the release | a release signed with *any* certificate was accepted, so whoever could publish one could install and elevate their own code |
| SEVERE | `stream_proxy.py` | the header gateway sent the channel's credentials to whatever host the request named | the provider's cookie went to any host that reused the token from a cast URL |
| SEVERE | `update_helper.ps1` | the rollback only restored the backup when the install directory was gone | a failed move left the app uninstalled and the working version sitting in the `.bak` folder |
| SEVERE | `main.py`, `internal_player.py` | a queued notification could outlive its window, and a destroyed wx object raises on every call | the Cast error box could take the app down with `RuntimeError: wrapped C/C++ object of type Frame has been deleted` |
| MINOR | `update_helper.ps1` | a timed-out installer was left running | the app restarted into the directory the installer was still writing to |
| MINOR | `internal_player.py` | the HLS variant probe was a blocking HTTP GET on the GUI thread | up to two seconds of frozen window and silent screen reader when opening a channel |
| MINOR | `recorder.py`, `main.py` | `stop()` did nothing when the recording id no longer resolved | a scheduled recording kept running past its end and was reported as a stop timeout |

Every fix has a regression test that fails without it.

## Still open

- The spoken behaviour of the Cast error box (NVDA reading it, the focus
  returning to the Cast button) is covered by GUI tests only. It still needs
  a real screen reader.
- `updater.TRUSTED_SIGNING_THUMBPRINTS` is empty. A certificate rotation is
  delivered by an update signed with the old certificate that already carries
  the new pin, so there is nothing to fill in until the certificate rotates.
- The variant probe now waits 0.4 s for the manifest and falls back to the
  master playlist when the host is slow. The probe is off by default
  (`internal_player_variant_max_mbps` is 0), and the fallback costs the
  variant selection, not playback.

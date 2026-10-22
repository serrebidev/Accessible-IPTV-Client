# Tooling, tests and process

Moved here from `agents.md` on 2026-10-22, verbatim. `agents.md`
points at this file; read it before changing the code it names and
grep it for the module, symbol or error you are about to touch.

- Windows certificate-chain tests need unique issuer/root subject names per fixture. Reusing names with new keys lets the native chain cache select an old root and fail otherwise trusted local TLS probes.
- On Python 3.14, `platform.system()` can fall back to a subprocess on Windows. Do not call it at module import time; use `sys.platform` for import-time OS detection so importing `main.py` remains subprocess-free.
- Anything that closes the app on purpose has to set `_exit_forced` before `Close()`. `on_close` vetoes the close and hides to the tray whenever `minimize_to_tray` is on, which would otherwise leave the app running through its own shutdown request.
- The feed is untrusted input down to its namespaces. ElementTree keeps the namespace in the tag, so the importer's child lookups have to take any namespace - a namespaced feed came in with blank names and blank titles, and every import overwrote the good ones.
- A diagnostic that cannot run must say why. The F1 smoke test sent its keys to whatever held the foreground and reported 22 failures with nothing to say so; it now names the session as the cause.

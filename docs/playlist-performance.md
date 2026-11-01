# Playlist performance benchmark

`tools/playlist_benchmark.py` measures the real M3U parser and the main
pre-publication work without starting wxPython. It reports separate timings
for parsing, grouping, JSON cache serialization/deserialization, and bounded
publication batch preparation.

Run the representative threshold measurements with:

```text
python tools/playlist_benchmark.py --sizes 50000 250000 500000
```

To fail when a representative size exceeds the current index or search
latency budget, add `--check`:

```text
python tools/playlist_benchmark.py --check --sizes 50000 250000 500000
```

The generated playlist is deterministic: channel names, groups, IDs, and URLs
are stable between runs. Record the output when selecting the threshold for
progressive publication. These timings are machine-dependent evidence, not a
cross-machine performance promise.

The publication phase measures bounded batch construction only. It does not
create native controls or claim to prove screen-reader latency. GUI callback
and accessibility behavior remain separate validation gates.

## Recorded baseline

The representative run on the development Windows host used the command
above with the default 800-row batch size. The values are machine-dependent;
they are recorded here so future changes have a comparison point.

| Channels | Parse | Group | Index | Indexed search | Serialize | Deserialize | Publication prep | Batches |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 50,000 | 2.160992s | 0.014054s | 0.141293s | 0.123692s | 0.118396s | 0.138279s | 0.001220s | 63 |
| 250,000 | 10.893732s | 0.163013s | 0.817590s | 0.513205s | 0.726060s | 0.691048s | 0.006516s | 313 |
| 500,000 | 22.330457s | 0.333460s | 1.009148s | 0.522076s | 1.577189s | 1.027134s | 0.010325s | 625 |

The wx-level publication tests separately exercise first preview visibility,
each scheduled append callback, final row count, and selected-channel
restoration. Those tests do not claim to replace owner-heard NVDA or physical
keyboard validation.

## Playlist scope acceptance handoff

The deterministic 100,000-channel test in `tests/test_playlist_scope_gui.py`
drives repeated choice previews through the real wx combo, checks that preview
does no scope read, list rebuild, or config save, then checks one Enter
activation rebuilds the scoped list and saves once. Run it with the real-wx
scope tests, plus `tools/smoke_playlist_navigation.py`,
`tools/smoke_virtual_list_nvda.py`, and `tools/smoke_accessible_names_nvda.py`.
The accessible-name smoke checks the Playlist view combo and its neighboring
Categories, Search, and Channels controls at the wx and MSAA levels when MSAA
is available. Record command results as automated evidence only.

For the owner-heard and physical-input gate, load a **real** playlist with at
least 100,000 channels and use NVDA with the actual keyboard and mouse:

1. Focus Playlist view. Arrow repeatedly among playlists and All playlists.
   Confirm NVDA announces each preview, focus stays on the combo, and the
   categories and channels stay on the active playlist until activation.
2. Press Enter on a different playlist. Confirm the categories and virtual
   channel rows change once, NVDA reads the new selection, and combo focus
   remains usable. Press Enter again to check that it does not refresh twice.
3. Preview another playlist, press Escape, and confirm the committed choice
   returns without changing the lists. Preview again, then use Tab to commit
   and reach Categories; use Shift+Tab to return to Playlist view. Check that
   Shift+Tab out of an uncommitted preview does not commit it.
4. Select a playlist with the mouse and confirm one activation updates the
   lists without losing keyboard access. Traverse the neighboring Search and
   Channels controls in both directions and listen for their names.

Record the playlist size, NVDA version, observed announcements, focus and
activation behavior, and any pauses separately from the automated results.
Known MPV live-subtitle environment failures are a separate playback gate;
they are not evidence of playlist combo responsiveness.

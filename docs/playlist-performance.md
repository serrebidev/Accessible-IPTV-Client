# Playlist performance benchmark

`tools/playlist_benchmark.py` measures the real M3U parser and the main
pre-publication work without starting wxPython. It reports separate timings
for parsing, grouping, JSON cache serialization, and bounded publication
preparation.

Run the representative threshold measurements with:

```text
python tools/playlist_benchmark.py --sizes 50000 250000 500000
```

The generated playlist is deterministic: channel names, groups, IDs, and URLs
are stable between runs. Record the output when selecting the threshold for
progressive publication. These timings are machine-dependent evidence, not a
cross-machine performance promise.

The publication phase currently measures bounded batch preparation only. It
does not create native controls or claim to prove screen-reader latency. GUI
callback and accessibility behavior remain separate validation gates.

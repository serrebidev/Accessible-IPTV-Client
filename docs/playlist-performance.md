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

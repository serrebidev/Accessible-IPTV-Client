# Changelog

Readable release history for Accessible IPTV Client. New entries are prepended automatically by `build.bat release`. Older entries were reconstructed from the [Forgejo mirror](https://git.serrebiradio.com/serrebi/Accessible-IPTV-Client).
## v1.105.2 - 2026-07-12

- Group untagged channels as Uncategorized, not by guessed country

## v1.105.1 - 2026-07-12

- Stop misclassifying live channels and single-stream shows

## v1.105.0 - 2026-07-12

- Add Video on Demand view for movies and series

## v1.104.1 - 2026-07-11

- Prevent broad searches from freezing the UI

## v1.104.0 - 2026-07-10

- Maintain project changelog
- Stop searches freezing the UI while EPG import is running


## v1.103.5 - 2026-07-09

- Stabilize NVDA virtual search results

## v1.103.4 - 2026-07-09

- Stop NVDA crashes during search by guarding virtual-list updates
- Restyle README to match BlindRSS format
- Refresh auto-maintained memory references in agents.md
- Tweak README tagline wording

## v1.103.3 - 2026-07-01

- Keep portable config beside executable

## v1.103.2 - 2026-07-01

- Cut startup/EPG-import CPU cost across DB repair scans, XMLTV parsing, and playlist caching

## v1.103.1 - 2026-06-30

- Stop region-fallback regex from scanning past the id's trailing segment
- Verify gzip download completeness by byte count, not just header probe

## v1.103.0 - 2026-06-30

- Add Inno Setup release installer

## v1.102.2 - 2026-06-30

- Improve startup laziness and recorder fixture

## v1.102.1 - 2026-06-29

- Tolerate BOM-prefixed JSON manifests
- Extract signing thumbprint with clean PowerShell

## v1.102.0 - 2026-06-29

- Silent updates with an accessible progress window
- Stabilize recording HTTP fixtures

## v1.101.1 - 2026-06-28

- Speed up startup and update checks

## v1.101.0 - 2026-06-22

- Virtual channel list for large playlists, faster EPG, and multiple bug fixes

## v1.100.2 - 2026-06-22

- Update Hungarian translation

## v1.100.1 - 2026-06-20

- I18n: revise Hungarian translation (contributed by @htibcsike)

## v1.100.0 - 2026-06-18

- Add DVR scheduling

## v1.99.0 - 2026-06-18

- Add IPTV recording

## v1.98.0 - 2026-06-18

- Add gettext internationalization with Hungarian translation

## v1.97.11 - 2026-05-17

- Stop bundled proxy from dying on every request (noconsole stderr)

## v1.97.10 - 2026-05-17

- Respond fast and serve bootstrap when HLS warm-up exceeds Chromecast tolerance

## v1.97.9 - 2026-05-17

- Keep Chromecast alive while slow HLS upstreams warm up

## v1.97.8 - 2026-05-17

- Harden AirPlay and Chromecast casting
- Refresh agent project notes
- Update agent release build rules

## v1.97.7 - 2026-05-16

- This time, I worked on EPG, and it now works as well as it did before.
- Sorry for the missing older releases again. Hopefully it will not happen again. Want to see this project's history?
- Https://git.serrebiradio.com/serrebi/Accessible-IPTV-Client

## v1.97.6 - 2026-05-16

- Keep draft cleanup release-safe

## v1.97.5 - 2026-05-16

- Repair release state verification

## v1.97.4 - 2026-05-16

- Harden release ffmpeg packaging

## v1.97.3 - 2026-05-16

- Add Telegram group link to README
- Ignore .claude/ local settings
- Enforce non-draft releases
- Document build and release flow
- Improve EPG import freshness and regional matching
- Keep GitHub releases published

## v1.97.2 - 2026-05-04

- **Full Changelog**: https://github.com/serrebidev/Accessible-IPTV-Client/compare/v1.97.1...v1.97.2

## v1.97.1 - 2026-03-08

- Require fixing build warnings/errors before shipping
- Fix laggy live stream playback by enabling frame dropping and reducing restart aggression

## v1.97.0 - 2026-03-04

- Fix casting bugs, enable adaptive buffering, and improve Opus stream stability

## v1.96.0 - 2026-02-01

- Fix focus-stealing when app is minimized to tray

## v1.95.0 - 2026-01-31

- Add 'What's on Now' feature (File > What's on Now, Ctrl+W)

## v1.94.3 - 2026-01-31

- Reduce stream startup delay from 3-5s to 1-2s
- Update learnings with stream startup and position tracking fixes

## v1.94.2 - 2026-01-31

- Fix system tray focus for NVDA and improve Xtream TS stream detection

## v1.94.1 - 2026-01-31

- Add learning about tray focus fix for NVDA
- Fix system tray: single left-click now restores app
- Update agents.md: system tray fix documentation

## v1.94.0 - 2026-01-31

- Add learning about PowerShell module loading fix for Authenticode
- Add Help menu with About dialog; fix NVDA focus issues
- V1.93.27: Add test suite, fix tray focus for NVDA

## v1.93.26 - 2026-01-31

- Update agents.md with today's learnings
- Authenticode verification now works with PowerShell Core environment

## v1.93.25 - 2026-01-31

- Legacy release; see the Forgejo mirror tag history for details.

## v1.93.23 - 2026-01-31

- Fix audio mute bug and improve stream startup time

## v1.93.24 - 2026-01-30

- Fix updater Authenticode verification with better error messages
- Document updater Authenticode verification fix

## v1.93.22 - 2026-01-30

- Fix updater invisibility, auto-cleanup backups, and optimize stream buffering

## v1.93.21 - 2026-01-28

- Prioritize channels with schedule data over strict region matching

## v1.93.20 - 2026-01-28

- Increase initial buffer to 64KB to prevent early stalling

## v1.93.19 - 2026-01-28

- Remove strict region filtering to find matches even if region tags disagree

## v1.93.18 - 2026-01-28

- Auto-repair stale normalized names in EPG database on startup

## v1.93.17 - 2026-01-28

- Correctly normalize channel names with tags in brackets like (UKHD)

## v1.93.16 - 2026-01-28

- Legacy release; see the Forgejo mirror tag history for details.

## v1.93.15 - 2026-01-28

- Improve matching for channels with suffix tags like UKHD/UKSD

## v1.93.14 - 2026-01-28

- Reduce buffer for audio streams to 2s for instant playback
- Reduce default video buffering to 4-6s for faster startup

## v1.93.13 - 2026-01-28

- Make radio station detection case-insensitive

## v1.93.12 - 2026-01-28

- Optimize chunk size (8KB) and fill (24KB) to reduce latency

## v1.93.11 - 2026-01-28

- Add 128KB initial buffer fill to prevent start-up stutters

## v1.93.10 - 2026-01-28

- Restore iptvclient.conf from backup during update

## v1.93.9 - 2026-01-28

- Implement 16MB threaded buffer for audio streams to fix slow playback

## v1.93.8 - 2026-01-28

- Force helper scripts to run from temp dir to fix legacy update locks

## v1.93.7 - 2026-01-28

- Run helper in temp dir to avoid locking install dir

## v1.93.6 - 2026-01-28

- Note netifaces install

## v1.93.5 - 2026-01-28

- Reduce startup CPU spikes
- Update agents

## v1.93.4 - 2026-01-04

- Fix update helper args
- Refresh readme and ignore build artifacts
- Make release script rerunnable

## v1.93.3 - 2025-12-30

- Resolve bundled assets (ffmpeg, update_helper) in _internal dir for PyInstaller onedir builds

## v1.93.2 - 2025-12-30

- Handle unclosed token error in EPG import for truncated/malformed XML

## v1.93.1 - 2025-12-28

- Support manifest signing thumbprint for updates

## v1.93.0 - 2025-12-28

- Add updater and release pipeline

## v1.92 - 2025-12-22

- I updated the build so hopefully it will work for everyone

## v1.91 - 2025-12-20

- Fixes.

## v1.9 - 2025-12-19

- Enhance casting, proxy, and accessibility features

## v1.8 - 2025-12-13

- Refactor player controls and add external player support

## v1.751 - 2025-12-11

- Retune internal player buffering for faster live startup

## v1.75 - 2025-12-10

- Add unified casting support and update docs

## v1.7 - 2025-11-22

- Added some sensible defaults for buffering settings in the conf file.
- Add per-channel HTTP headers and Plex-style volume control

## v1.651 - 2025-11-12

- Improve Xtream live TS stream recovery on stalls

## v1.65 - 2025-11-12

- Improve VLC player recovery for Xtream .ts live streams

## v1.64 - 2025-11-12

- Better URL display

## v1.63 - 2025-11-03

- Add EPG host offset support for DST correction
- Remove EPG host offset handling and config

## v1.62 - 2025-10-28

- Delete main.spec

## v1.61 - 2025-10-28

- Add advanced buffering and HLS variant controls to built in player

## v1.6 - 2025-10-28

- Add built-in IPTV player with adaptive buffering, and install for players you don't have

## v1.5.4 - 2025-10-16

- Add EPG import locking and expand playlist sources in the iptvclient.conf example

## v1.5.3 - 2025-10-04

- Improve playlist EPG import concurrency and locking

## v1.5.2 - 2025-09-28

- Improve EPG matching and add requirements.txt

## v1.5.1 - 2025-09-25

- Improve headless support and playlist parsing, so loading playlists should be much faster

## v1.5.0.6 - 2025-09-18

- Improve EPG import robustness and plus 1  scoring
- New Easier to digest ReadMe

## v1.5.0.5 - 2025-09-18

- Improve EPG handling and player launch logic

## v1.5.0.4 - 2025-09-18

- Improve EPG import robustness and logging

## v1.5.0.3 - 2025-09-17

- EPG Changes
- EPG optamizations

## v1.5.0.2 - 2025-09-17

- Improve config handling and region detection logic

## v1.5.0.1 - 2025-09-16

- Improve tray icon restore logic and add PyInstaller spec

## v1.5.0 - 2025-09-15

- More BugFixes
- Create main.spec
- Optimize EPG XML parsing to reduce memory usage
- Experimental XtreamCode and StockerPortal support.

## v1.4.2.0.7 - 2025-08-17

- Update README
- Added some clarity
- Made ReadMe easier to read.
- Update README.md

## v1.4.2.0.6 - 2025-08-11

- Fixed what's on now display: It picks the right channel like next on does.

## v1.4.2.0.5 - 2025-08-11

- Press enter fixes.
- Media players are no longer invisible.

## v1.4.2.0.4 - 2025-08-11

- Fixed EPG

## v1.4.2.0.3 - 2025-08-08

- Improve EPG matching

## v1.4.2.0.2 - 2025-08-07

- Fixed certain networks EPG

## v1.4.2.0.1 - 2025-08-07

- Major EPG updates
- Update README with clearer usage and requirements
- Update README.md

## v1.4.2.0 - 2025-07-31

- Improve config file handling and fix playlist result

## v1.4.1 - 2025-07-31

- Fixed EPG matching.
- Many bugfixes

## v1.4 - 2025-07-25

- Legacy release; see the Forgejo mirror tag history for details.

## v1.3.4 - 2025-07-25

- I fixed some uncategorized channels bugs, and also made it so you can left click or press enter on the system trey icon.

## v1.3.3 - 2025-07-05

- .
- Some orca crashing fixes.
- More fixes.
- I have limited results to 50 to cut down on Orca crashing. SO far so good. Wish I could find another way.

## v1.3.2 - 2025-07-05

- I added a menu button for Linux users which shows all the menu items for them.
- Aded some more Linux media players, so it probably has your favorit player now.

## v2025.07.04 - 2025-07-04

- I updated the system trey so you can left click to open the app, and I split the program up for vibe coding purposes!
- Back to 1.3.1

## v1.3.1 - 2025-07-04

- I have made it so EPG only caches the current program for each channel, and it stores 24Hours of this info. Every 3 hours, your EPG and playlists are refreshed. You also have the option of disabling EPG if you are used to living without it.
- Went back to the 1.2.2 version, and I think I have fixed EPG issue things.
- Went back to 1.2.2. Apologies.
- This is a reRelease. I moved EPG to temp directory which is whiped when you restart the app. Every 3 hours, your EPG and playlists are refreshed."
- Just included minimize to trey in the config file in the repo
- Fixed the options menu showing the correct value from the conf file, the conf file is unchanged.

## v1.3 - 2025-06-25

- Update README.md
- My radios playlist changed url.
- Updated.

## v1.2.2 - 2025-06-15

- Improved EPG matching again.

## v1.2.1 - 2025-06-14

- Made it less wordy
- Fixed parts of the ReadMe, nothing major.
- I updated list view logic so there's less lag, and improved SM player support on windows
- Way better EPG matching, and lag fix for the list of channels when there's EPG to look up

## v1.2.0 - 2025-06-11

- Fixed the traceback on exit.
- Tries to detect running Linux distribution and makes menu bar work with Orca
- Fixed accessibility on some Linux distros
- Tried to improve EPG matching
- Added some more media players. Let me know if you have any suggestions, but I think that's good.
- Fixed some paths for media players on windows. If you need a player added, let me know.

## v1.1.0 - 2025-06-08

- Hopefully I fixed media player access on Linux, and arrowing on Linux should work better now.
- Hopefully fixed Linux menu bar issues, and the traceback on exit is also hopefully fixed.
- Fixed some media player paths, and added a few MacOS options. You should have options on there now if you run it.
- I have split the project into three files. I'm adding it to the repo let me know if there's any issues, eventually I will remove the one file version.
- Update README.md

## v1.0.0 - 2025-06-06

- New version!
- Removed one time open functions until I can get them working.
- Update iptvclient.py
- Added some radio and TV sources to a conf I included in the Repo
- Now pressing enter reliably plays the currently selected stream.
- Update README.md
- Update README.md!
- Update README.md wordings
- Update README.md with better install instructions.
- Fix keyboarding in the lists.
- New config file layout, and new EPG support!
- Update ~$README.md
- New EPG logic, tries to match to channel ID. If it works done, if it doesn't work try to match as before.
- Added new public sources for streams. You should be able to find something to watch for sure now.
- Added some logic so you're not waiting for the GUI while the playlists load. Some lag when the playlists are added. I don't think it can be help, but it's less time than the waiting you were doing before.
- I fixed up EPG up next logic, and channel display for some channels.
- Updated channel matching. You may have to remove your epg.db .
- Added ability to use Global search to find channels airing a show and tune to them.
- Sorry for the quick change. Now global search will return EPG from now into future, and you can press enter on a result to play it even from EPG, if you want to tune a channel for the future.
- Media player choice now saves to the conf file.

## release - 2025-05-21

- Initial commit
- First version!

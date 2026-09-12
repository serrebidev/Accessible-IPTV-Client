<!--
Accessible IPTV Client user guide, English. This is the reference version.

Notes for translators:
- Copy this file to docs/help/<language code>.md (for example hu.md) and
  translate the text. The app shows the guide for its interface language and
  falls back to English when there is no file for that language.
- Keep every {#topic-id} exactly as it is. F1 help uses these ids to open the
  right section. Translate only the heading text in front of them.
- A section you have not translated yet can simply be left out: F1 on that
  part of the program then opens the English section instead.
- Menu names and button labels should match the wording of the translated
  program, so users can find what the guide describes.
- Lines that belong together can be wrapped freely. A blank line starts a new
  paragraph. Lines starting with "- " are list items.
-->

# Accessible IPTV Client User Guide {#user-guide}

Accessible IPTV Client plays live TV, radio and video on demand from IPTV providers. It is built for the keyboard and for screen readers such as NVDA, JAWS, Narrator and Orca, and it copes with very large playlists and programme guides.

This guide explains every part of the program. Press F1 anywhere in the program to open it at the section about what you are using at that moment.

## Using this guide {#using-help}

The guide window has four parts, in Tab order:

- Topics: the list of sections. Moving through it with the arrow keys moves the guide text to that section. Press Enter to go straight into the text.
- Guide text: the whole guide as one read-only document. Read it with the arrow keys or with your screen reader's say-all command, select and copy text as in any document.
- Find: type a word and press Enter to jump to the next place it appears.
- Close.

Keys in the guide window:

- Ctrl+F: go to the Find field.
- F3: find the next match. Shift+F3: find the previous match.
- F1: come back to this section.
- Escape: close the guide and return to where you were.

F1 is context-sensitive. Pressed on a menu item, in a dialog, in the built-in player or on a control in the main window, it opens the guide at the section about that item. Where no section has been written for something yet, the guide opens at its beginning. Help > User Guide always opens it at the beginning.

The guide is part of the program, so it works without an internet connection. It is shown in the program's interface language when a translation exists, and in English otherwise.

## Getting started {#getting-started}

1. Open File > Playlist Manager (Ctrl+M) and add your provider: an M3U playlist file or address, an Xtream Codes account, or a Stalker Portal account. Choose OK. The channels load in the background.
2. If your provider gives you a programme guide (EPG) address, add it in File > EPG Manager (Ctrl+E). Xtream Codes accounts can add it for you.
3. Import the guide with File > Import EPG to DB (Ctrl+I). This runs in the background and tells you when it has finished.
4. Choose a category, pick a channel and press Enter to play it.

Your playlists, guide sources and settings are kept between sessions, so this only has to be done once.

## The main window {#main-window}

The main window is where you browse and play channels. Tab moves through its controls in this order, and Shift+Tab goes back:

1. Playlist view: which playlist to browse.
2. Categories: the channel groups.
3. Search: filters the channel list.
4. Channels: the channels in the chosen category, or the search results.
5. Episode description: what is on the highlighted channel now.
6. Stream URL: the address of the highlighted channel, shown only when Options > Show Stream URL is on.

After the last control, Tab wraps round to the first one.

On Linux, the menus this guide describes are under the Menu button at the top of the window.

### Playlist view {#playlist-view}

When you have more than one playlist, the Playlist view list chooses what the categories and channels show: All playlists, or a single playlist. Your choice is remembered.

### Categories {#categories}

The category list holds the channel groups from your playlists. Its first rows are All Channels and, once you have added some, Favorites. Each row says how many channels it holds.

- Up and Down arrows move through the categories without changing the channel list, so you can listen to them first.
- Enter opens the highlighted category and moves to the channel list.
- Tab opens the highlighted category and moves to the Search field.
- Left and Right arrows collapse and expand a category that has sub-groups.

### Searching {#search}

Type in the Search field to filter the channel list, then press Enter or Tab to apply the filter and move on. Searching in All Channels also looks in the programme guide, so a search for a programme title can list the channels showing it. Clear the field and press Enter to see the whole category again.

### The channel list {#channel-list}

The channel list shows the channels of the chosen category or search.

- Enter plays the highlighted channel.
- The Applications key, Shift+F10 or a right click opens the channel's menu: Play, Add to Favorites or Remove from Favorites, Record or Stop Recording, Schedule Recording, View EPG, and Catch-up for channels that have an archive.
- Ctrl+D adds the channel to Favorites or removes it. In the Favorites category, Delete removes it.
- Ctrl+Shift+R starts recording the channel, and pressed again stops it.

Favorite channels are marked "(Favorite)", and each row also names the programme on air now when the guide has it. When a search also found programmes, their rows name the programme and the channel it is on.

### Episode description and stream URL {#episode-description}

Tab from the channel list reaches the Episode description: the programme on air now on the highlighted channel, with its times and description, and what is on next. Shift+Tab goes straight back to the channel list. The text follows the highlighted channel.

When Options > Show Stream URL is on, the Stream URL field comes one Tab later. It shows the channel's address, which can help when reporting a problem. Most people leave it off.

## Favorites {#favorites}

Favorites keep the channels you watch most in one place. Press Ctrl+D on a channel, or use its menu, or View > Add to Favorites. Favorites appear in the Favorites category near the top of the category list, and View > Go to Favorites takes you there.

To remove a favorite, press Ctrl+D on it again, or press Delete in the Favorites category.

Favorites are stored by provider and channel, not by stream address, so they survive a playlist refresh. Nothing about your account is stored with them.

## Video on demand {#video-on-demand}

View > Video on Demand (Movies && Series) switches the category list from live channels to your provider's films and series. Categories are named Movies or Series followed by the provider's category. Choosing a series lists its episodes in season and episode order. Press Enter to play a film or an episode.

View > Live TV && Catch-up switches back to live channels. The search field clears when you switch.

Video on demand works best with Xtream Codes accounts, which describe their catalogue properly. For plain M3U playlists the program recognizes films and series from their group names and episode numbering.

## Playlist Manager {#playlist-manager}

File > Playlist Manager (Ctrl+M) lists your playlist sources. It opens with the list focused.

- Add File: an M3U or M3U8 playlist on your computer.
- Add URL: the internet address of an M3U playlist.
- Add Xtream Codes: an Xtream Codes account.
- Add Stalker Portal: a Stalker (MAG) portal account.

On a source in the list, the Applications key or Shift+F10 opens its menu: Copy URL, Rename (F2) and Delete (Del). A name you give a source is only a label; it does not change the source.

Choose OK to keep your changes, or Cancel to forget them. The channels reload after OK.

### Xtream Codes accounts {#xtream-codes}

An Xtream Codes account needs the server address, your user name and your password, which your provider gives you. The name is your own label for the account. Leave "Automatically add XMLTV URL" checked to add the provider's programme guide to the EPG Manager at the same time.

Xtream Codes accounts also give you video on demand, catch-up where the provider offers it, and the account status under File > Account Info.

### Stalker Portal accounts {#stalker-portal}

A Stalker Portal account needs the portal address and the MAC address your provider registered for you. Some portals also want a user name and password. "Randomise MAC" makes up a new MAC address, which is only useful when the provider asks you to choose one. "Attempt to add provider XMLTV" adds the portal's programme guide when it has one.

## Programme guide (EPG) {#epg}

The programme guide, or EPG, tells you what is on each channel now and later. It comes from XMLTV guide files that your provider or another source publishes. The program imports them into a local database, then uses it for the episode description, What's on Now, View EPG, catch-up lists and searches.

### EPG Manager {#epg-manager}

File > EPG Manager (Ctrl+E) lists your guide sources.

- Add File: an XMLTV file on your computer (.xml or .xml.gz).
- Add URL: the internet address of an XMLTV guide.

The Applications key or Shift+F10 on a source opens its menu: Copy URL, Rename (F2) and Delete (Del). Choose OK to keep your changes.

### Importing the guide {#import-epg}

File > Import EPG to DB (Ctrl+I) downloads every guide source and loads it into the guide database. It runs in the background, so you can keep watching and browsing, and a message tells you when it has finished. Large guides can take several minutes.

The guide is also refreshed automatically from time to time, silently. Channels are matched to the guide by their guide ID and their names, including the usual country and quality variations in channel names.

If an imported guide does not show up for a channel, check that the source covers that channel, then import again. The import writes a detailed log; see Troubleshooting.

### What's on Now {#whats-on-now}

File > What's on Now (Ctrl+W) lists every programme on air right now across all channels, as "programme - channel".

- Typing letters jumps to the first programme that starts with them.
- Tab moves to the Filter field; type there to narrow the list to matching programmes or channels.
- Enter or the Play button plays the channel.
- Schedule Recording, or the programme's menu, schedules a recording of it.
- Escape closes the window.

### Channel guide (View EPG) {#channel-epg}

View EPG, on a channel's menu, lists that channel's programmes from the one on air now to as far as the guide goes. The programme on air now comes first.

- Tab moves between the list and the description of the highlighted programme.
- The Applications key or Shift+F10 on a programme offers Schedule Recording.
- Escape closes the window.

## Catch-up {#catch-up}

Channels that keep an archive let you watch programmes that have already been broadcast. Such channels have Catch-up on their menu in the channel list. It opens the catch-up window for the channel, listing its past programmes with their dates and times.

- Up and Down arrows move through the programmes.
- Enter plays the highlighted programme.
- The Applications key or Shift+F10 opens its menu: Open, to play it, and Download, to save it as a file.
- Tab moves to the programme's description and back.
- Escape closes the window.

When you close the built-in player after watching a catch-up programme, you return to the catch-up list at the same programme.

How far back you can go depends on your provider, usually a few days.

### Catch-up downloads {#catch-up-downloads}

Download saves a catch-up programme into your download folder (see Recordings), named after the channel and when the programme aired. Each download has its own window with its progress, time elapsed, time remaining and the size so far, all in one read-only field.

- Escape, or closing the window, hides it; the download continues.
- View > Show Downloads (Ctrl+Shift+D) brings the download windows back.
- Cancel stops the download after asking you to confirm. A canceled download cannot be resumed.

If a download fails, the window says why, and tries again automatically a few times when the problem may be temporary. Many providers allow only one stream at a time, so stop other playback from the same account if a download is refused.

## Built-in player {#built-in-player}

The built-in player plays channels inside the program. It opens when you play a channel, unless Options > Show Player on Enter is off, in which case playback starts without showing the window.

Its controls, in Tab order: Pause or Play, Stop, Record, Cast, Full Screen, the Volume slider and Choose Audio Track.

Keys in the player:

- Space: presses the focused button, so on Pause it pauses and resumes.
- Ctrl+P: play or pause.
- Ctrl+S: stop.
- Ctrl+R: record what you are watching, and stop that recording.
- Up and Down arrows: volume in 2% steps. Ctrl+Up and Ctrl+Down: 5% steps.
- A: next audio track.
- D: choose the audio output device.
- Ctrl+C: cast to a device.
- F11: full screen on or off. Escape leaves full screen.
- Ctrl+W: hide the player window; playback continues.
- Ctrl+Q: close the player and stop playback.

The same commands are on the player's Playback menu. The player reconnects on its own when a live stream drops, and keeps the audio track you chose.

### Audio tracks {#audio-tracks}

Channels can carry several audio tracks, such as other languages or audio description. Press A to move to the next track, use Playback > Audio Track, or Tab to Choose Audio Track, which always names the track that is playing.

A track you choose is remembered for that channel and comes back next time. See Preferred audio track for choosing tracks automatically.

### Audio output device {#audio-output-device}

Playback > Audio Output Device (D) chooses the speakers or headphones the player uses, for example to keep TV sound away from your screen reader. System default follows the Windows default device. The choice is remembered.

### Controlling the player from the main window {#player-from-main-window}

The Player menu in the main window works on the built-in player without switching to it:

- Show Built-in Player: Ctrl+Shift+J.
- Play/Pause: Ctrl+Shift+P.
- Stop: Ctrl+Shift+S.
- Cast / Connect: Ctrl+Shift+C.
- Ctrl+Up and Ctrl+Down change the volume.

## Media player {#media-player}

Options > Media Player to Use chooses what plays your channels: the Built-in Player, or an external player such as VLC, MPC, MPC-BE, MPV, PotPlayer, Kodi or SMPlayer. Custom Player lets you choose any other program by its file.

Recording, catch-up downloads and casting work the same whichever player you choose. The audio track features and the player keys described in this guide belong to the built-in player.

## Preferred audio track {#preferred-audio-track}

Options > Preferred Audio Track makes the built-in player choose an audio track by itself.

- "Prefer an audio description track when the channel has one" picks audio description wherever it is offered. It recognizes the names providers actually use in several languages, such as audio description, AD, Audiodeskription and Hörfilm, and the flag broadcasters put on such tracks.
- The text field takes track names or languages, most wanted first, separated by commas, for example: audio description, English. Leave it empty to keep whatever track a channel starts on.

A track you pick by hand in the player is remembered for that channel and takes priority over these rules the next time you watch it. The last track you picked anywhere is used for channels you have never chosen one for.

Recordings follow the same choice. An audio-only recording keeps the one track you would hear, and a video recording keeps every track with that one marked as the default.

## Recordings {#recordings}

The program can record any channel to a file while you watch something else, or with nothing playing at all.

- Recordings > Start Recording (Ctrl+Shift+R) records the highlighted channel. Pressed again, it stops.
- Record on a channel's menu does the same, and Record in the built-in player (Ctrl+R) records what you are watching.
- Recordings > Stop Recording stops the highlighted channel's recording, and Stop All Recordings stops them all.
- Recordings > Open Recordings Folder opens the folder the files are saved in.
- Recordings > Set Download Folder chooses that folder. Catch-up downloads go there too.
- Every recording writes a log file into the logs folder inside the recordings folder. When a recording ends, the program reports how many warnings and errors the log contains, so a capture that struggled is easy to spot; open the log for the details.

Recording what you are watching in the built-in player uses the same connection to the provider, so it works even with accounts that allow only one stream at a time.

Stopping a recording can take a moment while the file is finished. Closing the program lets running recordings finish their files on their own.

### Recording format {#recording-formats}

Recordings > Recording Format chooses how recordings are saved:

- Provider quality (copy, MKV): the stream exactly as broadcast, with every audio and subtitle track. Keeps everything the provider sends.
- Provider quality (copy, MP4): the same picture and sound in an MP4 file, which more devices play, without subtitles and teletext.
- x264 re-encode (MKV or MP4): a smaller re-encoded file. Uses much more processor time.
- Audio only (MP3 V0, FLAC, WAV, AAC M4A or Opus): the sound only, useful for radio.

### Scheduled recordings {#scheduled-recordings}

To record a programme in the future, choose Schedule Recording on a programme in View EPG, What's on Now or a programme row in the search results. Schedule Recording on a channel opens its guide so you can choose the programme first.

Recordings > Scheduled Recordings lists every scheduled, running and finished recording with its time, title, channel, status and format.

- The Applications key or Shift+F10 on a recording opens its menu: Refresh, Cancel and Delete.
- Delete removes the highlighted recording from the list; a running one is stopped first after asking you.
- Escape closes the window.

Scheduled recordings start by themselves while the program is running, even when it is minimized to the system tray. The window refreshes by itself when you open it and whenever a recording starts, finishes or is cancelled, so the Refresh command is rarely needed.

The program asks before it closes while a recording is scheduled, because the schedule only runs while the program is open. If you close it anyway, the scheduled recording will not start.

### Schedule padding {#schedule-padding}

Programmes rarely start and end exactly on time. Recordings > Schedule Padding sets how many minutes before a programme a scheduled recording starts, and how many minutes after it ends it keeps recording. Manual recordings are not affected. Catch-up downloads use the same minutes: the archive window requested from the provider is widened by them whenever the provider can serve it, and the download is retried when the file arrives shorter than the programme.

### Shutting down after recordings {#shutdown-after-recordings}

Recordings > Shut Down the Computer When Recordings Finish turns the computer off once every running and scheduled recording is done, which is useful for a late-night recording.

It never fires while something is still recording or waiting in the schedule. When the time comes, a window counts down 60 seconds; Cancel Shutdown is focused, so pressing Enter or Escape stops it, and Shut Down Now does not wait. The option turns itself off once it has been used or canceled.

## Casting {#casting}

Casting sends a channel to a TV or speaker on your network: Chromecast devices, DLNA and UPnP renderers, and AirPlay devices such as Apple TV and HomePod.

File > Cast To searches your network and lists the devices it finds. Choose a device and Connect. Some AirPlay devices need Pair first, which asks for the code shown on the TV. Once connected, playing a channel sends it to the device. Choose Cast To again to disconnect.

The Cast button in the built-in player, Player > Cast / Connect (Ctrl+Shift+C) and Ctrl+C in the player do the same.

Casting needs your computer and the device on the same network.

## Account Info {#account-info}

File > Account Info (Ctrl+Shift+A) shows the status of your Xtream Codes and Stalker Portal accounts: whether the account is active, its expiry date and the days remaining, whether it is a trial, and how many connections it allows and has open. Accounts found in playlist addresses are listed too.

Choose an account in the list; its details appear in the read-only field below. Refresh asks the provider again, and Copy Details puts the details on the clipboard. Passwords are never shown.

## Options {#options}

The Options menu holds the program's settings. Each one is saved as soon as you change it.

- Media Player to Use: see Media player.
- Preferred Audio Track: see Preferred audio track.
- Language: see Language.
- Minimize to System Tray: see System tray.
- Show Player on Enter: when on, playing a channel shows the built-in player window. When off, playback starts and focus stays in the channel list.
- Show Stream URL: adds the Stream URL field after the episode description in the main window.
- Auto-check for Updates: see Updates.

### Language {#language}

Options > Language chooses the language of the program. Automatic follows your Windows or desktop language and uses English when there is no translation for it. The change applies completely after restarting the program.

The program is available in English, Spanish, Arabic, Brazilian Portuguese, French, German, Russian, Turkish, Italian, Polish, Hindi, Simplified Chinese, Japanese and Hungarian. Corrections and new languages are welcome; see Getting help.

### System tray {#system-tray}

When Options > Minimize to System Tray is on, closing or minimizing the main window hides it in the notification area instead of exiting, so scheduled recordings keep running. Activate the tray icon to bring the window back. Its menu also has Restore, Player Controls, Stop Recording(s) while something is recording, and Exit.

To quit the program completely, use File > Exit (Ctrl+Q).

## Updates {#updates}

On Windows the program can update itself. Help > Check for Updates looks for a new version now, and Options > Auto-check for Updates checks in the background from time to time.

When an update is available, you are told what is new and asked whether to install it. The download is checked before anything is installed. The program closes during the update and starts again by itself when it has finished, then tells you whether the update succeeded. Your settings, favorites and recordings are kept.

On Linux, install the new package over the old one instead.

## Troubleshooting {#troubleshooting}

- Help > Open Logs Folder opens the folder with the program's log files, including the log of guide imports and one log per recording.
- Help > Copy Log and Debug Information copies a report with the program's version, your system and recent log lines to the clipboard, ready to paste into a bug report. It contains your stream addresses, which can include your provider login, so check it before sharing it publicly.

Common problems:

- A channel does not play: many providers allow only one stream per account at a time. Stop other playback, recordings or downloads from the same account and try again.
- A channel has no guide: check that one of your EPG sources covers it, and import the guide again.
- Playback stutters: the built-in player adjusts its buffer by itself. You can raise internal_player_buffer_seconds and internal_player_max_buffer_seconds in iptvclient.conf for a more patient buffer.
- Catch-up says the programme is not available: it is probably older than your provider's archive.

## Keyboard shortcuts {#keyboard-shortcuts}

Anywhere:

- F1: help about what you are using.

Main window:

- Ctrl+M: Playlist Manager.
- Ctrl+E: EPG Manager.
- Ctrl+I: Import EPG to DB.
- Ctrl+W: What's on Now.
- Ctrl+Shift+A: Account Info.
- Ctrl+D: add the selected channel to Favorites, or remove it.
- Delete: remove the selected channel from Favorites, in the Favorites category.
- Ctrl+Shift+R: start or stop recording the selected channel.
- Ctrl+Shift+D: show the catch-up download windows.
- Ctrl+Shift+J: show the built-in player.
- Ctrl+Shift+P: play or pause the built-in player.
- Ctrl+Shift+S: stop the built-in player.
- Ctrl+Shift+C: cast or connect.
- Ctrl+Up and Ctrl+Down: built-in player volume.
- Enter: play the selected channel.
- Applications key or Shift+F10: the channel's menu.
- Ctrl+Q: exit.

Built-in player:

- Space: press the focused button, such as Pause.
- Ctrl+P: play or pause.
- Ctrl+S: stop.
- Ctrl+R: record.
- Up and Down: volume in 2% steps; with Ctrl, 5% steps.
- A: next audio track.
- D: audio output device.
- Ctrl+C: cast.
- F11: full screen; Escape leaves full screen.
- Ctrl+W: hide the player.
- Ctrl+Q: close the player.

Lists of sources in the Playlist Manager and EPG Manager:

- F2: rename.
- Delete: delete.

## Getting help {#support}

Questions, bug reports and release news:

- The SerrebiProjects Telegram group: https://t.me/SerrebiProjects
- Bug reports and suggestions on GitHub: https://github.com/serrebidev/Accessible-IPTV-Client/issues

Help > About shows the version you are running and links to both. When you report a problem, Help > Copy Log and Debug Information gives the details needed to track it down.

<!--
Accessible-IPTV-Client-Benutzerhandbuch, Deutsch. Die englische Referenz
befindet sich in docs/help/en.md. Hinweis für Übersetzer: Die
{#topic ID}-Anker unverändert lassen; nur den Überschriftentext übersetzen.
Ein noch nicht übersetzter Abschnitt kann einfach weggelassen werden; F1
öffnet dann den englischen Abschnitt.
-->

# Accessible IPTV Client Benutzerhandbuch {#user-guide}

Der Accessible IPTV Client spielt Live-TV, Radio und Video on Demand von IPTV-Anbietern ab. Er ist für Tastatur und Screenreader wie NVDA, JAWS, Narrator und Orca gebaut, und er bewältigt sehr große Wiedergabelisten und Programmzeitschriften.

Dieses Handbuch erklärt jeden Teil des Programms. Drücken Sie an einer beliebigen Stelle F1, um es an dem Abschnitt zu öffnen, der zu dem gehört, was Sie gerade benutzen.

## Dieses Handbuch benutzen {#using-help}

Das Handbuchfenster hat vier Teile, in Tab-Reihenfolge:

- Themen: die Liste der Abschnitte. Das Bewegen mit den Pfeiltasten verschiebt den Handbuchtext zu diesem Abschnitt. Mit Enter gelangen Sie direkt in den Text.
- Handbuchtext: das ganze Handbuch als ein schreibgeschütztes Dokument. Lesen Sie es mit den Pfeiltasten oder mit der Alles-vorlesen-Funktion Ihres Screenreaders; Text markieren und kopieren funktioniert wie in jedem Dokument.
- Suchen: geben Sie ein Wort ein und drücken Sie Enter, um zur nächsten Stelle zu springen, an der es vorkommt.
- Schließen.

Tasten im Handbuchfenster:

- Ctrl+F: zum Suchfeld wechseln.
- F3: den nächsten Treffer finden. Shift+F3: den vorherigen Treffer finden.
- F1: zurück zu diesem Abschnitt.
- Escape: das Handbuch schließen und dorthin zurückkehren, wo Sie waren.

F1 ist kontextsensitiv. Auf einem Menüpunkt, in einem Dialog, im integrierten Player oder auf einem Steuerelement des Hauptfensters öffnet es das Handbuch an dem Abschnitt zu diesem Element. Wo noch kein Abschnitt geschrieben wurde, öffnet das Handbuch seinen Anfang. Hilfe > Benutzerhandbuch öffnet es immer am Anfang.

Das Handbuch ist Teil des Programms und funktioniert daher ohne Internetverbindung. Es erscheint in der Oberflächensprache des Programms, wenn eine Übersetzung existiert, sonst auf Englisch.

## Erste Schritte {#getting-started}

1. Öffnen Sie Datei > Wiedergabelisten-Manager (Ctrl+M) und fügen Sie Ihren Anbieter hinzu: eine M3U-Wiedergabelistendatei oder -adresse, ein Xtream-Codes-Konto oder ein Stalker-Portal-Konto. Wählen Sie OK. Die Sender laden im Hintergrund.
2. Wenn Ihr Anbieter eine Adresse für die Programmzeitschrift (EPG) liefert, tragen Sie sie unter Datei > EPG-Manager (Ctrl+E) ein. Xtream-Codes-Konten können das für Sie übernehmen.
3. Importieren Sie die Zeitschrift mit Datei > EPG in Datenbank importieren (Ctrl+I). Das läuft im Hintergrund und meldet sich, wenn es fertig ist.
4. Wählen Sie eine Kategorie, wählen Sie einen Sender und drücken Sie Enter, um ihn abzuspielen.

Ihre Wiedergabelisten, Zeitschriftenquellen und Einstellungen bleiben zwischen Sitzungen erhalten; dies muss also nur einmal erledigt werden.

## Das Hauptfenster {#main-window}

Im Hauptfenster blättern Sie durch die Sender und spielen sie ab. Tab wandert in dieser Reihenfolge durch die Steuerelemente, Shift+Tab geht zurück:

1. Wiedergabelistenansicht: welche Wiedergabeliste durchgeblättert wird.
2. Kategorien: die Sendergruppen.
3. Suchen: filtert die Senderliste.
4. Sender: die Sender der gewählten Kategorie bzw. die Suchtreffer.
5. Folgenbeschreibung: was gerade auf dem markierten Sender läuft.
6. Stream-URL: die Adresse des markierten Senders, nur sichtbar, wenn Optionen > Stream-URL anzeigen eingeschaltet ist.

Nach dem letzten Steuerelement springt Tab zum ersten zurück.

Unter Linux liegen die Menüs, die dieses Handbuch beschreibt, unter der Menü-Schaltfläche oben im Fenster.

### Wiedergabelistenansicht {#playlist-view}

Wenn Sie mehr als eine Wiedergabeliste haben, wählt die Liste Wiedergabelistenansicht, was Kategorien und Sender zeigen: Alle Wiedergabelisten oder eine einzelne. Ihre Auswahl wird gemerkt.

### Kategorien {#categories}

Die Kategorieliste enthält die Sendergruppen Ihrer Wiedergabelisten. Ihre ersten Zeilen sind Alle Sender und - sobald Sie welche hinzugefügt haben - Favoriten. Jede Zeile nennt, wie viele Sender sie enthält.

- Pfeil auf und ab bewegen sich durch die Kategorien, ohne die Senderliste zu ändern; Sie können sie also erst einmal anhören.
- Enter öffnet die markierte Kategorie und springt zur Senderliste.
- Tab öffnet die markierte Kategorie und springt zum Suchfeld.
- Pfeil links und rechts klappen eine Kategorie mit Untergruppen zu bzw. auf.

### Suchen {#search}

Tippen Sie ins Suchfeld, um die Senderliste zu filtern, und drücken Sie dann Enter oder Tab, um den Filter anzuwenden und weiterzugehen. Die Suche in Alle Sender durchsucht auch die Programmzeitschrift; eine Suche nach einem Sendungstitel listet also die Sender auf, die sie zeigen. Leeren Sie das Feld und drücken Sie Enter, um wieder die ganze Kategorie zu sehen.

### Die Senderliste {#channel-list}

Die Senderliste zeigt die Sender der gewählten Kategorie oder Suche.

- Enter spielt den markierten Sender ab.
- Die Anwendungstaste, Shift+F10 oder ein Rechtsklick öffnet das Menü des Senders: Wiedergeben, Zu Favoriten hinzufügen bzw. Aus Favoriten entfernen, Aufnehmen bzw. Aufnahme stoppen, Aufnahme planen, EPG anzeigen…, sowie Nachholen bei Sendern mit Archiv.
- Ctrl+D fügt den Sender zu den Favoriten hinzu bzw. entfernt ihn. In der Kategorie Favoriten entfernt ihn die Entf-Taste.
- Ctrl+Shift+R startet die Aufnahme des Senders; noch einmal gedrückt, stoppt sie.

Favoritensender sind mit „(Favorit)“ markiert, und jede Zeile nennt auch die Sendung, die gerade läuft, wenn die Zeitschrift sie führt. Wenn eine Suche auch Sendungen fand, nennen ihre Zeilen die Sendung und den Sender, auf dem sie läuft.

### Folgenbeschreibung und Stream-URL {#episode-description}

Tab von der Senderliste gelangt zur Folgenbeschreibung: die Sendung, die gerade auf dem markierten Sender läuft, mit Zeiten und Beschreibung, und was danach kommt. Shift+Tab springt direkt zurück zur Senderliste. Der Text folgt dem markierten Sender.

Wenn Optionen > Stream-URL anzeigen eingeschaltet ist, folgt das Stream-URL-Feld einen Tab später. Es zeigt die Adresse des Senders, was bei Fehlermeldungen helfen kann. Die meisten lassen es ausgeschaltet.

## Favoriten {#favorites}

Die Favoriten halten die Sender, die Sie am häufigsten ansehen, an einem Ort. Drücken Sie Ctrl+D auf einem Sender, benutzen Sie sein Menü oder Ansicht > Zu Favoriten hinzufügen. Favoriten erscheinen in der Kategorie Favoriten nahe dem Anfang der Kategorieliste; Ansicht > Zu den Favoriten wechseln führt Sie dorthin.

Um einen Favoriten zu entfernen, drücken Sie erneut Ctrl+D auf ihm oder Entf in der Kategorie Favoriten.

Favoriten werden nach Anbieter und Sender gespeichert, nicht nach Stream-Adresse, und überstehen so eine Aktualisierung der Wiedergabeliste. Über Ihr Konto wird nichts dabei gespeichert.

## Video-on-Demand {#video-on-demand}

Ansicht > Video-on-Demand (Filme && Serien) schaltet die Kategorieliste von Live-Sendern auf die Filme und Serien Ihres Anbieters um. Kategorien heißen Movies oder Series, gefolgt von der Anbieterkategorie. Die Wahl einer Serie listet ihre Folgen in Staffel- und Folgenreihenfolge. Drücken Sie Enter, um einen Film oder eine Folge abzuspielen.

Ansicht > Live-TV && Nachholen schaltet auf Live-Sender zurück. Das Suchfeld leert sich beim Wechsel.

Video-on-Demand funktioniert am besten mit Xtream-Codes-Konten, die ihr Angebot korrekt beschreiben. Bei reinen M3U-Wiedergabelisten erkennt das Programm Filme und Serien an ihren Gruppennamen und Folgennummern.

## Wiedergabelisten-Manager {#playlist-manager}

Datei > Wiedergabelisten-Manager (Ctrl+M) listet Ihre Wiedergabelistenquellen auf. Er öffnet mit dem Fokus auf der Liste.

- Datei hinzufügen: eine M3U- oder M3U8-Wiedergabeliste auf Ihrem Computer.
- URL hinzufügen: die Internetadresse einer M3U-Wiedergabeliste.
- Xtream Codes hinzufügen: ein Xtream-Codes-Konto.
- Stalker Portal hinzufügen: ein Stalker-Portal-Konto (MAG).

Auf einer Quelle in der Liste öffnet die Anwendungstaste oder Shift+F10 ihr Menü: URL kopieren, Umbenennen (F2) und Löschen (Entf). Ein Name, den Sie einer Quelle geben, ist nur ein Etikett; er ändert die Quelle nicht.

Wählen Sie OK, um Ihre Änderungen zu behalten, oder Abbrechen, um sie zu verwerfen. Nach OK laden die Sender neu.

### Xtream-Codes-Konten {#xtream-codes}

Ein Xtream-Codes-Konto braucht die Serveradresse, Ihren Benutzernamen und Ihr Passwort, die Ihr Anbieter Ihnen gibt. Der Name ist Ihr eigenes Etikett für das Konto. Lassen Sie „XMLTV-URL automatisch hinzufügen“ angehakt, damit die Programmzeitschrift des Anbieters gleichzeitig in den EPG-Manager kommt.

Xtream-Codes-Konten geben Ihnen außerdem Video-on-Demand, wo angeboten, Nachholen, und den Kontostand unter Datei > Kontoinformationen.

### Stalker-Portal-Konten {#stalker-portal}

Ein Stalker-Portal-Konto braucht die Portaladresse und die MAC-Adresse, die Ihr Anbieter für Sie registriert hat. Manche Portale wollen zusätzlich Benutzername und Passwort. „MAC zufällig generieren“ erfindet eine neue MAC-Adresse, was nur nützlich ist, wenn der Anbieter Sie eine wählen lässt. „Versuchen, das XMLTV des Anbieters hinzuzufügen“ übernimmt die Zeitschrift des Portals, wenn es eine hat.

## Programmzeitschrift (EPG) {#epg}

Die Programmzeitschrift, das EPG, sagt Ihnen, was auf jedem Sender jetzt und später läuft. Sie stammt aus XMLTV-Dateien, die Ihr Anbieter oder eine andere Quelle veröffentlicht. Das Programm importiert sie in eine lokale Datenbank und benutzt sie für die Folgenbeschreibung, Jetzt im Programm, EPG anzeigen…, Nachholen-Listen und Suchen.

### EPG-Manager {#epg-manager}

Datei > EPG-Manager (Ctrl+E) listet Ihre Zeitschriftenquellen auf.

- Datei hinzufügen: eine XMLTV-Datei auf Ihrem Computer (.xml oder .xml.gz).
- URL hinzufügen: die Internetadresse einer XMLTV-Zeitschrift.

Die Anwendungstaste oder Shift+F10 auf einer Quelle öffnet ihr Menü: URL kopieren, Umbenennen (F2) und Löschen (Entf). Wählen Sie OK, um Ihre Änderungen zu behalten.

### Die Zeitschrift importieren {#import-epg}

Datei > EPG in Datenbank importieren (Ctrl+I) lädt jede Zeitschriftenquelle herunter und füllt die Zeitschriftendatenbank. Es läuft im Hintergrund; Sie können weiter ansehen und blättern, und eine Nachricht meldet sich, wenn es fertig ist. Große Zeitschriften können mehrere Minuten dauern.

Die Zeitschrift wird auch von Zeit zu Zeit automatisch und lautlos aufgefrischt. Sender werden über ihre Zeitschriftenkennung und ihre Namen zugeordnet, einschließlich der üblichen Länder- und Qualitätsvarianten in Sendernamen.

Wenn eine importierte Zeitschrift bei einem Sender nicht erscheint, prüfen Sie, ob eine Ihrer Quellen ihn abdeckt, und importieren Sie erneut. Der Import schreibt ein ausführliches Protokoll; siehe Fehlerbehebung.

### Jetzt im Programm {#whats-on-now}

Datei > Jetzt im Programm (Ctrl+W) listet jede Sendung, die gerade über alle Sender läuft, in der Form „Sendung - Sender“.

- Tippen von Buchstaben springt zur ersten Sendung, die damit beginnt.
- Tab wechselt zum Filterfeld; dort getippt engt die Liste auf passende Sendungen oder Sender ein.
- Enter oder die Wiedergeben-Schaltfläche spielt den Sender ab.
- Aufnahme planen, oder das Menü der Sendung, plant ihre Aufnahme.
- Escape schließt das Fenster.

### Senderzeitschrift (EPG anzeigen) {#channel-epg}

EPG anzeigen…, im Menü eines Senders, listet die Sendungen dieses Senders von der laufenden bis so weit, wie die Zeitschrift reicht. Die laufende Sendung steht zuerst.

- Tab wechselt zwischen der Liste und der Beschreibung der markierten Sendung.
- Die Anwendungstaste oder Shift+F10 auf einer Sendung bietet Aufnahme planen an.
- Escape schließt das Fenster.

## Nachholen {#catch-up}

Sender, die ein Archiv führen, lassen Sie Sendungen ansehen, die schon gelaufen sind. Solche Sender haben Nachholen in ihrem Menü in der Senderliste. Es öffnet das Nachholen-Fenster des Senders, das seine vergangenen Sendungen mit Datum und Uhrzeit auflistet.

- Pfeil auf und ab bewegen sich durch die Sendungen.
- Enter spielt die markierte Sendung ab.
- Die Anwendungstaste oder Shift+F10 öffnet ihr Menü: Öffnen, um sie abzuspielen, und Herunterladen, um sie als Datei zu speichern.
- Tab wechselt zur Beschreibung der Sendung und zurück.
- Escape schließt das Fenster.

Wenn Sie den integrierten Player nach einer nachgeholten Sendung schließen, kehren Sie zur Nachholen-Liste an derselben Sendung zurück.

Wie weit zurück Sie gehen können, hängt von Ihrem Anbieter ab, meist einige Tage.

### Nachholen-Downloads {#catch-up-downloads}

Herunterladen speichert eine nachgeholte Sendung in Ihren Download-Ordner (siehe Aufnahmen), benannt nach Sender und Ausstrahlungszeit der Sendung. Jeder Download hat sein eigenes Fenster mit Fortschritt, verstrichener Zeit, verbleibender Zeit und bisheriger Größe, alles in einem schreibgeschützten Feld.

- Escape oder das Schließen des Fensters versteckt es; der Download läuft weiter.
- Ansicht > Downloads anzeigen (Ctrl+Shift+D) holt die Downloadfenster zurück.
- Abbrechen stoppt den Download nach einer Rückfrage. Ein abgebrochener Download kann nicht fortgesetzt werden.

Schlägt ein Download fehl, sagt das Fenster warum und versucht es automatisch noch ein paar Mal, wenn das Problem vorübergehend sein kann. Viele Anbieter erlauben nur einen Stream zurzeit; stoppen Sie andere Wiedergaben desselben Kontos, wenn ein Download abgelehnt wird.

## Integrierter Player {#built-in-player}

Der integrierte Player spielt Sender innerhalb des Programms ab. Er öffnet sich, wenn Sie einen Sender abspielen, es sei denn, Optionen > Player bei Eingabetaste anzeigen ist ausgeschaltet; dann startet die Wiedergabe ohne Fenster.

Seine Steuerelemente in Tab-Reihenfolge: Wiedergabe/Pause, Stopp, Aufnehmen, Übertragen, Vollbild, der Lautstärkeregler und Tonspur wählen.

Tasten im Player:

- Leertaste: drückt die fokussierte Schaltfläche, bei Wiedergabe/Pause also Pause und Weiter.
- Ctrl+P: wiedergeben oder pausieren.
- Ctrl+S: stoppen.
- Ctrl+R: aufnehmen, was Sie ansehen, und diese Aufnahme stoppen.
- Pfeil auf und ab: Lautstärke in 2%-Schritten. Ctrl+Pfeil auf/ab: 5%-Schritte.
- A: nächste Tonspur.
- D: das Audioausgabegerät wählen.
- Ctrl+C: an ein Gerät übertragen.
- F11: Vollbild an oder aus. Escape verlässt den Vollbildmodus.
- Ctrl+W: das Playerfenster ausblenden; die Wiedergabe läuft weiter.
- Ctrl+Q: den Player schließen und die Wiedergabe stoppen.

Dieselben Befehle liegen im Wiedergabe-Menü des Players. Der Player verbindet sich von selbst neu, wenn ein Live-Stream abreißt, und behält die gewählte Tonspur.

### Tonspuren {#audio-tracks}

Sender können mehrere Tonspuren mitführen, etwa andere Sprachen oder Audiodeskription. Drücken Sie A für die nächste Spur, benutzen Sie Wiedergabe > Audiospur, oder Tab zu Tonspur wählen, die immer die laufende Spur nennt.

Eine gewählte Spur wird pro Sender gemerkt und kommt beim nächsten Mal wieder. Zum automatischen Wählen siehe Bevorzugte Audiospur.

### Audioausgabegerät {#audio-output-device}

Wiedergabe > Audioausgabegerät… (D) wählt die Lautsprecher oder Kopfhörer, die der Player benutzt, etwa um TV-Ton von Ihrem Screenreader fernzuhalten. Systemstandard folgt dem Windows-Standardgerät. Die Wahl wird gemerkt.

### Den Player aus dem Hauptfenster steuern {#player-from-main-window}

Das Player-Menü im Hauptfenster steuert den integrierten Player, ohne zu ihm zu wechseln:

- Integrierten Player anzeigen: Ctrl+Shift+J.
- Wiedergabe/Pause: Ctrl+Shift+P.
- Stopp: Ctrl+Shift+S.
- Übertragen / Verbinden…: Ctrl+Shift+C.
- Ctrl+Pfeil auf und Ctrl+Pfeil ab ändern die Lautstärke.

## Medienplayer {#media-player}

Optionen > Zu verwendender Medienplayer wählt, was Ihre Sender abspielt: der Integrierte Player oder ein externer Player wie VLC, MPC, MPC-BE, MPV, PotPlayer, Kodi oder SMPlayer. Benutzerdefinierter Player… lässt Sie jedes andere Programm über seine Datei wählen.

Aufnahme, Nachholen-Downloads und Übertragen funktionieren bei jedem Player gleich. Die Tonspur-Funktionen und die in diesem Handbuch beschriebenen Playertasten gehören zum integrierten Player.

## Bevorzugte Audiospur {#preferred-audio-track}

Optionen > Bevorzugte Audiospur lässt den integrierten Player selbst eine Tonspur wählen.

- „Audiodeskriptionsspur bevorzugen, wenn der Sender eine anbietet“ wählt überall Audiodeskription, wo sie angeboten wird. Es erkennt die Namen, die Anbieter tatsächlich in mehreren Sprachen benutzen, etwa audio description, AD, Audiodeskription und Hörfilm, sowie das Kennzeichen, das Rundfunkanstalten auf solche Spuren setzen.
- Das Textfeld nimmt Spurnamen oder Sprachen auf, meistgewünschte zuerst, durch Kommata getrennt, zum Beispiel: audio description, German. Leer gelassen, bleibt es bei der Spur, mit der ein Sender startet.

Eine von Hand gewählte Spur wird pro Sender gemerkt und hat beim nächsten Ansehen Vorrang vor diesen Regeln. Die zuletzt irgendwo gewählte Spur gilt für Sender, für die Sie nie eine gewählt haben.

Aufnahmen folgen derselben Wahl. Eine reine Audioaufnahme behält die eine Spur, die Sie gehört hätten; eine Videoaufnahme behält alle Spuren und markiert jene als Standard.

## Aufnahmen {#recordings}

Das Programm kann jeden Sender in eine Datei aufnehmen, während Sie etwas anderes ansehen oder gar nichts läuft.

- Aufnahmen > Aufnahme starten (Ctrl+Shift+R) nimmt den markierten Sender auf. Noch einmal gedrückt, stoppt sie.
- Aufnehmen im Menü eines Senders tut dasselbe; Aufnehmen im integrierten Player (Ctrl+R) nimmt auf, was Sie ansehen.
- Aufnahmen > Aufnahme stoppen stoppt die Aufnahme des markierten Senders, Alle Aufnahmen stoppen stoppt alle.
- Aufnahmen > Aufnahmeordner öffnen öffnet den Ordner, in dem die Dateien landen.
- Aufnahmen > Download-Ordner festlegen… wählt diesen Ordner. Nachholen-Downloads landen ebenfalls dort.

Das Aufnehmen des laufenden Programms im integrierten Player benutzt dieselbe Verbindung zum Anbieter und funktioniert daher auch bei Konten, die nur einen Stream zurzeit erlauben.

Das Stoppen einer Aufnahme kann einen Moment dauern, bis die Datei fertiggestellt ist. Beim Schließen des Programms dürfen laufende Aufnahmen ihre Dateien eigenständig abschließen.

### Aufnahmeformat {#recording-formats}

Aufnahmen > Aufnahmeformat wählt, wie Aufnahmen gespeichert werden:

- Anbieterqualität (Kopie, MKV): der Stream genau wie ausgestrahlt, mit allen Audio- und Untertitel-Spuren. Behält alles, was der Anbieter sendet.
- Anbieterqualität (Kopie, MP4): dasselbe Bild und derselbe Ton in einer MP4-Datei, die mehr Geräte abspielen, ohne Untertitel und Videotext.
- x264-Neucodierung (MKV oder MP4): eine kleinere, neu kodierte Datei. Braucht viel mehr Prozessorzeit.
- Nur Audio (MP3 V0, FLAC, WAV, AAC M4A oder Opus): nur der Ton, nützlich für Radio.

### Geplante Aufnahmen {#scheduled-recordings}

Um eine künftige Sendung aufzunehmen, wählen Sie Aufnahme planen auf einer Sendung in EPG anzeigen…, Jetzt im Programm oder einer Sendungszeile in den Suchtreffern. Aufnahme planen auf einem Sender öffnet seine Zeitschrift, damit Sie zuerst die Sendung wählen.

Aufnahmen > Geplante Aufnahmen… listet jede geplante, laufende und fertige Aufnahme mit Zeit, Titel, Sender, Status und Format.

- Die Anwendungstaste oder Shift+F10 auf einer Aufnahme öffnet ihr Menü: Aktualisieren, Abbrechen und Löschen.
- Löschen entfernt die markierte Aufnahme aus der Liste; eine laufende wird vorher nach Rückfrage gestoppt.
- Escape schließt das Fenster.

Geplante Aufnahmen starten von selbst, während das Programm läuft, auch wenn es in den Infobereich minimiert ist.

### Zeitpuffer für Aufnahmen {#schedule-padding}

Sendungen beginnen und enden selten genau auf die Minute. Aufnahmen > Zeitpuffer für Aufnahmen… legt fest, wie viele Minuten vor einer Sendung eine geplante Aufnahme beginnt und wie viele Minuten nach ihrem Ende sie weiterläuft. Manuelle Aufnahmen sind nicht betroffen.

### Herunterfahren nach Aufnahmen {#shutdown-after-recordings}

Aufnahmen > Computer herunterfahren, wenn die Aufnahmen fertig sind schaltet den Computer aus, sobald jede laufende und geplante Aufnahme fertig ist - nützlich für eine nächtliche Aufnahme.

Es greift nie, während noch etwas aufgenommen wird oder wartet. Ist es so weit, zählt ein Fenster 60 Sekunden herunter; der Fokus liegt auf Herunterfahren abbrechen, also stoppen Enter oder Escape es, und Jetzt herunterfahren wartet nicht. Die Option schaltet sich nach einmaliger Benutzung oder einem Abbruch selbst aus.

## Übertragen {#casting}

Übertragen schickt einen Sender an ein Fernsehgerät oder einen Lautsprecher in Ihrem Netz: Chromecast-Geräte, DLNA- und UPnP-Renderer sowie AirPlay-Geräte wie Apple TV und HomePod.

Datei > Übertragen an… durchsucht Ihr Netz und listet die gefundenen Geräte. Wählen Sie ein Gerät und Verbinden. Manche AirPlay-Geräte verlangen zuerst Koppeln…, das nach dem auf dem Fernseher gezeigten Code fragt. Nach dem Verbinden schickt das Abspielen eines Senders ihn an das Gerät. Erneutes Übertragen an… trennt.

Die Übertragen-Schaltfläche im integrierten Player, Player > Übertragen / Verbinden… (Ctrl+Shift+C) und Ctrl+C im Player tun dasselbe.

Für das Übertragen müssen Computer und Gerät im selben Netz sein.

## Kontoinformationen {#account-info}

Datei > Kontoinformationen (Ctrl+Shift+A) zeigt den Stand Ihrer Xtream-Codes- und Stalker-Portal-Konten: ob das Konto aktiv ist, sein Ablaufdatum und die verbleibenden Tage, ob es ein Testkonto ist, und wie viele Verbindungen es erlaubt und offen hat. In Wiedergabelistenadressen gefundene Konten werden ebenfalls aufgelistet.

Wählen Sie ein Konto in der Liste; seine Einzelheiten erscheinen im schreibgeschützten Feld darunter. Aktualisieren fragt den Anbieter erneut, Details kopieren legt die Einzelheiten auf die Zwischenablage. Passwörter werden nie gezeigt.

## Optionen {#options}

Das Optionen-Menü enthält die Einstellungen des Programms. Jede wird gespeichert, sobald Sie sie ändern.

- Zu verwendender Medienplayer: siehe Medienplayer.
- Bevorzugte Audiospur: siehe Bevorzugte Audiospur.
- Sprache: siehe Sprache.
- In den Infobereich minimieren: siehe Infobereich.
- Player bei Eingabetaste anzeigen: eingeschaltet zeigt das Abspielen eines Senders das Playerfenster. Ausgeschaltet startet die Wiedergabe und der Fokus bleibt in der Senderliste.
- Stream-URL anzeigen: fügt das Stream-URL-Feld hinter der Folgenbeschreibung im Hauptfenster ein.
- Automatisch nach Updates suchen: siehe Updates.

### Sprache {#language}

Optionen > Sprache wählt die Programmsprache. Automatisch folgt Ihrer Windows- bzw. Desktop-Sprache und benutzt Englisch, wenn es dafür keine Übersetzung gibt. Die Änderung greift vollständig nach einem Neustart des Programms.

Das Programm gibt es auf Englisch, Spanisch, Arabisch, Brasilianisches Portugiesisch, Französisch, Deutsch, Russisch, Türkisch, Italienisch, Polnisch, Hindi, vereinfachtem Chinesisch, Japanisch und Ungarisch. Korrekturen und neue Sprachen sind willkommen; siehe Hilfe holen.

### Infobereich {#system-tray}

Wenn Optionen > In den Infobereich minimieren eingeschaltet ist, versteckt das Schließen oder Minimieren des Hauptfensters es im Benachrichtigungsbereich, statt das Programm zu beenden; so laufen geplante Aufnahmen weiter. Aktivieren Sie das Symbol im Infobereich, um das Fenster zurückzuholen. Sein Menü hat auch Wiederherstellen, Player-Steuerung, während einer Aufnahme Aufnahme(n) stoppen, sowie Beenden.

Um das Programm ganz zu beenden, benutzen Sie Datei > Beenden (Ctrl+Q).

## Updates {#updates}

Unter Windows kann sich das Programm selbst aktualisieren. Hilfe > Nach Updates suchen… sucht jetzt nach einer neuen Version, Optionen > Automatisch nach Updates suchen prüft von Zeit zu Zeit im Hintergrund.

Gibt es ein Update, erfahren Sie, was neu ist, und werden gefragt, ob Sie es installieren wollen. Der Download wird geprüft, bevor etwas installiert wird. Das Programm schließt sich während des Updates und startet danach von selbst neu, dann meldet es, ob es gelang. Ihre Einstellungen, Favoriten und Aufnahmen bleiben erhalten.

Unter Linux installieren Sie stattdessen das neue Paket über das alte.

## Fehlerbehebung {#troubleshooting}

- Hilfe > Protokollordner öffnen öffnet den Ordner mit den Protokolldateien des Programms, einschließlich des Protokolls der Zeitschriftenimporte und eines Protokolls pro Aufnahme.
- Hilfe > Protokoll und Debug-Informationen kopieren legt einen Bericht mit Programmversion, Ihrem System und frischen Protokollzeilen auf die Zwischenablage, bereit zum Einfügen in einen Fehlerbericht. Er enthält Ihre Stream-Adressen, in denen Ihre Anbieteranmeldung stecken kann; prüfen Sie ihn, bevor Sie ihn öffentlich teilen.

Häufige Probleme:

- Ein Sender spielt nicht: viele Anbieter erlauben nur einen Stream pro Konto zurzeit. Stoppen Sie andere Wiedergaben, Aufnahmen oder Downloads desselben Kontos und versuchen Sie es erneut.
- Ein Sender hat keine Zeitschrift: prüfen Sie, ob eine Ihrer EPG-Quellen ihn abdeckt, und importieren Sie die Zeitschrift erneut.
- Wiedergabe stockt: der integrierte Player stellt seinen Puffer selbst ein. Sie können internal_player_buffer_seconds und internal_player_max_buffer_seconds in der iptvclient.conf für einen geduldigeren Puffer erhöhen.
- Nachholen sagt, die Sendung sei nicht verfügbar: sie ist vermutlich älter als das Archiv Ihres Anbieters.

## Tastenkürzel {#keyboard-shortcuts}

Überall:

- F1: Hilfe zu dem, was Sie gerade benutzen.

Hauptfenster:

- Ctrl+M: Wiedergabelisten-Manager.
- Ctrl+E: EPG-Manager.
- Ctrl+I: EPG in Datenbank importieren.
- Ctrl+W: Jetzt im Programm.
- Ctrl+Shift+A: Kontoinformationen.
- Ctrl+D: den gewählten Sender zu den Favoriten hinzufügen bzw. entfernen.
- Entf: den gewählten Sender aus den Favoriten entfernen, in der Kategorie Favoriten.
- Ctrl+Shift+R: die Aufnahme des gewählten Senders starten oder stoppen.
- Ctrl+Shift+D: die Nachholen-Downloadfenster zeigen.
- Ctrl+Shift+J: den integrierten Player zeigen.
- Ctrl+Shift+P: den integrierten Player wiedergeben oder pausieren.
- Ctrl+Shift+S: den integrierten Player stoppen.
- Ctrl+Shift+C: übertragen oder verbinden.
- Ctrl+Pfeil auf und Ctrl+Pfeil ab: Lautstärke des integrierten Players.
- Enter: den gewählten Sender abspielen.
- Anwendungstaste oder Shift+F10: das Menü des Senders.
- Ctrl+Q: beenden.

Integrierter Player:

- Leertaste: die fokussierte Schaltfläche drücken, etwa Pause.
- Ctrl+P: wiedergeben oder pausieren.
- Ctrl+S: stoppen.
- Ctrl+R: aufnehmen.
- Pfeil auf und ab: Lautstärke in 2%-Schritten; mit Ctrl 5%-Schritte.
- A: nächste Tonspur.
- D: Audioausgabegerät.
- Ctrl+C: übertragen.
- F11: Vollbild; Escape verlässt den Vollbildmodus.
- Ctrl+W: den Player ausblenden.
- Ctrl+Q: den Player schließen.

Quellenlisten im Wiedergabelisten-Manager und EPG-Manager:

- F2: umbenennen.
- Entf: löschen.

## Hilfe holen {#support}

Fragen, Fehlerberichte und Release-Neuigkeiten:

- Die SerrebiProjects-Telegrammgruppe: https://t.me/SerrebiProjects
- Fehlerberichte und Vorschläge auf GitHub: https://github.com/serrebidev/Accessible-IPTV-Client/issues

Hilfe > Über… zeigt die laufende Version und verlinkt beides. Bei einem Problem liefert Hilfe > Protokoll und Debug-Informationen kopieren die nötigen Einzelheiten.

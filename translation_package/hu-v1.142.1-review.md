# A v1.142.1 magyar fordításának ismételt lektorálása

Állapot: helyben elkészített, még be nem küldött fordítási csomag.

## Hatókör és eredmény

A felülvizsgálat a v1.141.1 és a v1.142.1 közötti új szövegekre terjed ki. A korábban meglévő magyar fordítások változatlanok. Az alkalmazás működését meghatározó programkód nem módosult.

- A magyar súgó valamennyi új bekezdésének és felsorolási pontjának nyelvi, terminológiai és működés szerinti ellenőrzése megtörtént.
- A kezelőfelület 56 új katalógusbejegyzése ismételt lektoráláson esett át.
- A shortcuts.py fájl öt további, fordításra előkészített, de a katalógusból kimaradt hibaüzenete bekerült a magyar PO- és MO-fájlba. Így összesen 61 új alkalmazásszöveg kapott fordítást.
- A kiadási jegyzetek két új bejegyzését az angol eredetivel összevetve ellenőriztem.
- Az alábbi, jelenleg közvetlenül angolul megjelenő szövegekhez elkészült a magyar változat. Aktiválásukhoz fejlesztői beavatkozás szükséges.

## Fontosabb lektori módosítások

A „What Is Playing” parancs magyar neve „Aktuális műsorinformációk”. Ez a megnevezés a televíziós és a rádiós tartalomhoz egyaránt illeszkedik. A bemondásban a műsorcím után a „Kezdés” és a „befejezés” szó különbözteti meg az időpontokat; értelmezésük nem függ a gondolatjel felolvasásától.

A „Record Daily” és a „Record Weekly” fordítása „Rögzítés naponta”, illetve „Rögzítés hetente”. A „Record Series” megnevezése „Azonos című műsorok rögzítése”, mivel a program az adott csatorna műsorújságában cím alapján keres egyezést; nem követeli meg, hogy az adás televíziós sorozat legyen.

Az ütközésről szóló figyelmeztetés egyértelművé teszi, hogy a rögzítések időtartama részben is egybeeshet. A csatornaszámot tartalmazó hibaüzenetben nincs „A(z)” alak. A billentyűparancs szerkesztésekor a kérdés pontosan jelzi, hogy a hozzárendelt kombináció módosítható.

## Két pontossági javítás a súgóban

1. A Lejátszás > Feliratok almenü a sávválasztást tartalmazza. A Feliratfájl betöltése külön parancs a Lejátszás menüben; nem a Feliratok almenü része. Ellenőrzési hely: internal_player.py, _build_menu_bar és _on_subtitle_menu_open.
2. A napi, heti és azonos című adásokra vonatkozó rögzítési parancsok a műsorújság és a Most adásban ablak műsorainak helyi menüjében szerepelnek. A súgó új bekezdése ezt tükrözi; nem az Ütemezett felvételek listájához irányítja a felhasználót. Ellenőrzési hely: main.py, WhatsOnNowDialog és ChannelEPGDialog.

E két helyen az angol súgó megfogalmazása is pontosításra szorul. A magyar változatot az ellenőrzött programkódhoz igazítottam; az angol dokumentumot nem módosítottam.

## A fordítási folyamatból kimaradt modul

A tools/i18n_tools.py SOURCE_FILES listájában jelenleg nem szerepel a shortcuts.py. Ezért az alábbi öt, már gettext-hívással ellátott szöveg kimaradt a kiadás katalógusaiból:

| Angol forrásszöveg | Magyar fordítás |
| --- | --- |
| Invalid keyboard shortcut. | Érvénytelen billentyűkombináció. |
| Unknown command. | Ismeretlen parancs. |
| Main-window shortcuts need Ctrl or Alt. | A főablak billentyűparancsainak tartalmazniuk kell a Ctrl vagy az Alt billentyűt. |
| F1 is reserved for Help. | Az F1 billentyű a súgó számára van fenntartva. |
| Shortcut conflicts with {command}. | A billentyűkombináció ütközik az alábbi parancs hozzárendelésével: {command}. |

Ezek a csomag magyar katalógusában már szerepelnek. A fejlesztőnek a shortcuts.py fájlt is fel kell vennie a szövegkinyerés forrásai közé, különben a következő katalógusfrissítés eltávolíthatja a kézzel pótolt bejegyzéseket.

A {command} értéke jelenleg belső parancsazonosítóból származik: például a play_pause „play pause” alakban kerül az üzenetbe. A fejlesztőnek itt az adott környezethez tartozó, már lefordított menü- vagy parancsnevet kell átadnia. A változó megőrzése önmagában nem magyarítja annak tartalmát.

## Közvetlenül angolul megjelenő új szövegek

Az alábbi fordítások készen állnak a beépítésre, de a jelenlegi forráskód nem hívja meg hozzájuk a fordítási réteget. Pusztán a PO- vagy MO-fájl cseréje ezért nem teszi őket magyarul elérhetővé.

### Biztonsági mentési hibák – settings_backup.py

| Angol forrásszöveg | Magyar fordítás |
| --- | --- |
| A backup password is required. | Adja meg a biztonsági mentés jelszavát. |
| Settings are too large to back up. | A beállítások mérete meghaladja a biztonsági mentés megengedett felső határát. |
| Backup file is too large. | A biztonsági mentés fájlmérete meghaladja a megengedett felső határt. |
| Not an Accessible IPTV settings backup. | A kiválasztott fájl nem az Accessible IPTV Client beállításainak biztonsági mentése. |
| Invalid backup salt. | A biztonsági mentéshez tartozó kriptográfiai só érvénytelen. |
| Wrong password or damaged backup. | A jelszó hibás, vagy a biztonsági mentés sérült. |
| Backup settings are invalid. | A biztonsági mentés érvénytelen beállításokat tartalmaz. |

Az első üzenet fordítása már szerepel az alkalmazáskatalógusban, mert a main.py is használja. A settings_backup.py azonban közvetlen angol szöveget ad át. A saját hibaüzenetekhez gettext-hívást és a modul szövegkinyerésbe történő felvételét javaslom. A rendszerből vagy külső könyvtárból származó kivételek ettől még az eredeti nyelven érkezhetnek.

### Fájltípusok neve a megnyitási és mentési ablakokban

A szűrőmintákat és elválasztójeleket változatlanul kell megőrizni.

| Hely | Teljes angol szűrő | Teljes magyar szűrő |
| --- | --- | --- |
| main.py, _export_settings és _import_settings | Accessible IPTV backup (*.aiptv)&#124;*.aiptv | Accessible IPTV biztonsági mentés (*.aiptv)&#124;*.aiptv |
| internal_player.py, _load_subtitle_file | Subtitle files (*.srt;*.ass;*.ssa;*.vtt)&#124;*.srt;*.ass;*.ssa;*.vtt | Feliratfájlok (*.srt;*.ass;*.ssa;*.vtt)&#124;*.srt;*.ass;*.ssa;*.vtt |

A táblázatban a &#124; jel a szűrő tényleges függőleges elválasztójelét jelenti. E két szöveget a fejlesztőnek fordítási hívással kell ellátnia, majd fel kell vennie a katalógusba.

### Új ütemezési állapotüzenet

A dvr.py új, tárolt állapotüzenete:

- Angol: Series recording canceled.
- Magyar: Az azonos című műsorok felvételi ütemezése visszavonva.

Ez jelenleg belső feladatadatként szerepel; a vizsgált felületen nem azonosítottam közvetlen megjelenítési helyet. Ha később látható vagy felolvasott üzenetté válik, megjelenítéskor kell fordítani. A tárolt adatok nyelvfüggő átírását nem javaslom.

## Beépítendő fájlok és ellenőrzési határok

- docs/help/hu.md
- docs/help-sync.json – kizárólag a magyar bejegyzés frissült.
- locale/hu/LC_MESSAGES/iptvclient.po és iptvclient.mo
- locale/hu/LC_MESSAGES/release_notes.po és release_notes.mo

A katalógusok formai helyessége, a változók megőrzése, a fordítások lefedettsége, a súgó szerkezete és a korábbi szövegek változatlansága ellenőrizhető. A szövegösszeállítás próbája a katalógus tényleges betöltésével történt. Élő Windows-, JAWS- vagy NVDA-próba nem történt; a képernyőolvasós működés igazolásához külön felhasználói teszt szükséges.

A munkapéldányban már a fordítási munka előtt eltérést mutató ffmpeg.exe nem része a fordítási csomagnak.

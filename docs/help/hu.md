<!--
Az Accessible IPTV Client felhasználói útmutatója, magyarul.

Megjegyzések a fordítóhoz (a magyar szöveg fenntartója):
- Az angol referencia a docs/help/en.md fájl. A fejlécekben lévő {#téma-azonosító}
  azonosítókat változatlanul kell hagyni, csak a címsor szövegét szabad fordítani.
- Egy még lefordítatlan szakasz egyszerűen kihagyható: az F1 akkor az angol
  szakaszt nyitja meg.
-->

# Az Accessible IPTV Client felhasználói útmutatója {#user-guide}

Az Accessible IPTV Client élő televíziós és rádiós műsorokat, valamint igény szerinti videókat játszik le IPTV-szolgáltatóktól. Billentyűzetről és képernyőolvasóval - például NVDA, JAWS, Narrátor vagy Orca használatával - kényelmesen kezelhető, és a nagyon nagy lejátszási listákkal és műsorújságokkal is megbirkózik.

Ez az útmutató a program minden részét bemutatja. Nyomja meg az F1-et a program bármely pontján, és az útmutató ott nyílik meg, ahol éppen tart.

## Az útmutató használata {#using-help}

Az útmutató ablaka négy részből áll, Tab-sorrendben:

- Témakörök: a szakaszok listája. A nyílbillentyűkkel való mozgás a szöveget is az adott szakaszra görgeti. Az Enter egyenesen a szövegbe lép.
- Az útmutató szövege: a teljes útmutató egyetlen, csak olvasható dokumentumként. Olvassa nyilakkal vagy a képernyőolvasó folyamatos olvasásával, a szöveg jelölése és másolása a szokásos módon működik.
- Keresés: írjon be egy szót, és az Enter a következő előfordulásához ugrik.
- Bezárás.

Billentyűk az útmutató ablakában:

- Ctrl+F: a Keresés mezőre ugrik.
- F3: a következő találat. Shift+F3: az előző találat.
- F1: visszatér ide, erre a szakaszra.
- Escape: bezárja az útmutatót, és visszatér oda, ahonnan indította.

Az F1 környezetérzékeny. Menüpontra, párbeszédablakban, a beépített lejátszóban vagy a főablak egy elemén lenyomva az útmutató az éppen használt dolog szakaszán nyílik meg. Ahol még nincs külön szakasz, az útmutató az elején nyílik meg. A Súgó > Felhasználói útmutató mindig az elejét nyitja meg.

Az útmutató a program része, ezért internetkapcsolat nélkül is működik. A program felületi nyelvén jelenik meg, ha létezik fordítás, egyébként angolul.

## Első lépések {#getting-started}

1. Nyissa meg a Fájl > Lejátszási lista kezelése (Ctrl+M) ablakot, és adja hozzá a szolgáltatóját: egy M3U lejátszási lista fájlt vagy címét, egy Xtream Codes-fiókot, vagy egy Stalker Portal-fiókot. Válassza az OK-t. A csatornák a háttérben töltődnek be.
2. Ha a szolgáltató ad műsorújság (EPG) címet, vegye fel a Fájl > Műsorújság kezelése (Ctrl+E) ablakban. Az Xtream Codes-fiókok ezt megtehetik helyette.
3. Importálja az újságot a Fájl > Műsorújság importálása az adatbázisba (Ctrl+I) paranccsal. Ez a háttérben fut, és elkészültekor szól.
4. Válasszon egy kategóriát, válasszon csatornát, és nyomja meg az Entert a lejátszáshoz.

A lejátszási listák, az újságforrások és a beállítások a munkamenetek között megmaradnak, ezért ezt csak egyszer kell elvégeznie.

## A főablak {#main-window}

A főablakban böngészhet a csatornák között, és ott indul a lejátszás. A Tab a vezérlők között ebben a sorrendben lépked, a Shift+Tab visszafelé:

1. Lejátszási lista nézete: melyik lejátszási listát böngéssze.
2. Kategóriák: a csatornacsoportok.
3. Keresés: szűri a csatornalistát.
4. Csatornák: a kiválasztott kategória csatornái, illetve a találatok.
5. Epizódleírás: mi megy éppen a kijelölt csatornán.
6. Adás-URL: a kijelölt csatorna címe, csak akkor látszik, ha a Beállítások > Adás-URL megjelenítése be van kapcsolva.

Az utolsó vezérlő után a Tab visszaugrik az elsőre.

Linuxon az útmutatóban említett menük az ablak tetején lévő Menü gomb alatt vannak.

### Lejátszási lista nézete {#playlist-view}

Ha több lejátszási listája is van, a Lejátszási lista nézete lista választja meg, hogy a kategóriák és a csatornák mit mutassanak: az összes lejátszási listát, vagy csak az egyiket. A választás megmarad.

### Kategóriák {#categories}

A kategórialista a lejátszási listák csatornacsoportjait tartalmazza. Az első sorai: Összes csatorna, majd - ha már vett fel csatornákat - Kedvencek. Minden sor megadja, hány csatornát tartalmaz.

- A Fel és Le nyilak a kategóriák között mozognak anélkül, hogy megváltoztatnák a csatornalistát, így előbb végighallgathatja őket.
- Az Enter megnyitja a kijelölt kategóriát, és a csatornalistára lép.
- A Tab megnyitja a kijelölt kategóriát, és a Keresés mezőre lép.
- A Bal és Jobb nyilak összecsukják, illetve kibontják az alcsoportos kategóriákat.

### Keresés {#search}

A Keresés mezőbe írt szöveg szűri a csatornalistát; az Enter vagy a Tab alkalmazza a szűrőt, és továbblép. Az Összes csatorna kategóriában a keresés a műsorújságra is kiterjed, így egy műsor címére keresve kilistázhatja azokat a csatornákat, amelyeken éppen megy. A mező kiürítése és az Enter megnyomása után ismét a teljes kategória látszik.

### A csatornalista {#channel-list}

A csatornalista a kiválasztott kategória vagy keresés csatornáit mutatja.

- Az Enter lejátssza a kijelölt csatornát.
- Az alkalmazásgomb, a Shift+F10 vagy a jobb egérgomb megnyitja a csatorna menüjét: Lejátszás, Hozzáadás a kedvencekhez vagy Eltávolítás a kedvencekből, Rögzítés vagy Rögzítés leállítása, Felvétel ütemezése, Műsorújság megtekintése…, valamint Műsorarchívum azoknál a csatornáknál, amelyeknek van archívuma.
- A Ctrl+D hozzáadja a csatornát a kedvencekhez, illetve kiveszi onnan. A Kedvencek kategóriában a Delete vesz ki belőle.
- A Ctrl+Shift+R elkezdi rögzíteni a csatornát, ismételt megnyomása leállítja.

A kedvenc csatornák neve után „(kedvenc)” áll, és minden sor feltünteti az éppen adásban lévő műsort is, ha az újság tartalmazza. Ha a keresés műsorokat is talált, a sorok a műsort és azt a csatornát nevezik meg, amelyen megy.

### Epizódleírás és adás-URL {#episode-description}

A csatornalistából a Tab az Epizódleírásra lép: ez mutatja a kijelölt csatornán éppen adásban lévő műsort az időpontokkal és a leírással, valamint a következő műsort. A Shift+Tab egyenesen visszaugrik a csatornalistára. A szöveg követi a kijelölt csatornát.

Ha a Beállítások > Adás-URL megjelenítése be van kapcsolva, az Adás-URL mező egy Tab-bal később jön. A csatorna címét mutatja, ami hibajelentésnél hasznos lehet. A legtöbben kikapcsolva hagyják.

## Kedvencek {#favorites}

A kedvencek a leggyakrabban nézett csatornákat tartják egy helyen. Nyomja meg a Ctrl+D-t egy csatornán, vagy használja a menüjét, vagy a Nézet > Hozzáadás a kedvencekhez parancsot. A kedvencek a Kedvencek kategóriában jelennek meg, a kategórialista elején, a Nézet > Ugrás a kedvencekhez pedig odavisz.

Egy kedvenc eltávolításához nyomja meg ismét a Ctrl+D-t rajta, vagy nyomja meg a Delete-et a Kedvencek kategóriában.

A kedvencek szolgáltató és csatorna alapján tárolódnak, nem adáscím alapján, így a lejátszási lista frissítése után is megmaradnak. A fiókjáról semmilyen adat nem tárolódik velük.

## Igény szerinti videó {#video-on-demand}

A Nézet > Igény szerinti videó (filmek és sorozatok) a kategórialistát az élő csatornákról a szolgáltató filmjeire és sorozataira váltja. A kategóriák neve a szolgáltatói kategória előtt Movies vagy Series, vagy annak fordítása. Egy sorozat kiválasztása évad és epizód sorrendben listája az epizódjait. Film vagy epizód lejátszásához nyomja meg az Entert.

A Nézet > Élő TV és műsorarchívum visszaáll élő csatornákra. A váltáskor a keresőmező kiürül.

Az igény szerinti videó az Xtream Codes-fiókokkal működik a legjobban, mert azok szabályosan leírják a kínálatukat. Egyszerű M3U lejátszási listáknál a program a csoportnevekből és az epizódszámozásból ismeri fel a filmeket és a sorozatokat.

## Lejátszási lista kezelése {#playlist-manager}

A Fájl > Lejátszási lista kezelése (Ctrl+M) listázza a lejátszási lista forrásait. Megnyitáskor a listán van a fókusz.

- Fájl hozzáadása: M3U vagy M3U8 lejátszási lista a számítógépen.
- URL hozzáadása: egy M3U lejátszási lista internetes címe.
- Xtream Codes hozzáadása: egy Xtream Codes-fiók.
- Stalker Portal hozzáadása: egy Stalker (MAG) portálfiók.

Egy forráson az alkalmazásgomb vagy a Shift+F10 megnyitja a menüjét: URL másolása, Átnevezés (F2) és Törlés (Delete). A forrásnak adott név csak címke; a forrást nem változtatja meg.

Az OK őrzi meg a változtatásokat, a Mégse elveti őket. Az OK után a csatornák újratöltődnek.

### Xtream Codes-fiókok {#xtream-codes}

Egy Xtream Codes-fiókhoz a szerver címe, a felhasználóneve és a jelszava kell, amit a szolgáltató ad. A név a fiók saját címkéje. Hagyja bejelölve az „XMLTV-URL automatikus hozzáadása” jelölőnégyzetet, hogy a szolgáltató műsorújságja egyben a Műsorújság kezelése ablakba is kerüljön.

Az Xtream Codes-fiókok igény szerinti videót, ahol a szolgáltató kínálja, műsorarchívumot is adnak, a fiók állapota pedig a Fájl > Fiókadatok alatt érhető el.

### Stalker Portal-fiókok {#stalker-portal}

Egy Stalker Portal-fiókhoz a portál címe és a szolgáltató által regisztrált MAC-cím kell. Néhány portál felhasználónevet és jelszót is kér. A „Véletlenszerű MAC-cím generálása” új MAC-címet gyárt, ami csak akkor hasznos, ha a szolgáltató kéri, hogy válasszon egyet. Az „A szolgáltató XMLTV-forrásának automatikus beállítása” felveszi a portál műsorújságját, ha van.

## Műsorújság (EPG) {#epg}

A műsorújság, vagyis az EPG megmutatja, hogy mi megy az egyes csatornákon most és később. Az XMLTV újságfájlokból származik, amelyeket a szolgáltató vagy más forrás tesz közzé. A program ezeket egy helyi adatbázisba importálja, és ezt használja az epizódleíráshoz, a Most adásban-hoz, a Műsorújság megtekintéséhez, a műsorarchívum-listákhoz és a keresésekhez.

### Műsorújság kezelése {#epg-manager}

A Fájl > Műsorújság kezelése (Ctrl+E) listázza az újságforrásokat.

- Fájl hozzáadása: XMLTV fájl a számítógépen (.xml vagy .xml.gz).
- URL hozzáadása: egy XMLTV újság internetes címe.

Egy forráson az alkalmazásgomb vagy a Shift+F10 megnyitja a menüjét: URL másolása, Átnevezés (F2) és Törlés (Delete). Az OK őrzi meg a változtatásokat.

### Műsorújság importálása {#import-epg}

A Fájl > Műsorújság importálása az adatbázisba (Ctrl+I) letölt minden újságforrást, és betölti az újságadatbázisba. A háttérben fut, ezért közben tovább nézhet és böngészhet, és üzenet szól, ha elkészült. A nagy újságok több percet is igénybe vehetnek.

Az újság időnként magától, észrevétlenül is frissül. A csatornák az újságazonosítójuk és a nevük alapján párosulnak az újsághoz, a csatornanevekben szokásos ország- és minőségváltozatokkal együtt.

Ha egy importált újság nem jelenik meg egy csatornánál, ellenőrizze, hogy a forrás lefedi-e azt a csatornát, majd importáljon újra. Az importálás részletes naplót ír; lásd a Hibaelhárítás szakaszt.

### Most adásban {#whats-on-now}

A Fájl > Most adásban (Ctrl+W) kilistázza az összes csatorna összes, éppen adásban lévő műsorát, „műsor - csatorna” alakban.

- Betűk beírása az első, azokkal kezdődő műsorra ugrik.
- A Tab a Szűrő mezőre lép; ott írás leszűkíti a listát a találatokra.
- Az Enter vagy a Lejátszás gomb lejátssza a csatornát.
- A Felvétel ütemezése, vagy a műsor menüje felvételt ütemez rá.
- Az Escape bezárja az ablakot.

### Műsorújság megtekintése (View EPG) {#channel-epg}

A Műsorújság megtekintése…, egy csatorna menüjében, kilistázza a csatorna műsorait az éppen adásban lévőtől az újság végéig. Az éppen adásban lévő műsor áll első helyen.

- A Tab a lista és a kijelölt műsor leírása között vált.
- A műsoron az alkalmazásgomb vagy a Shift+F10 a Felvétel ütemezése lehetőséget kínálja.
- Az Escape bezárja az ablakot.

## Műsorarchívum {#catch-up}

Azok a csatornák, amelyek archívumot tartanak, lehetővé teszik a már leadott műsorok megnézését. Az ilyen csatornák menüjében szerepel a Műsorarchívum. Ez megnyitja a csatorna műsorarchívum-ablakát, amely a múltbeli műsorait sorolja fel dátummal és időponttal.

- A Fel és Le nyilak a műsorok között mozognak.
- Az Enter lejátssza a kijelölt műsort.
- Az alkalmazásgomb vagy a Shift+F10 megnyitja a menüjét: Megnyitás, a lejátszáshoz, és Letöltés, a fájlba mentéshez.
- A Tab a műsor leírására lép, és vissza.
- Az Escape bezárja az ablakot.

Ha egy műsorarchívum-műsor megnézése után bezárja a beépített lejátszót, visszatér a műsorarchívum-listára, ugyanarra a műsorra.

Akkorát lehet visszanézni, amennyit a szolgáltató archivál, jellemzően néhány napot.

### Műsorarchívum-letöltések {#catch-up-downloads}

A Letöltés a műsorarchívumból a műsort a letöltési mappájába menti (lásd a Felvételek szakaszt), a csatorna és a műsor adásba kerülésének ideje szerint elnevezve. Minden letöltésnek saját ablaka van, amely egyetlen, csak olvasható mezőben mutatja a haladást, a eltelt időt, a hátralévő időt és az eddigi méretet.

- Az Escape, vagy az ablak bezárása elrejti az ablakot; a letöltés folytatódik.
- A Nézet > Letöltések megjelenítése (Ctrl+Shift+D) visszahozza a letöltőablakokat.
- A Mégse megkérdezi, majd leállítja a letöltést. A megszakított letöltés nem folytatható.

Ha egy letöltés meghiúsul, az ablak megmondja, miért, és ha a hiba átmenetinek tűnhet, néhányszor magától megpróbálja újra. Sok szolgáltató egyszerre csak egy adásfolyamot enged, ezért ha egy letöltést elutasítanak, állítsa le a ugyanarról a fiókról szóló többi lejátszást.

## Beépített lejátszó {#built-in-player}

A beépített lejátszó a programon belül játssza le a csatornákat. Csatorna lejátszásakor nyílik meg, kivéve, ha a Beállítások > Lejátszó megjelenítése az Enter lenyomására ki van kapcsolva; akkor a lejátszás az ablak megjelenítése nélkül indul el.

Vezérlői Tab-sorrendben: Szünet vagy Lejátszás, Leállítás, Rögzítés, Átküldés, Teljes képernyő, a Hangerő csúszka és a Hangsáv kiválasztása.

Billentyűk a lejátszóban:

- Szóköz: megnyomja a fókuszban lévő gombot, tehát a Szüneten szüneteltet és folytat.
- Ctrl+P: lejátszás vagy szünet.
- Ctrl+S: leállítás.
- Ctrl+R: rögzíti, amit néz, majd leállítja azt a felvételt.
- Fel és Le nyilak: hangerő 2%-os lépésekben. Ctrl+Fel és Ctrl+Le: 5%-os lépések.
- A: következő hangsáv.
- D: a hangkimeneti eszköz kiválasztása.
- Ctrl+C: átküldés egy eszközre.
- F11: teljes képernyő be vagy ki. Az Escape kilép a teljes képernyőből.
- Ctrl+W: elrejti a lejátszó ablakát; a lejátszás folytatódik.
- Ctrl+Q: bezárja a lejátszót, és leállítja a lejátszást.

Ugyanezek a parancsok megtalálhatók a lejátszó Lejátszás menüjében is. A lejátszó élő adásfolyam megszakadása esetén magától újracsatlakozik, és megtartja a választott hangsávot.

### Hangsávok {#audio-tracks}

A csatornák több hangsávot is vihetnek, például más nyelven vagy audionarrációval. Az A gomb a következő hangsávra vált, a Lejátszás > Hangsáv menü is használható, vagy a Tab-bal elérhető Hangsáv kiválasztása, amely mindig megnevezi a szóló hangsávot.

A kézzel választott hangsáv az adott csatornához megjegyződik, és legközelebb is az szól. Az automatikus választáshoz lásd az Előnyben részesített hangsáv szakaszt.

### Hangkimeneti eszköz {#audio-output-device}

A Lejátszás > Hangkimeneti eszköz… (D) választja meg, hogy a lejátszó mely hangszórókat vagy fülhallgatót használja, például hogy a TV hangja ne zavarja a képernyőolvasóját. A „A rendszer alapértelmezett eszköze” követi a Windows alapértelmezett eszközét. A választás megmarad.

### A lejátszó vezérlése a főablakból {#player-from-main-window}

A főablak Lejátszó menüje a beépített lejátszót vezérli, anélkül, hogy odalépne:

- Beépített lejátszó megjelenítése: Ctrl+Shift+J.
- Lejátszás/szünet: Ctrl+Shift+P.
- Leállítás: Ctrl+Shift+S.
- Átküldés / kapcsolódás…: Ctrl+Shift+C.
- A Ctrl+Fel és Ctrl+Le a hangerőt változtatja.

## Médialejátszó {#media-player}

A Beállítások > Használandó médialejátszó választja meg, mi játssza a csatornáit: a beépített lejátszó, vagy egy külső lejátszó, például VLC, MPC, MPC-BE, MPV, PotPlayer, Kodi vagy SMPlayer. Az Egyéni lejátszó… tetszőleges másik programot választ fájl alapján.

A rögzítés, a műsorarchívum-letöltés és az átküldés bármely lejátszónál ugyanúgy működik. A hangsáv-funkciók és a jelen útmutatóban leírt lejátszóbillentyűk a beépített lejátszóhoz tartoznak.

## Előnyben részesített hangsáv {#preferred-audio-track}

A Beállítások > Előnyben részesített hangsáv beállítja, hogy a beépített lejátszó magától válasszon hangsávot.

- Az „Audionarrációs hangsáv előnyben részesítése, ha elérhető” mindenhol az audionarrációt választja, ahol kínálják. Felismeri a szolgáltatók több nyelven ténylegesen használt elnevezéseit, például audio description, AD, Audiodeskription és Hörfilm, valamint a műsorszolgáltatók ilyen sávokon elhelyező jelölését is.
- A szövegmező a sávok nevét vagy nyelvét kéri, a legfontosabb elől, vesszővel elválasztva, például: audio description, magyar. Ha üresen hagyja, a csatorna azon sávja szól, amellyel indul.

A lejátszóban kézzel választott sáv az adott csatornához megjegyződik, és legközelebb ezeknél a szabályoknál is elsőbbséget élvez. A bárhol utoljára választott sáv szól azokon a csatornákon, ahol még nem választott.

A felvételek ugyanezt a választást követik. Egy csak hangot tartalmazó felvétel azt az egy sávot őrzi meg, amelyet hallott volna, a videófelvétel minden sávot megtart, és azt jelöli meg alapértelmezettként.

## Felvételek {#recordings}

A program bármely csatornát rögzíthet fájlba, miközben más megy, vagy egyáltalán nem szól semmi.

- A Felvételek > Rögzítés indítása (Ctrl+Shift+R) rögzíti a kijelölt csatornát. Ismételt megnyomására leáll.
- A Rögzítés a csatorna menüjében ugyanezt teszi, a beépített lejátszó Rögzítése (Ctrl+R) pedig azt rögzíti, amit néz.
- A Felvételek > Rögzítés leállítása leállítja a kijelölt csatorna felvételét, az Összes rögzítés leállítása pedig az összeset.
- A Felvételek > Felvételek mappájának megnyitása megnyitja azt a mappát, ahová a fájlok kerülnek.
- A Felvételek > Letöltési mappa beállítása… ezt a mappát választja meg. Ide kerülnek a műsorarchívum-letöltések is.

A beépített lejátszóban nézett műsor rögzítése ugyanazt a szolgáltatói kapcsolatot használja, ezért azoknál a fiókoknál is működik, amelyek egyszerre csak egy adásfolyamot engednek.

Egy felvétel leállítása eltart egy ideig, míg a fájl befejeződik. A program bezárásakor a futó felvételek maguktól befejezik a fájljaikat.

### Rögzítési formátum {#recording-formats}

A Felvételek > Rögzítési formátum választja meg, hogyan mentődjenek a felvételek:

- Eredeti minőség (újrakódolás nélkül, MKV): az adásfolyam pontosan úgy, ahogy leadták, minden hang- és feliratsávval. Megtart mindent, amit a szolgáltató küld.
- Eredeti minőség (újrakódolás nélkül, MP4): ugyanaz a kép és hang MP4-fájlban, amelyet több eszköz lejátszik, feliratok és teletext nélkül.
- Újrakódolás x264 használatával (MKV vagy MP4): kisebb, újrakódolt fájl. Sokkal több processzoridőt igényel.
- Csak hang (MP3 V0, FLAC, WAV, AAC M4A vagy Opus): csak a hang, rádióhoz hasznos.

### Ütemezett felvételek {#scheduled-recordings}

Egy jövőbeli műsor rögzítéséhez válassza a Felvétel ütemezése lehetőséget a Műsorújság megtekintése, a Most adásban vagy a keresés találati sorain egy műsoron. Egy csatornán a Felvétel ütemezése megnyitja a műsorújságját, hogy előbb válasszon műsort.

A Felvételek > Ütemezett felvételek… kilistázza az összes ütemezett, futó és befejezett felvételt időponttal, címvel, csatornával, állapottal és formátummal.

- Egy felvételen az alkalmazásgomb vagy a Shift+F10 megnyitja a menüjét: Frissítés, Megszakítás és Törlés.
- A Törlés elveszi a kijelölt felvételt a listáról; a futót előbb leállítja, megkérdezve.
- Az Escape bezárja az ablakot.

Az ütemezett felvételek maguktól indulnak el, amíg a program fut, akkor is, ha a rendszertálcára van lekicsinyítve.

### Ütemezési ráhagyás {#schedule-padding}

A műsorok ritkán kezdenek és fejeződnek be pontosan. A Felvételek > Ütemezési ráhagyás… adja meg, hány perccel a műsor előtt induljon el az ütemezett felvétel, és hány perccel a vége után fejeződjön be. A kézi felvételekre nincs hatással.

### Leállítás a felvételek után {#shutdown-after-recordings}

A Felvételek > A számítógép leállítása a felvételek befejezése után leállítja a számítógépet, miután minden futó és ütemezett felvétel elkészült, ami késő esti felvételnél hasznos.

Sosem lép életbe, amíg valami még rögzítés alatt van vagy a sorban áll. Ha eljött az idő, egy ablak 60 másodpercen visszaszámol; a fókuszban a Leállítás megszakítása van, tehát az Enter vagy az Escape megállítja, a Leállítás most pedig nem vár. A beállítás egyszeri használat vagy megszakítás után magától kikapcsol.

## Átküldés {#casting}

Az átküldés a csatornát a hálózatán lévő televízióra vagy hangszóróra küldi: Chromecast eszközökre, DLNA és UPnP megjelenítőkre, valamint AirPlay eszközökre, például Apple TV-re és HomePodra.

A Fájl > Átküldés ide… átvizsgálja a hálózatát, és kilistázza a talált eszközöket. Válasszon eszközt, majd Kapcsolódás. Néhány AirPlay-eszköz előbb a Párosítás…-t kéri, amely a televízión látható kódot várja. Kapcsolódás után a csatorna lejátszása az eszközre küldi. Az újbóli Átküldés ide… a leválasztást végzi.

Az Átküldés gomb a beépített lejátszóban, a Lejátszó > Átküldés / kapcsolódás… (Ctrl+Shift+C) és a lejátszóban a Ctrl+C ugyanezt teszi.

Az átküldéshez a számítógépnek és az eszköznek ugyanazon a hálózaton kell lennie.

## Fiókadatok {#account-info}

A Fájl > Fiókadatok (Ctrl+Shift+A) megmutatja az Xtream Codes- és Stalker Portal-fiókok állapotát: aktív-e a fiók, mikor jár le és hány nap van hátra, próbaverzió-e, és hány kapcsolatot enged és tart nyitva. A lejátszási lista címeiben felfedezett fiókok is felkerülnek a listára.

Válasszon fiókot a listában; a részletei a alatta lévő, csak olvasható mezőben jelennek meg. A Frissítés újból megkérdezi a szolgáltatót, a Adatok másolása a vágólapra teszi a részleteket. A jelszavak soha nem látszanak.

## Beállítások {#options}

A Beállítások menü tartalmazza a program beállításait. Mindegyik a megváltoztatása után azonnal mentődik.

- Használandó médialejátszó: lásd a Médialejátszó szakaszt.
- Előnyben részesített hangsáv: lásd az Előnyben részesített hangsáv szakaszt.
- Nyelv: lásd a Nyelv szakaszt.
- Minimalizálás a rendszertálcára: lásd a Rendszertálca szakaszt.
- Lejátszó megjelenítése az Enter lenyomására: bekapcsolva a csatorna lejátszása megjeleníti a beépített lejátszó ablakát. Kikapcsolva a lejátszás elindul, és a fókusz a csatornalistában marad.
- Adás-URL megjelenítése: az Adás-URL mezőt veszi fel az epizódleírás után a főablakban.
- Frissítések automatikus keresése: lásd a Frissítések szakaszt.

### Nyelv {#language}

A Beállítások > Nyelv választja meg a program nyelvét. Az Automatikus követi a Windows vagy az asztal nyelvét, és angolt használ, ha nincs hozzá fordítás. A változás a program újraindítása után teljesedik ki.

A program angol, spanyol, arab, brazil portugál, francia, német, orosz, török, olasz, lengyel, hindi, egyszerűsített kínai, japán és magyar nyelven érhető el. A javításokat és az új nyelveket szívesen fogadjuk; lásd a Segítség kérése szakaszt.

### Rendszertálca {#system-tray}

Ha a Beállítások > Minimalizálás a rendszertálcára be van kapcsolva, a főablak bezárása vagy lekicsinyítése nem lép ki, hanem elrejti a értesítési területen, így az ütemezett felvételek futnak tovább. Aktiválja a tálcikon a visszatéréshez. A menüjében szerepel még a Visszaállítás, a Lejátszó vezérlői, valami rögzítése alatt a Rögzítés leállítása, valamint a Kilépés.

A program teljes kilépéséhez használja a Fájl > Kilépés (Ctrl+Q) parancsot.

## Frissítések {#updates}

Windows alatt a program magát is frissítheti. A Súgó > Frissítések keresése… most keres új verziót, a Beállítások > Frissítések automatikus keresése pedig időnként a háttérben.

Ha frissítés érhető el, megtudhatja, mi változott, és megkérdezik, telepítse-e. A letöltést még a telepítés előtt ellenőrzik. A frissítés alatt a program bezárul, és a végén magától újraindul, majd jelenti, hogy sikerült-e. A beállítások, a kedvencek és a felvételek megmaradnak.

Linuxon a új csomagot telepítse a régi fölé.

## Hibaelhárítás {#troubleshooting}

- A Súgó > Naplómappa megnyitása megnyitja a program naplófájljainak mappáját, benne az újságimportálás naplójával és felvételenként egy naplóval.
- A Súgó > Napló- és hibakeresési adatok másolása a vágólapra tesz egy jelentést, benne a program verziójával, a rendszerével és friss naplósoraival, hibajelentésbe illeszthetően. Ez tartalmazza az adásfolyam-címeket, amelyek a szolgáltatói belépését is rejthetik, ezért nyilvános megosztás előtt nézze át.

Gyakori problémák:

- Egy csatorna nem indul el: sok szolgáltató fiókonként egyszerre csak egy adásfolyamot enged. Állítsa le ugyanannak a fióknak a többi lejátszását, felvételét vagy letöltését, majd próbálja újra.
- Egy csatornának nincs műsorújsága: ellenőrizze, hogy valamelyik EPG-forrása lefedi-e, majd importálja újra az újságot.
- Akadozik a lejátszás: a beépített lejátszó maga hangolja a pufferét. Az iptvclient.conf fájlban az internal_player_buffer_seconds és az internal_player_max_buffer_seconds értékével türelmesebb puffert állíthat be.
- A műsorarchívum azt mondja, a műsor nem érhető el: valószínűleg régebbi, mint a szolgáltató archívuma.

## Billentyűparancsok {#keyboard-shortcuts}

Bárhol:

- F1: súgó arról, amit éppen használ.

Főablak:

- Ctrl+M: Lejátszási lista kezelése.
- Ctrl+E: Műsorújság kezelése.
- Ctrl+I: Műsorújság importálása az adatbázisba.
- Ctrl+W: Most adásban.
- Ctrl+Shift+A: Fiókadatok.
- Ctrl+D: a kijelölt csatorna felvétele a kedvencekbe, illetve kivétele onnan.
- Delete: a kijelölt csatorna kivétele a kedvencekből, a Kedvencek kategóriában.
- Ctrl+Shift+R: a kijelölt csatorna felvételének indítása vagy leállítása.
- Ctrl+Shift+D: a műsorarchívum-letöltőablakok megjelenítése.
- Ctrl+Shift+J: a beépített lejátszó megjelenítése.
- Ctrl+Shift+P: a beépített lejátszó lejátszása vagy szüneteltetése.
- Ctrl+Shift+S: a beépített lejátszó leállítása.
- Ctrl+Shift+C: átküldés vagy kapcsolódás.
- Ctrl+Fel és Ctrl+Le: a beépített lejátszó hangerője.
- Enter: a kijelölt csatorna lejátszása.
- Alkalmazásgomb vagy Shift+F10: a csatorna menüje.
- Ctrl+Q: kilépés.

Beépített lejátszó:

- Szóköz: a fókuszban lévő gomb megnyomása, például a Szüneté.
- Ctrl+P: lejátszás vagy szünet.
- Ctrl+S: leállítás.
- Ctrl+R: rögzítés.
- Fel és Le: hangerő 2%-os lépésekben; Ctrl-val 5%-os lépések.
- A: következő hangsáv.
- D: hangkimeneti eszköz.
- Ctrl+C: átküldés.
- F11: teljes képernyő; az Escape kilép belőle.
- Ctrl+W: a lejátszó elrejtése.
- Ctrl+Q: a lejátszó bezárása.

A Lejátszási lista kezelése és a Műsorújság kezelése forráslistái:

- F2: átnevezés.
- Delete: törlés.

## Segítség kérése {#support}

Kérdések, hibajelentések és kiadási hírek:

- A SerrebiProjects Telegram-csoport: https://t.me/SerrebiProjects
- Hibajelentések és javaslatok a GitHubon: https://github.com/serrebidev/Accessible-IPTV-Client/issues

A Súgó > Névjegy… megmutatja a futtatott verziót, és linkeli mindkettőt. Ha hibát jelent, a Súgó > Napló- és hibakeresési adatok másolása adja meg a szükséges részleteket.

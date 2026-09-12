<!--
Az Accessible IPTV Client felhasználói útmutatója, magyarul. Ez a fordítás
az angol referenciafájl alapján készült.

Megjegyzések a fordítóknak:
- Más nyelvű fordításhoz másolja ezt a fájlt a docs/help/<nyelvi kód>.md
  útvonalra (például hu.md néven), majd fordítsa le a szöveget. A program a
  kezelőfelület nyelvéhez tartozó útmutatót jeleníti meg; ha ilyen fájl nem
  érhető el, az angol változatot használja.
- Minden {#topic-id} azonosítót pontosan, változtatás nélkül meg kell őrizni.
  A környezetérzékeny F1-súgó ezek alapján nyitja meg a megfelelő szakaszt.
  Csak az azonosító előtti címszöveget fordítsa le.
- A még le nem fordított szakasz elhagyható. Ha a felhasználó a program
  megfelelő részén F1-et nyom, az adott témakör angol szövege jelenik meg.
- A menüpontok és gombok elnevezése egyezzen meg a lefordított kezelőfelület
  szóhasználatával, hogy a felhasználó könnyen megtalálja a leírt elemeket.
- Az összetartozó sorok tetszés szerint tördelhetők. Az üres sor új bekezdést
  kezd, a „- ” karakterekkel induló sorok pedig felsorolási pontok.
-->

# Az Accessible IPTV Client felhasználói útmutatója {#user-guide}

Az Accessible IPTV Client IPTV-szolgáltatók élő televízió- és rádióadásainak, valamint igény szerinti videótartalmainak lejátszására szolgál. Kifejezetten billentyűzetes és képernyőolvasós használatra tervezték; többek között az NVDA, a JAWS, a Narrátor és az Orca szoftverrel működik együtt, továbbá a különösen nagy lejátszási listákat és műsorújságokat is hatékonyan kezeli.

Ez az útmutató a program minden részét ismerteti. Ha bárhol megnyomja az F1 billentyűt, a súgó közvetlenül az éppen használt kezelőelemhez, párbeszédablakhoz vagy funkcióhoz tartozó szakaszt nyitja meg, amennyiben ahhoz külön témakör készült.

## Az útmutató használata {#using-help}

Az útmutató ablaka a Tab billentyűvel az alábbi négy rész között járható be:

- Témakörök: a súgó fejezeteinek és szakaszainak listája. A nyílbillentyűkkel mozogva az útmutató szövege automatikusan a kijelölt részhez ugrik. Az Enter megnyomásával közvetlenül a szöveghez léphet.
- Az útmutató szövege: a teljes súgó egyetlen, csak olvasható dokumentumban. A tartalom a nyílbillentyűkkel vagy a képernyőolvasó folyamatos felolvasási parancsával olvasható; a szöveg kijelölése és másolása a más dokumentumoknál megszokott módon működik.
- Keresés: írjon be egy szót vagy kifejezést, majd az Enter megnyomásával ugorjon annak következő előfordulására.
- Bezárás.

Az útmutató ablakában használható fontosabb billentyűparancsok:

- Ctrl+F: a Keresés mezőre lép.
- F3: a következő találatra ugrik. Shift+F3: az előző találatra lép vissza.
- F1: visszatér ehhez a súgószakaszhoz.
- Escape: bezárja az útmutatót, és visszahelyezi a fókuszt oda, ahonnan megnyitotta.

Az F1 környezetérzékenyen működik. Ha egy menüponton, párbeszédablakban, a beépített lejátszóban vagy a főablak valamely kezelőelemén nyomja meg, az útmutató az adott elemhez tartozó szakaszt nyitja meg. Ha az adott funkcióhoz még nem készült külön súgórész, az útmutató az elejétől jelenik meg. A Súgó > Felhasználói útmutató menüpont minden esetben a dokumentum elejét nyitja meg.

A súgó a program része, ezért internetkapcsolat nélkül is használható. Ha az aktuális felületi nyelvhez rendelkezésre áll fordítás, azon a nyelven jelenik meg; ellenkező esetben az angol változatot használja.

## Első lépések {#getting-started}

1. Nyissa meg a Fájl > Lejátszási lista kezelése (Ctrl+M) ablakot, majd adja hozzá a szolgáltatója által biztosított forrást: a számítógépen található M3U-lejátszási listát, internetes M3U-címet, Xtream Codes-fiókot vagy Stalker Portal-fiókot. Ezután válassza az OK lehetőséget. A csatornák betöltése a háttérben történik.
2. Ha a szolgáltató műsorújságot (EPG-t) is biztosít, annak címét vegye fel a Fájl > Műsorújság kezelése (Ctrl+E) ablakban. Xtream Codes-fiók használatakor ezt a program automatikusan is elvégezheti.
3. A Fájl > Műsorújság importálása az adatbázisba (Ctrl+I) paranccsal importálja a műsorújságot. A folyamat a háttérben fut, befejezéséről a program értesítést jelenít meg.
4. Válasszon kategóriát, jelölje ki a kívánt csatornát, majd a lejátszás megkezdéséhez nyomja meg az Enter billentyűt.

A program a lejátszási listákat, a műsorújság-forrásokat és a beállításokat a következő munkamenetekre is megőrzi, ezért ezeket rendszerint csak egyszer kell megadnia.

## A főablak {#main-window}

A főablakban böngészhet a csatornák között és indíthatja el a lejátszást. A Tab az alábbi sorrendben léptet a kezelőelemek között, a Shift+Tab pedig visszafelé halad:

1. Lejátszási lista nézete: meghatározza a böngészni kívánt listát vagy listákat.
2. Kategóriák: a csatornacsoportok listája.
3. Keresés: a csatornalista szűrésére szolgáló mező.
4. Csatornák: a kiválasztott kategória csatornái vagy a keresés eredményei.
5. Epizódleírás: a kijelölt csatornán éppen adásban lévő műsor adatai.
6. Adás-URL: a kijelölt csatorna címe. Ez a mező csak akkor jelenik meg, ha a Beállítások > Adás-URL megjelenítése beállítás engedélyezve van.

Az utolsó kezelőelem után a Tab ismét az elsőre lép.

Linuxon az ebben az útmutatóban említett menük az ablak tetején található Menü gombból érhetők el.

### Lejátszási lista nézete {#playlist-view}

Ha több lejátszási listát is beállított, a Lejátszási lista nézete mezővel szabályozhatja, mely listákból származzanak a megjelenő kategóriák és csatornák. Választhatja az Összes lejátszási lista lehetőséget, vagy kijelölhet egyetlen listát. A program megjegyzi a választását.

### Kategóriák {#categories}

A Kategóriák lista a lejátszási listákban található csatornacsoportokat tartalmazza. Első eleme az Összes csatorna, ezt pedig – amennyiben már vannak kedvencek – a Kedvencek követi. Minden sor a benne található csatornák számát is jelzi.

- A Fel és Le nyílbillentyűvel úgy járhatja be a kategóriákat, hogy közben a csatornalista nem változik meg; így először meghallgathatja a rendelkezésre álló csoportokat.
- Az Enter megnyitja a kijelölt kategóriát, majd a fókuszt a csatornalistára helyezi.
- A Tab szintén megnyitja a kiválasztott kategóriát, ezután a Keresés mezőre lép.
- A Bal és Jobb nyílbillentyű összecsukja, illetve kibontja az alcsoportokat tartalmazó kategóriákat.

### Keresés {#search}

A Keresés mezőbe írt szöveggel szűrheti a csatornalistát. A szűrés alkalmazásához és a továbblépéshez nyomja meg az Enter vagy a Tab billentyűt. Az Összes csatorna kategóriában a keresés a műsorújság adataira is kiterjed, ezért egy műsorcím megadásával azok a csatornák is megtalálhatók, amelyeken az adott műsor éppen adásban van. A teljes kategória újbóli megjelenítéséhez törölje a keresőmező tartalmát, majd nyomja meg az Entert.

### A csatornalista {#channel-list}

A csatornalista a kiválasztott kategóriához vagy a kereséshez tartozó csatornákat jeleníti meg.

- Az Enter elindítja a kijelölt csatorna lejátszását.
- Az Alkalmazásgomb, a Shift+F10 vagy a jobb egérgomb megnyitja a csatorna helyi menüjét. Innen érhető el a Lejátszás, a Hozzáadás a kedvencekhez vagy Eltávolítás a kedvencekből, a Rögzítés vagy Rögzítés leállítása, a Felvétel ütemezése, a Műsorújság megtekintése…, továbbá archívummal rendelkező csatornáknál a Műsorarchívum.
- A Ctrl+D hozzáadja a kijelölt csatornát a kedvencekhez, illetve eltávolítja onnan. A Kedvencek kategóriában ugyanez a Delete billentyűvel is elvégezhető.
- A Ctrl+Shift+R megkezdi a kijelölt csatorna rögzítését; ismételt megnyomása leállítja azt.

A kedvencként megjelölt csatornák neve mellett a „(kedvenc)” jelölés szerepel. Ha a műsorújság tartalmaz megfelelő adatot, minden sorban megjelenik az éppen adásban lévő műsor címe is. Amennyiben a keresés műsorokra is adott találatot, az eredménysor feltünteti a műsorcímet és az azt sugárzó csatornát.

### Epizódleírás és adás-URL {#episode-description}

A csatornalistából a Tab az Epizódleírás mezőre lép. Itt olvasható a kijelölt csatornán éppen adásban lévő műsor kezdési és befejezési ideje, leírása, valamint a következő műsor címe és időpontja. A Shift+Tab közvetlenül visszalép a csatornalistára. A mező tartalma mindig a kijelölt csatornát követi.

Ha a Beállítások > Adás-URL megjelenítése engedélyezve van, az Adás-URL mező az Epizódleírás után, egy további Tab megnyomásával érhető el. A csatorna internetes címét mutatja, ami például hibajelentés készítésekor lehet hasznos. A legtöbb felhasználónak nincs szüksége ennek állandó megjelenítésére.

## Kedvencek {#favorites}

A Kedvencek segítségével a leggyakrabban használt csatornákat egy helyen érheti el. Egy csatorna hozzáadásához nyomja meg a Ctrl+D billentyűkombinációt, használja a helyi menü megfelelő parancsát, vagy válassza a Nézet > Hozzáadás a kedvencekhez lehetőséget. A megjelölt csatornák a kategórialista elején található Kedvencek csoportba kerülnek; a Nézet > Ugrás a kedvencekhez paranccsal közvetlenül oda léphet.

Egy kedvenc eltávolításához nyomja meg rajta ismét a Ctrl+D billentyűkombinációt, vagy a Kedvencek kategóriában használja a Delete billentyűt.

A program a kedvenceket a szolgáltató és a csatorna alapján azonosítja, nem pedig az adás internetes címe szerint. Ennek köszönhetően egy lejátszási lista frissítése után is megmaradnak. A kedvencekhez semmilyen fiókadat nem kerül mentésre.

## Igény szerinti videó {#video-on-demand}

A Nézet > Igény szerinti videó (filmek és sorozatok) paranccsal az élő csatornák helyett a szolgáltató film- és sorozatkínálata jelenik meg. A kategórianevek a Filmek vagy Sorozatok megjelölést követően a szolgáltató által megadott kategória nevét tartalmazzák. Sorozat kiválasztásakor az epizódok évad- és epizódsorrendben jelennek meg. Film vagy epizód lejátszásához nyomja meg az Enter billentyűt.

A Nézet > Élő TV és műsorarchívum paranccsal visszatérhet az élő csatornákhoz. A nézetváltáskor a keresőmező tartalma törlődik.

Az igény szerinti videótartalmak kezelése Xtream Codes-fiókokkal működik a legjobban, mivel ezek megfelelően írják le a szolgáltató kínálatát. Egyszerű M3U-lejátszási listák esetén a program a csoportnevek és az epizódszámozás alapján ismeri fel a filmeket és a sorozatokat.

## Lejátszási lista kezelése {#playlist-manager}

A Fájl > Lejátszási lista kezelése (Ctrl+M) ablak a beállított lejátszási lista-forrásokat tartalmazza. Megnyitásakor a fókusz a források listájára kerül.

- Fájl hozzáadása: a számítógépen tárolt M3U- vagy M3U8-formátumú lejátszási lista felvétele.
- URL hozzáadása: egy internetes M3U-lejátszási lista címének megadása.
- Xtream Codes hozzáadása: fiók beállítása.
- Stalker Portal hozzáadása: MAG-portálfiók felvétele.

A listában kijelölt forráson az Alkalmazásgomb vagy a Shift+F10 megnyitja a helyi menüt, amelyből az URL másolása, az Átnevezés (F2) és a Törlés (Delete) érhető el. A forráshoz megadott név kizárólag azonosításra szolgáló címke; magát a forrást nem módosítja.

A változtatások mentéséhez válassza az OK lehetőséget, elvetésükhöz pedig a Mégse gombot. Az OK használata után a csatornák újratöltődnek.

### Xtream Codes-fiókok {#xtream-codes}

Xtream Codes-fiók beállításához a szolgáltatótól kapott kiszolgálócímre, felhasználónévre és jelszóra van szükség. A név mezőben tetszőleges elnevezést adhat a fióknak. Ha az XMLTV-URL automatikus hozzáadása jelölőnégyzet bejelölve marad, a szolgáltató műsorújság-forrását a program egyúttal felveszi a Műsorújság kezelése ablakba is.

Az Xtream Codes-fiókok ezenfelül hozzáférést biztosíthatnak igény szerinti videókhoz és – ha a szolgáltató támogatja – műsorarchívumhoz. A fiók állapota a Fájl > Fiókadatok menüpontban tekinthető meg.

### Stalker Portal-fiókok {#stalker-portal}

Stalker Portal-fiókhoz meg kell adni a portál címét, valamint a szolgáltatónál regisztrált MAC-címet. Egyes portálok felhasználónevet és jelszót is kérnek. A Véletlenszerű MAC-cím generálása lehetőség új címet hoz létre; ezt csak akkor használja, ha a szolgáltató kifejezetten arra kéri, hogy Ön válasszon MAC-címet. Az „A szolgáltató XMLTV-forrásának automatikus beállítása” lehetőség felveszi a portál műsorújság-forrását, amennyiben ilyen elérhető.

## Műsorújság (EPG) {#epg}

A műsorújság, más néven EPG, megmutatja, hogy az egyes csatornákon jelenleg mi van adásban, és milyen műsorok következnek később. Az adatok a szolgáltató vagy más forrás által közzétett XMLTV-fájlokból származnak. A program ezeket egy helyi adatbázisba importálja, majd többek között az Epizódleírásban, a Most adásban és a Műsorújság megtekintése… nézetben, továbbá a műsorarchívum listáiban és a keresések során használja fel.

### Műsorújság kezelése {#epg-manager}

A Fájl > Műsorújság kezelése (Ctrl+E) ablak a beállított műsorújság-forrásokat sorolja fel.

- Fájl hozzáadása: a számítógépen tárolt XMLTV-fájl (.xml vagy .xml.gz) felvétele.
- URL hozzáadása: internetes XMLTV-műsorújság címének megadása.

A kijelölt forráson az Alkalmazásgomb vagy a Shift+F10 megnyitja a helyi menüt, amelyből az URL másolása, az Átnevezés (F2) és a Törlés (Delete) érhető el. A módosítások megőrzéséhez válassza az OK lehetőséget.

### A műsorújság importálása {#import-epg}

A Fájl > Műsorújság importálása az adatbázisba (Ctrl+I) letölti valamennyi beállított forrás adatait, majd betölti azokat a helyi műsorújság-adatbázisba. A művelet a háttérben fut, így közben tovább nézhet műsort vagy böngészhet a programban. A befejezésről értesítés tájékoztatja. Nagy méretű műsorújságok feldolgozása több percig is tarthat.

A program időnként automatikusan, külön értesítés nélkül is frissíti a műsorújságot. A csatornákat a műsorújság-azonosító és a csatornanév alapján társítja az adatokhoz; a névegyeztetés a gyakori ország- és minőségjelölési eltéréseket is figyelembe veszi.

Ha egy importált műsorújság adatai nem jelennek meg valamely csatornánál, ellenőrizze, hogy a beállított forrás valóban tartalmazza-e az adott csatornát, majd futtassa újra az importálást. A folyamat részletes naplót készít; ezzel kapcsolatban lásd a Hibaelhárítás című részt.

### Most adásban {#whats-on-now}

A Fájl > Most adásban (Ctrl+W) ablak valamennyi csatorna jelenleg futó műsorát felsorolja „műsor – csatorna” formában.

- Betűk begépelésével az első olyan műsorra ugorhat, amelynek címe a beírt karakterekkel kezdődik.
- A Tab a Szűrő mezőre lép; itt a listát műsorcím vagy csatornanév alapján szűkítheti.
- Az Enter vagy a Lejátszás gomb elindítja az adott csatornát.
- A Felvétel ütemezése paranccsal, illetve a műsor helyi menüjéből ütemezheti az adott műsor rögzítését.
- Az Escape bezárja az ablakot.

### Csatorna műsorújsága (Műsorújság megtekintése) {#channel-epg}

A csatorna helyi menüjében található Műsorújság megtekintése… parancs az éppen adásban lévő műsortól kezdve felsorolja az adott csatorna rendelkezésre álló műsorait. A lista első eleme a jelenleg futó adás.

- A Tab a lista és a kijelölt műsor leírása között vált.
- Egy műsoron az Alkalmazásgomb vagy a Shift+F10 megnyomásával elérhető a Felvétel ütemezése parancs.
- Az Escape bezárja az ablakot.

## Műsorarchívum {#catch-up}

Az archívumot biztosító csatornákon a korábban sugárzott műsorok utólag is megtekinthetők. Ezeknél a csatornáknál a helyi menüben megjelenik a Műsorarchívum parancs. Megnyitásakor a program a korábbi műsorokat dátummal és időponttal együtt sorolja fel.

- A Fel és Le nyílbillentyűvel mozoghat a műsorok között.
- Az Enter lejátssza a kijelölt műsort.
- Az Alkalmazásgomb vagy a Shift+F10 megnyitja a helyi menüt. A Megnyitás paranccsal lejátszhatja, a Letöltés lehetőséggel pedig fájlba mentheti a kijelölt tartalmat.
- A Tab a műsorlista és a kijelölt elem leírása között vált.
- Az Escape bezárja az ablakot.

Ha egy archív műsor megtekintése után bezárja a beépített lejátszót, a program visszatér a műsorarchívum listájához, azon az elemen hagyva a kijelölést, amelyet éppen nézett.

Az, hogy az archívum milyen messzre nyúlik vissza, szolgáltatónként eltérő; rendszerint az elmúlt néhány nap műsorai érhetők el.

### Archív műsorok letöltése {#catch-up-downloads}

A Letöltés parancs az archív műsort a letöltési mappába menti; ennek beállításáról a Felvételek című részben olvashat. A fájlnév a csatorna nevét és a műsor eredeti sugárzási időpontját tartalmazza. Minden letöltéshez külön ablak tartozik, amely egyetlen, csak olvasható mezőben jelzi az előrehaladást, az eltelt és a becsült hátralévő időt, valamint az addig letöltött adatmennyiséget.

- Az Escape megnyomása vagy az ablak bezárása csak elrejti a letöltési ablakot; maga a folyamat tovább fut.
- A Nézet > Letöltések megjelenítése (Ctrl+Shift+D) paranccsal ismét előhívhatja a letöltési ablakokat.
- A Mégse gomb megerősítés után megszakítja a letöltést. A megszakított folyamat később nem folytatható.

Ha a letöltés nem sikerül, az ablak jelzi a hiba okát. Átmeneti probléma esetén a program néhányszor automatikusan újrapróbálkozik. Sok szolgáltató fiókonként egyszerre csak egy adatfolyamot engedélyez. Ha a szolgáltató megtagadja a letöltést, állítsa le az ugyanehhez a fiókhoz tartozó egyéb lejátszási és letöltési folyamatokat, majd próbálja meg újra.

## Beépített lejátszó {#built-in-player}

A beépített lejátszó a programon belül játssza le a csatornákat. Egy csatorna elindításakor megnyílik a lejátszó ablaka, kivéve, ha a Beállítások > Lejátszó megjelenítése az Enter lenyomására lehetőség ki van kapcsolva. Utóbbi esetben a lejátszás elindul, de az ablak nem jelenik meg.

A lejátszó kezelőelemei Tab-sorrendben: Szünet vagy Lejátszás, Leállítás, Rögzítés, Átküldés, Teljes képernyő, Hangerőszabályzó és Hangsáv kiválasztása.

A lejátszó fontosabb billentyűparancsai:

- Szóköz: aktiválja a fókuszban lévő gombot; ha például a Szünet gombon áll, szünetelteti, majd ismételt használatkor folytatja a lejátszást.
- Ctrl+P: lejátszás vagy szünet.
- Ctrl+S: lejátszás leállítása.
- Ctrl+R: az éppen nézett adás rögzítésének elindítása, illetve leállítása.
- Fel és Le nyílbillentyű: a hangerő módosítása 2 százalékpontos lépésekben. Ctrl+Fel és Ctrl+Le: 5 százalékpontos lépésekben változtatja a hangerőt.
- A: a következő hangsáv kiválasztása.
- D: a hangkimeneti eszköz kiválasztása.
- Ctrl+C: az adás átküldése másik eszközre.
- F11: a teljes képernyős nézet be- vagy kikapcsolása. Teljes képernyőből az Escape billentyűvel léphet ki.
- Ctrl+W: elrejti a lejátszó ablakát; a lejátszás folytatódik.
- Ctrl+Q: bezárja a lejátszót és leállítja a lejátszást.

Ugyanezek a parancsok a lejátszó Lejátszás menüjéből is elérhetők. Ha egy élő adás megszakad, a lejátszó automatikusan megkísérli az újracsatlakozást, és megtartja a korábban kiválasztott hangsávot.

### Hangsávok {#audio-tracks}

Egy csatorna több hangsávot is tartalmazhat, például különböző nyelvű hangot vagy audionarrációt. Az A billentyű a következő hangsávra vált; ugyanezt a Lejátszás > Hangsáv menüből is megteheti. A Tab billentyűvel elérhető Hangsáv kiválasztása mező mindig az aktuálisan hallható sáv nevét jelzi.

A program megjegyzi az adott csatornához kézzel kiválasztott hangsávot, és a következő lejátszáskor ismét azt állítja be. Az automatikus választási lehetőségekről az Előnyben részesített hangsáv című részben olvashat.

### Hangkimeneti eszköz {#audio-output-device}

A Lejátszás > Hangkimeneti eszköz (D) paranccsal kiválaszthatja, melyik hangszórón vagy fejhallgatón szólaljon meg a beépített lejátszó. Így például a műsor hangját a képernyőolvasótól eltérő hangkimenetre irányíthatja. Az „A rendszer alapértelmezett eszköze” beállítás a Windows aktuális hangkimenetét követi. A program megjegyzi a választását.

### A lejátszó vezérlése a főablakból {#player-from-main-window}

A főablak Lejátszó menüjéből anélkül vezérelheti a beépített lejátszót, hogy át kellene váltania annak ablakára:

- Beépített lejátszó megjelenítése: Ctrl+Shift+J.
- Lejátszás/szünet: Ctrl+Shift+P.
- Leállítás: Ctrl+Shift+S.
- Átküldés / kapcsolódás: Ctrl+Shift+C.
- Ctrl+Fel és Ctrl+Le: a hangerő módosítása.

## Médialejátszó {#media-player}

A Beállítások > Használandó médialejátszó menüpont határozza meg, melyik program játssza le a csatornákat. Választhatja a Beépített lejátszót, illetve külső programot, például VLC-t, MPC-t, MPC-BE-t, MPV-t, PotPlayert, Kodit vagy SMPlayert. Az Egyéni lejátszó… lehetőséggel más program futtatható fájlja is megadható.

A rögzítés, az archív műsorok letöltése és az átküldés a kiválasztott médialejátszótól függetlenül ugyanúgy használható. Az ebben az útmutatóban ismertetett hangsávkezelési funkciók és lejátszóbillentyűk azonban kifejezetten a beépített lejátszóra vonatkoznak.

## Előnyben részesített hangsáv {#preferred-audio-track}

A Beállítások > Előnyben részesített hangsáv menüpontban szabályozhatja, hogy a beépített lejátszó automatikusan melyik sávot használja.

- Az „Audionarrációs hangsáv előnyben részesítése, ha elérhető” beállítás minden olyan csatornán audionarrációt választ, ahol a program ilyet felismer. Több nyelven használt megnevezéseket is azonosít – például audio description, AD, Audiodeskription és Hörfilm –, továbbá figyelembe veszi a műsorszolgáltató által az ilyen hangsávhoz rendelt jelölést is.
- A szövegmezőben vesszővel elválasztva adhat meg hangsávneveket vagy nyelveket, a kívánt sorrendben, a legfontosabbal kezdve; például: audionarráció, magyar. Ha a mezőt üresen hagyja, a program megtartja azt a hangsávot, amellyel a csatorna alapértelmezés szerint elindul.

Ha a lejátszóban kézzel választ hangsávot, a program ezt az adott csatornához megjegyzi, és a következő megtekintéskor az automatikus szabályoknál magasabb prioritással veszi figyelembe. Az utoljára bármely csatornán kézzel kiválasztott hangsávot használja azoknál az adóknál, amelyekhez még nem tartozik egyedi választás.

A felvételek ugyanezeket a szabályokat követik. Hangfelvételnél csak az a sáv kerül a fájlba, amelyet lejátszáskor is hallana; videofelvételnél valamennyi hangsáv megmarad, a kiválasztott pedig alapértelmezettként lesz megjelölve.

## Felvételek {#recordings}

A program bármely csatorna adását képes fájlba rögzíteni akkor is, ha közben másik csatornát néz, vagy éppen semmilyen lejátszás nincs folyamatban.

- A Felvételek > Rögzítés indítása (Ctrl+Shift+R) a főablakban kijelölt csatorna rögzítését kezdi meg. A parancs ismételt használata leállítja a folyamatot.
- A csatorna helyi menüjének Rögzítés parancsa ugyanezt teszi. A beépített lejátszó Rögzítés parancsa (Ctrl+R) az éppen nézett adást rögzíti.
- A Felvételek > Rögzítés leállítása paranccsal befejezheti a kijelölt csatornán folyó felvételt; az Összes rögzítés leállítása valamennyi aktív folyamatot leállítja.
- A Felvételek > Felvételek mappájának megnyitása paranccsal megnyithatja a mentett fájlokat tartalmazó mappát.
- A Felvételek > Letöltési mappa beállítása… paranccsal választhatja ki ezt a mappát. Az archív műsorok letöltései szintén ide kerülnek.
- Minden rögzítés naplófájlt ír a felvételi mappán belüli logs mappába. Amikor egy rögzítés befejeződik, a program jelzi, hány figyelmeztetést és hibát tartalmaz a napló, így könnyen észrevehető, ha egy felvétel nehézségek közepette készült; a részletekért nyissa meg a naplót.

Ha a beépített lejátszóban éppen nézett csatornát kezdi rögzíteni, a lejátszás és a felvétel ugyanazt a szolgáltatói kapcsolatot használja. Emiatt a funkció olyan fiókokkal is működik, amelyek egyszerre csak egy adatfolyamot engedélyeznek.

A rögzítés leállítása néhány pillanatig tarthat, amíg a program szabályosan lezárja a fájlt. Az alkalmazás bezárásakor a folyamatban lévő rögzítések szabályosan befejezik a fájlok írását.

### Rögzítési formátumok {#recording-formats}

A Felvételek > Rögzítési formátum menüponttal választhatja ki, milyen formátumban mentse a program a felvételeket:

- Eredeti minőség (újrakódolás nélkül, MKV): a szolgáltató által küldött kép- és hangadatokat változtatás nélkül menti, valamennyi hangsávval és feliratsávval együtt.
- Eredeti minőség (újrakódolás nélkül, MP4): ugyanazt a kép- és hangtartalmat MP4-fájlba menti, amelyet több eszköz képes lejátszani; a feliratok és a teletext nem kerülnek bele.
- Újrakódolás x264 használatával (MKV vagy MP4): kisebb méretű, újrakódolt fájlt készít, ami lényegesen nagyobb processzorterheléssel jár.
- Csak hang (MP3 V0, FLAC, WAV, AAC M4A vagy Opus): kizárólag a hangot menti; különösen rádióadások rögzítésére alkalmas.

### Ütemezett felvételek {#scheduled-recordings}

Egy későbbi műsor rögzítéséhez válassza a Felvétel ütemezése parancsot a Műsorújság megtekintése, a Most adásban vagy a keresési találatok valamely műsorán. Ha ugyanezt közvetlenül egy csatorna helyi menüjéből választja, először annak műsorújsága nyílik meg, hogy kijelölhesse a kívánt műsort.

A Felvételek > Ütemezett felvételek… ablak minden ütemezett, folyamatban lévő és már befejezett felvételt felsorol, megjelenítve az időpontot, a címet, a csatornát, az állapotot és a formátumot.

- Egy felvételen az Alkalmazásgomb vagy a Shift+F10 megnyitja a helyi menüt, amelyből a Frissítés, a Mégse és a Törlés érhető el.
- A Delete eltávolítja a kijelölt elemet a listából. Ha a felvétel még folyamatban van, a program megerősítés után előbb leállítja.
- Az Escape bezárja az ablakot.

Az ütemezett felvételek automatikusan elindulnak, amennyiben a program fut; ez akkor is igaz, ha a főablak a rendszertálcára van minimalizálva. Az ablak a megnyitáskor, valamint minden rögzítés indításakor, befejezésekor vagy törlésekor magától frissül, így a Frissítés parancs ritkán szükséges.

A program megkérdezi, hogy biztosan bezárja-e, amíg van ütemezett rögzítés, mert az ütemezés csak nyitott program mellett működik. Ha ennek ellenére bezárja, az ütemezett felvétel nem indul el.

### Ütemezési ráhagyás {#schedule-padding}

A műsorok a gyakorlatban nem mindig pontosan a meghirdetett időben kezdődnek vagy fejeződnek be. A Felvételek > Ütemezési ráhagyás… beállítással megadhatja, hány perccel a műsor kezdete előtt induljon el az ütemezett felvétel, illetve a tervezett befejezés után mennyi ideig folytatódjon. A kézzel indított rögzítéseket ez a beállítás nem érinti. A archívumról letöltött felvételek is ugyanezeket a perceket használják: amikor a szolgáltató lehetővé teszi, a kért archívumablak is ennyivel bővül, és a letöltés újrapróbálkozik, ha a fájl a műsnál rövidebb lett.

### A számítógép leállítása a felvételek után {#shutdown-after-recordings}

A Felvételek menü A számítógép leállítása a felvételek befejezése után lehetőségével automatikus kikapcsolást állíthat be. Erre akkor kerül sor, amikor valamennyi folyamatban lévő és ütemezett rögzítés befejeződött. A funkció például késő éjszakára ütemezett műsor rögzítésekor lehet hasznos.

A számítógép nem áll le addig, amíg bármely felvétel folyamatban van vagy még indításra vár. Amikor minden feladat befejeződött, egy ablak 60 másodperces visszaszámlálást jelenít meg. A Leállítás megszakítása gombon van a fókusz, ezért az Enter vagy az Escape megnyomásával megszakíthatja a visszaszámlálást; a Leállítás most parancs azonnal kikapcsolja a számítógépet. A beállítás sikeres leállítás vagy megszakítás után automatikusan kikapcsol.

## Átküldés {#casting}

Az átküldés segítségével egy csatorna lejátszását a helyi hálózaton található televízióra vagy hangszóróra irányíthatja. Támogatottak többek között a Chromecast-eszközök, a DLNA- és UPnP-megjelenítők, valamint az AirPlay-kompatibilis készülékek, például az Apple TV és a HomePod.

A Fájl > Átküldés ide… parancs megkeresi a hálózaton elérhető eszközöket, majd listában jeleníti meg őket. Válassza ki a kívánt készüléket, és használja a Kapcsolódás parancsot. Egyes AirPlay-eszközöknél előbb a Párosítás… szükséges; ekkor meg kell adnia a televízión megjelenő kódot. Sikeres kapcsolódás után egy csatorna elindítása az adott eszközre küldi a lejátszást. A kapcsolat megszakításához nyissa meg ismét az Átküldés ide… menüt.

A beépített lejátszó Átküldés gombja, a Lejátszó > Átküldés / kapcsolódás… (Ctrl+Shift+C), valamint a lejátszóban használható Ctrl+C ugyanezt a műveletet indítja.

Az átküldéshez a számítógépnek és a fogadó eszköznek ugyanahhoz a helyi hálózathoz kell kapcsolódnia.

## Fiókadatok {#account-info}

A Fájl > Fiókadatok (Ctrl+Shift+A) megjeleníti az Xtream Codes- és Stalker Portal-fiókok állapotát. A részletek jelzik, hogy a fiók aktív-e, mikor jár le, hány nap van még hátra, illetve próbafiók-e. Emellett látható az engedélyezett és a jelenleg használt párhuzamos kapcsolatok száma. A program a lejátszási listák internetes címeiből felismert fiókokat is felsorolja.

Válasszon fiókot a listából; a részletes adatok az alatta található, csak olvasható mezőben jelennek meg. A Frissítés ismét lekéri az információkat a szolgáltatótól, az Adatok másolása pedig a vágólapra helyezi őket. A program soha nem jeleníti meg a jelszavakat.

## Beállítások {#options}

A Beállítások menü a program működését szabályozó lehetőségeket tartalmazza. A program minden változtatást azonnal elment.

- Használandó médialejátszó: lásd a Médialejátszó című részt.
- Előnyben részesített hangsáv: lásd az azonos című szakaszt.
- Nyelv: lásd a Nyelv című részt.
- Minimalizálás a rendszertálcára: lásd a Rendszertálca című részt.
- Lejátszó megjelenítése az Enter lenyomására: ha engedélyezve van, csatorna indításakor megjelenik a beépített lejátszó ablaka. Kikapcsolt állapotban a lejátszás elindul, miközben a fókusz a csatornalistán marad.
- Adás-URL megjelenítése: a főablakban az Epizódleírás után hozzáadja az Adás-URL mezőt.
- Frissítések automatikus keresése: lásd a Frissítések című részt.

### Nyelv {#language}

A Beállítások > Nyelv menüpontban választhatja ki a program felületi nyelvét. Az Automatikus beállítás a Windows vagy az asztali környezet nyelvét követi; ha ahhoz nem érhető el fordítás, a program angolul jelenik meg. A nyelvváltás teljes érvénybe lépéséhez újra kell indítani az alkalmazást.

A program angol, spanyol, arab, brazíliai portugál, francia, német, orosz, török, olasz, lengyel, hindi, egyszerűsített kínai, japán és magyar nyelven érhető el. A fordítások javítását és új nyelvek hozzáadását a fejlesztő örömmel fogadja; további részletekért lásd a Segítségkérés című részt.

### Rendszertálca {#system-tray}

Ha a Beállítások > Minimalizálás a rendszertálcára lehetőség engedélyezve van, a főablak bezárása vagy minimalizálása nem lépteti ki a programot, hanem az értesítési területre rejti az ablakot. Így az ütemezett felvételek a háttérben is elindulhatnak és folytatódhatnak. A rendszertálca ikonjának aktiválásával ismét megjelenítheti az ablakot. Az ikon helyi menüjéből elérhető többek között az Ablak visszaállítása, a Lejátszó vezérlőelemei, folyamatban lévő rögzítés esetén a Rögzítések leállítása, valamint a Kilépés.

A program teljes bezárásához használja a Fájl > Kilépés (Ctrl+Q) parancsot.

## Frissítések {#updates}

Windows alatt a program képes önmagát frissíteni. A Súgó > Frissítések keresése… paranccsal azonnal ellenőrizheti, hogy elérhető-e új verzió. A Beállítások > Frissítések automatikus keresése időnként a háttérben végzi el ugyanezt.

Ha új verzió érhető el, a program ismerteti a változásokat, majd engedélyt kér a telepítésre. A letöltött csomagot telepítés előtt ellenőrzi. A frissítés során az alkalmazás bezárul, a folyamat befejeztével pedig automatikusan újraindul, majd tájékoztat a telepítés eredményéről. A beállítások, a kedvencek és a felvételek megmaradnak.

Linux alatt az új csomagot a korábbi verzió fölé kell telepíteni.

## Hibaelhárítás {#troubleshooting}

- A Súgó > Naplómappa megnyitása paranccsal elérheti a program naplófájljainak mappáját. Itt található többek között a műsorújság-importálás naplója és az egyes rögzítésekhez tartozó külön naplófájl.
- A Súgó > Napló- és hibakeresési adatok másolása olyan jelentést helyez a vágólapra, amely tartalmazza a program verzióját, a rendszer alapadatait és a legutóbbi naplósorokat. Ez közvetlenül beilleszthető egy hibajelentésbe. A jelentés az adások internetes címeit is tartalmazza; ezekben a szolgáltatói bejelentkezési adatok is szerepelhetnek, ezért nyilvános megosztás előtt mindig ellenőrizze a tartalmát.

Gyakori problémák:

- A csatorna nem játszható le: sok szolgáltató fiókonként egyszerre csak egy adatfolyamot engedélyez. Állítsa le az ugyanahhoz a fiókhoz tartozó egyéb lejátszást, rögzítést vagy letöltést, majd próbálja újra.
- Egy csatornához nem jelenik meg műsorújság: ellenőrizze, hogy valamelyik beállított műsorújság-forrás tartalmazza-e az adott csatornát, majd importálja újra az adatokat.
- A lejátszás akadozik: a beépített lejátszó automatikusan szabályozza a pufferelést. Ha nagyobb puffert szeretne, az iptvclient.conf fájlban növelheti az internal_player_buffer_seconds és az internal_player_max_buffer_seconds értékét.
- A Műsorarchívum azt jelzi, hogy egy műsor nem érhető el: valószínűleg régebbi annál az időtartamnál, ameddig a szolgáltató archívuma visszamenőleg tartalmat őriz.

## Billentyűparancsok {#keyboard-shortcuts}

A program bármely részén:

- F1: az éppen használt kezelőelemhez vagy funkcióhoz tartozó súgó megnyitása.

A főablakban:

- Ctrl+M: Lejátszási lista kezelése.
- Ctrl+E: Műsorújság kezelése.
- Ctrl+I: Műsorújság importálása az adatbázisba.
- Ctrl+W: Most adásban.
- Ctrl+Shift+A: Fiókadatok.
- Ctrl+D: a kijelölt csatorna hozzáadása a kedvencekhez, illetve eltávolítása onnan.
- Delete: a kijelölt csatorna eltávolítása a kedvencekből, ha a Kedvencek kategóriában áll.
- Ctrl+Shift+R: a kijelölt csatorna rögzítésének elindítása vagy leállítása.
- Ctrl+Shift+D: a folyamatban lévő archív műsorletöltések ablakainak megjelenítése.
- Ctrl+Shift+J: a beépített lejátszó megjelenítése.
- Ctrl+Shift+P: lejátszás vagy szünet a beépített lejátszóban.
- Ctrl+Shift+S: a beépített lejátszó leállítása.
- Ctrl+Shift+C: átküldés vagy kapcsolódás.
- Ctrl+Fel és Ctrl+Le: a beépített lejátszó hangerejének módosítása.
- Enter: a kijelölt csatorna lejátszása.
- Alkalmazásgomb vagy Shift+F10: a kijelölt csatorna helyi menüjének megnyitása.
- Ctrl+Q: kilépés a programból.

A beépített lejátszóban:

- Szóköz: a fókuszban lévő gomb aktiválása, például a Szünet megnyomása.
- Ctrl+P: lejátszás vagy szünet.
- Ctrl+S: leállítás.
- Ctrl+R: rögzítés indítása vagy leállítása.
- Fel és Le nyílbillentyű: a hangerő módosítása 2 százalékpontos lépésekben; a Ctrl nyomva tartásával 5 százalékponttal változtathatja.
- A: következő hangsáv.
- D: hangkimeneti eszköz kiválasztása.
- Ctrl+C: átküldés.
- F11: teljes képernyő be- vagy kikapcsolása; az Escape visszatér az ablakos nézethez.
- Ctrl+W: a lejátszóablak elrejtése.
- Ctrl+Q: a lejátszó bezárása.

A Lejátszási lista kezelése és a Műsorújság kezelése forráslistáiban:

- F2: átnevezés.
- Delete: törlés.

## Segítségkérés {#support}

Kérdésekhez, hibajelentésekhez és a kiadásokkal kapcsolatos hírekhez az alábbi csatornákat használhatja:

- SerrebiProjects Telegram-csoport: https://t.me/SerrebiProjects
- Hibajelentések és javaslatok a GitHubon: https://github.com/serrebidev/Accessible-IPTV-Client/issues

A Súgó > Névjegy… megjeleníti az éppen használt verziót, és mindkettőhöz hivatkozást tartalmaz. Hibajelentés készítésekor a Súgó > Napló- és hibakeresési adatok másolása paranccsal a kivizsgáláshoz szükséges technikai adatokat is a vágólapra helyezheti.

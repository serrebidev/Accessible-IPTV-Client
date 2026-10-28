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

Az Accessible IPTV Client az IPTV-szolgáltatók által kínált élő televízió- és rádióadások, valamint igény szerinti videótartalmak lejátszására szolgál. Kifejezetten billentyűzettel és képernyőolvasóval történő használatra tervezték. Együttműködik többek között az NVDA, a JAWS, a Narrátor és az Orca képernyőolvasókkal; emellett a különösen nagy lejátszási listákat és műsorújságokat is hatékonyan kezeli.

Ez az útmutató a program minden részét ismerteti. Ha bárhol megnyomja az F1 billentyűt, a súgó közvetlenül az éppen használt kezelőelemhez, párbeszédablakhoz vagy funkcióhoz tartozó szakaszt nyitja meg, amennyiben ahhoz külön témakör készült.

## Az útmutató használata {#using-help}

Az útmutató ablakában a Tab billentyűvel az alábbi négy terület között lépkedhet:

- Témakörök: a súgó fejezeteinek és szakaszainak listája. A nyílbillentyűkkel mozogva az útmutató szövege automatikusan a kijelölt részhez ugrik. Az Enter megnyomásával közvetlenül a szöveghez léphet.
- Az útmutató szövege: a teljes súgó egyetlen, csak olvasható dokumentumban. A tartalom a nyílbillentyűkkel vagy a képernyőolvasó folyamatos felolvasási parancsával olvasható; a szöveg más dokumentumokhoz hasonlóan kijelölhető és másolható.
- Keresés: írjon be egy szót vagy kifejezést, majd az Enter megnyomásával ugorjon annak következő előfordulására.
- Bezárás.

Az útmutató ablakában használható fontosabb billentyűparancsok:

- Ctrl+F: a Keresés mezőre lép.
- F3: a következő találatra ugrik. Shift+F3: az előző találatra lép vissza.
- F1: visszatér ehhez a súgószakaszhoz.
- Escape: bezárja az útmutatót, majd visszaállítja a fókuszt arra az elemre, ahonnan megnyitotta.

Az F1 környezetérzékenyen működik. Ha egy menüponton, párbeszédablakban, a beépített lejátszóban vagy a főablak valamely kezelőelemén nyomja meg, az útmutató az adott elemhez tartozó szakaszt nyitja meg. Ha az adott funkcióhoz még nem készült külön súgórész, az útmutató az elején nyílik meg. A Súgó > Felhasználói útmutató menüpont minden esetben a dokumentum elejét jeleníti meg.

A súgó a program része, ezért internetkapcsolat nélkül is használható. Ha az aktuális felületi nyelvhez rendelkezésre áll fordítás, azon a nyelven jelenik meg; ellenkező esetben az angol változatot használja.

## Első lépések {#getting-started}

1. Nyissa meg a Fájl > Lejátszási lista kezelése (Ctrl+M) ablakot, majd adja hozzá a szolgáltatója által biztosított forrást: a számítógépen található M3U-lejátszási listát, internetes M3U-címet, Xtream Codes-fiókot vagy Stalker Portal-fiókot. Ezután nyomja meg az OK gombot. A csatornák betöltése a háttérben történik.
2. Ha a szolgáltató műsorújságot (EPG-t) is biztosít, annak címét vegye fel a Fájl > Műsorújság kezelése (Ctrl+E) ablakban. Xtream Codes-fiók használatakor ezt a program automatikusan is elvégezheti.
3. A Fájl > Műsorújság importálása az adatbázisba (Ctrl+I) paranccsal importálja a műsorújságot. A folyamat a háttérben fut, befejezéséről a program értesítést jelenít meg.
4. Válasszon kategóriát, jelölje ki a kívánt csatornát, majd a lejátszás megkezdéséhez nyomja meg az Enter billentyűt.

A program a munkamenetek között is megőrzi a lejátszási listákat, a műsorújság-forrásokat és a beállításokat, ezért ezeket rendszerint csak egyszer kell megadnia.

## A főablak {#main-window}

A főablakban böngészhet a csatornák között és indíthatja el a lejátszást. A Tab billentyűvel az alábbi sorrendben haladhat a kezelőelemek között, a Shift+Tab billentyűkombinációval pedig visszafelé lépkedhet:

1. Lejátszási lista nézete: meghatározza a böngészni kívánt listát vagy listákat.
2. Kategóriák: a csatornacsoportok listája.
3. Keresés: a csatornalista szűrésére szolgáló mező.
4. Csatornák: a kiválasztott kategória csatornái vagy a keresés eredményei.
5. Epizódleírás: a kijelölt csatornán éppen adásban lévő műsor adatai.
6. Adás-URL: a kijelölt csatorna címe. Ez a mező csak akkor jelenik meg, ha a Beállítások > Adás-URL megjelenítése beállítás engedélyezve van.

Az utolsó kezelőelem után a Tab ismét az elsőre lép.

Linuxon az útmutatóban említett menük az ablak tetején található Menü gomb megnyomásával nyithatók meg.

### Lejátszási lista nézete {#playlist-view}

Ha több listát is beállított, a Lejátszási lista nézete mezővel szabályozhatja, melyekből származzanak a megjelenő kategóriák és csatornák. Választhatja az Összes lejátszási lista lehetőséget, vagy kijelölhet egyetlen listát. A program megjegyzi a választását.

### Kategóriák {#categories}

A Kategóriák lista a lejátszási listák csatornacsoportjait sorolja fel. Első eleme az Összes csatorna, ezt pedig – ha már megjelölt legalább egy kedvenc csatornát – a Kedvencek követi. Minden sor a hozzá tartozó csatornák számát is jelzi.

- A Fel és Le nyílbillentyűvel a csatornalista módosítása nélkül lépkedhet a kategóriák között, így előbb végighallgathatja azok nevét.
- Az Enter megnyitja a kijelölt kategóriát, majd a fókuszt a csatornalistára helyezi.
- A Tab szintén megnyitja a kiválasztott kategóriát, ezután a Keresés mezőre lép.
- A Bal nyílbillentyű összecsukja, a Jobb nyílbillentyű pedig kibontja az alcsoportokat tartalmazó kategóriákat.

### Keresés {#search}

A Keresés mezőbe írt szöveggel szűrheti a csatornalistát. A szűrés alkalmazásához és a továbblépéshez nyomja meg az Enter vagy a Tab billentyűt. Az Összes csatorna kategóriában a keresés a műsorújság adataira is kiterjed, ezért egy műsorcím megadásával azok a csatornák is megtalálhatók, amelyeken az adott műsor éppen adásban van. A teljes kategória újbóli megjelenítéséhez törölje a keresőmező tartalmát, majd nyomja meg az Enter billentyűt.

### A csatornalista {#channel-list}

A csatornalista a kiválasztott kategória csatornáit vagy a keresés találatait jeleníti meg.

- Az Enter elindítja a kijelölt csatorna lejátszását.
- Az Alkalmazásgomb, a Shift+F10 vagy a jobb egérgomb megnyitja a csatorna helyi menüjét. Innen érhető el a Lejátszás, a Hozzáadás a kedvencekhez vagy Eltávolítás a kedvencekből, a Rögzítés vagy Rögzítés leállítása, a Felvétel ütemezése, a Műsorújság megtekintése…, továbbá archívummal rendelkező csatornáknál a Műsorarchívum.
- A Ctrl+D hozzáadja a kijelölt csatornát a kedvencekhez, illetve eltávolítja onnan. A Kedvencek kategóriában ugyanez a Delete billentyűvel is elvégezhető.
- A Ctrl+Shift+R megkezdi a kijelölt csatorna rögzítését; ismételt megnyomása leállítja azt.
- A Ctrl+G megnyomása után csatornaszámot adhat meg a kívánt adás elindításához. A Ctrl+0 az előző csatornára vált, a Ctrl+H pedig megnyitja a Legutóbb lejátszott csatornák listáját.
- A Ctrl+Shift+I a fókusz áthelyezése nélkül bemondja az aktuális csatorna nevét, a jelenlegi és a következő műsor címét, kezdési és befejezési idejét, valamint a rögzítés állapotát.

A kedvencként megjelölt csatornák neve mellett a „(kedvenc)” jelölés szerepel. Ha a műsorújság tartalmaz megfelelő adatot, minden sorban megjelenik az éppen adásban lévő műsor címe is. Ha a keresés műsorcímek között is talál egyezést, az eredménysor feltünteti a műsor címét és az azt sugárzó csatornát.

### Epizódleírás és adás-URL {#episode-description}

A csatornalistából a Tab az Epizódleírás mezőre lép. Itt olvasható a kijelölt csatornán éppen futó adás kezdési és befejezési ideje, leírása, valamint az utána következő műsor címe és időpontja. A Shift+Tab közvetlenül visszalép a csatornalistára. A mező tartalma a kijelölt csatorna változásakor automatikusan frissül.

Ha engedélyezte a Beállítások > Adás-URL megjelenítése lehetőséget, az Epizódleírás után egy további Tab megnyomásával érhető el a mező. Ez a csatorna internetes címét mutatja, amely például hibajelentés készítésekor lehet hasznos. A legtöbb felhasználónak nincs szüksége ennek állandó megjelenítésére.

## Kedvencek {#favorites}

A Kedvencek segítségével a leggyakrabban használt csatornákat egy helyen érheti el. Egy csatorna hozzáadásához nyomja meg a Ctrl+D billentyűkombinációt, használja a helyi menü megfelelő parancsát, vagy válassza a Nézet > Hozzáadás a kedvencekhez lehetőséget. A kedvencnek jelölt csatornák a kategórialista elején található Kedvencek csoportba kerülnek; a Nézet > Ugrás a kedvencekhez paranccsal közvetlenül oda léphet.

Egy kedvenc eltávolításához jelölje ki a csatornát, majd nyomja meg ismét a Ctrl+D billentyűkombinációt, vagy a Kedvencek kategóriában használja a Delete billentyűt.

A program a kedvenceket a szolgáltató és a csatorna alapján azonosítja, nem pedig az adás internetes címe szerint. Ennek köszönhetően egy lejátszási lista frissítése után is megmaradnak. A program a kedvencekhez nem ment fiókadatokat.

A Nézet > Legutóbb lejátszott csatornák menüpont a korábban hallgatott vagy nézett adók listáját nyitja meg. A Nézet > Előző csatorna (Ctrl+0) paranccsal visszatérhet ahhoz, amelyet közvetlenül a jelenlegi előtt választott.

## Igény szerinti videó {#video-on-demand}

A Nézet > Igény szerinti videó (filmek és sorozatok) paranccsal az élő csatornák helyett a szolgáltató film- és sorozatkínálata jelenik meg. A kategóriák neve a Filmek vagy Sorozatok megjelöléssel kezdődik; ezt a szolgáltató által megadott kategórianév követi. Sorozat kiválasztásakor az epizódok évad- és epizódsorrendben jelennek meg. Film vagy epizód lejátszásához nyomja meg az Enter billentyűt.

A Nézet > Élő TV és műsorarchívum paranccsal visszatérhet az élő csatornákhoz. A nézetváltáskor a keresőmező tartalma törlődik.

Az igény szerinti videók Xtream Codes-fiókkal érhetők el a legmegbízhatóbban, mivel ez a fióktípus pontos adatokat szolgáltat a szolgáltató kínálatáról. Egyszerű M3U-lejátszási listák esetén a program a csoportnevek és az epizódszámozás alapján ismeri fel a filmeket és a sorozatokat.

A beépített lejátszó megjegyzi a videótárból elindított filmek és sorozatepizódok lejátszási pozícióját. A következő megnyitáskor három lehetőség közül választhat: a Folytatás a mentett időponttól indítja el a műsort; a Lejátszás az elejétől törli a korábbi pozíciót, és újrakezdi a tartalmat; a Mégse megőrzi a mentést, és nem váltja le a jelenlegi adást. Az Escape és az ablak bezárása szintén megszakítja a műveletet. Az első 30 másodpercben, illetve a befejezés közelében nem készül folytatási pont. A program legfeljebb 200 tételt őriz meg; a használathoz a forrásnak és a beépített lejátszónak egyaránt támogatnia kell az időpontra ugrást. Külső lejátszókra és archív műsorokra ez a lehetőség nem terjed ki.

A Nézet > Folytatásra váró tartalmak… ablakban a mentett bejegyzéseket a legutóbbi megtekintéssel kezdve tekintheti át, a főablakban választott lejátszási listától függetlenül. Minden sor feltünteti a címet, a lejátszási pozíciót, az utolsó megtekintés helyi idő szerinti időpontját és az elérhetőség ellenőrzésének eredményét. Korábbi mentésnél előfordulhat, hogy a cím még nem áll rendelkezésre. A Folytatás gomb vagy az Enter ellenőrzi a kijelölt tartalmat, majd megnyitja a folytatási kérdést. Az Elérhetőség ellenőrzése ugyanazt a vizsgálatot lejátszás nélkül végzi el. A hálózati műveletek a háttérben futnak; az ablak közben bezárható. Az ellenőrzés önmagában nem nyit műsorfolyamot.

Az Elérhető állapot azt jelenti, hogy a tartalom egyértelműen azonosítható az aktuális kínálatban; a tényleges lejátszás sikerét nem garantálja. A Nem érhető el vagy nem azonosítható egyértelműen jelzés eltávolított tételre, hiányzó fiókra vagy bizonytalan egyezésre is utalhat. Hálózati hiba esetén külön üzenet jelzi, hogy az ellenőrzés nem sikerült; ez nem bizonyítja a műsor megszűnését. A program egyik esetben sem törli automatikusan a mentett pozíciót. Ha a lejátszási listák az ellenőrzés közben megváltoztak, nyissa meg újra az ablakot. Folytatáshoz válassza a beépített lejátszót, és szakítsa meg az esetleges átküldést.

A Mentett pozíció törlése gombbal vagy a Delete billentyűvel egyetlen bejegyzést távolíthat el; az Összes mentett pozíció törlése valamennyi előzményt kiüríti. Mindkét művelet megerősítést kér, és kizárólag a folytatási adatokat érinti: a szolgáltatói tartalmakat és a felvett fájlokat nem törli. Ha az érintett film éppen lejátszás alatt áll, a program nem hozza létre újra a törölt pozíciót; annak megjegyzése a tartalom következő indításakor válik ismét aktívvá.

Xtream Codes-fióknál a program a szolgáltató film- vagy epizódazonosítóját a beállított fiókhoz és a tartalom típusához kapcsolja; sorozatnál annak azonosítóját is figyelembe veszi. Így egy megváltozott lejátszási cím önmagában nem teszi elérhetetlenné az új rendszerben mentett pozíciót. Azonos cím alapján nem társít eltérő tartalmakat. A szolgáltatói azonosító lecserélése vagy újrafelhasználása, illetve a fiók eltávolítása és újbóli felvétele továbbra is befolyásolhatja az egyezést. Egyszerű M3U-listánál megbízható tartalomazonosító hiányában a program a pontos URL-címre és – ha rendelkezésre áll – a forrás azonosítójára támaszkodik; megváltozott címhez nem rendeli hozzá találomra a korábbi mentést.

A régi, kizárólag URL-alapú mentések megmaradnak. Xtream-tartalom ismételt megnyitásakor a pontos korábbi egyezés alapján átkerülhetnek az új azonosításhoz; már megváltozott cím alapján ez nem végezhető el biztonságosan. A korábban forráshoz nem kapcsolt M3U-mentést a program nem rendeli önkényesen valamelyik listához. Régi sorozatepizód esetén szükség lehet annak megnyitására az eredeti sorozatból: az alkalmazás nem tölti le minden sorozat összes epizódját pusztán a mentés megkereséséhez. A tárolt előzmények a címet, az időadatokat és a visszakereséshez szükséges korlátozott azonosítókat tartalmazzák; műsor-URL-címeket és bejelentkezési adatokat nem mentenek. A beállítások titkosított exportjába ezek az adatok is bekerülnek.

## Lejátszási lista kezelése {#playlist-manager}

A Fájl > Lejátszási lista kezelése (Ctrl+M) ablakban a beállított források jelennek meg. Megnyitásakor a fókusz ezek listájára kerül.

- Fájl hozzáadása: a számítógépen tárolt M3U- vagy M3U8-formátumú lejátszási lista felvétele.
- URL hozzáadása: egy internetes M3U-lejátszási lista címének megadása.
- Xtream Codes hozzáadása: fiók beállítása.
- Stalker Portal hozzáadása: MAG-portálfiók felvétele.

A listában kijelölt forrás helyi menüjét az Alkalmazásgombbal vagy a Shift+F10 billentyűkombinációval nyithatja meg; innen érhető el az URL másolása, az Átnevezés (F2) és a Törlés (Delete). A forráshoz megadott név kizárólag azonosításra szolgáló címke; magát a forrást nem módosítja.

A helyi menü Frissítés parancsa (F5) ismét lekéri a kijelölt lejátszási listát, majd betölti annak csatornáit; a művelet befejezéséről értesítés jelenik meg. Új forrás esetén előbb az OK gombbal mentse a beállításokat. Az alkalmazás indításkor, majd háromóránként automatikusan is elvégzi a frissítést. A parancs csak a kijelölt listákra vonatkozik, a többi forrás csatornái változatlanok maradnak. Valamennyi elem kijelöléséhez nyomja meg a Ctrl+A billentyűkombinációt.

A módosítások mentéséhez nyomja meg az OK gombot, elvetésükhöz pedig a Mégse gombot. Mentés után a csatornák újratöltődnek.

### Xtream Codes-fiókok {#xtream-codes}

Xtream Codes-fiók beállításához a szolgáltatótól kapott kiszolgálócímre, felhasználónévre és jelszóra van szükség. A név mezőben tetszőleges elnevezést adhat a fióknak. Ha bejelölve hagyja az XMLTV-URL automatikus hozzáadása jelölőnégyzetet, a program a szolgáltató műsorújság-forrását is felveszi a Műsorújság kezelése ablakba.

Az Xtream Codes-fiókok ezenfelül hozzáférést biztosíthatnak igény szerinti videókhoz és – ha a szolgáltató támogatja – műsorarchívumhoz. A fiók állapota a Fájl > Fiókadatok menüpontban tekinthető meg.

### Stalker Portal-fiókok {#stalker-portal}

Stalker Portal-fiók beállításához meg kell adni a portál címét, valamint a szolgáltatónál regisztrált MAC-címet. Egyes portálok felhasználónevet és jelszót is kérnek. A Véletlenszerű MAC-cím generálása lehetőség új címet hoz létre; ezt csak akkor használja, ha a szolgáltató kifejezetten arra kéri, hogy Ön válasszon MAC-címet. Ha bejelöli az „A szolgáltató XMLTV-forrásának automatikus beállítása” lehetőséget, a program felveszi a portál műsorújság-forrását, ha az rendelkezésre áll.

## Műsorújság (EPG) {#epg}

A műsorújság, más néven EPG, megmutatja, hogy az egyes csatornákon éppen melyik műsor van adásban, és mi következik utána. Az adatok a szolgáltató vagy más forrás által közzétett XMLTV-fájlokból származnak. A program ezeket egy helyi adatbázisba importálja, majd többek között az Epizódleírás mezőben, a Most adásban és a Műsorújság megtekintése… ablakban, továbbá a műsorarchívum listáiban és a keresések során használja fel.

### Műsorújság kezelése {#epg-manager}

A Fájl > Műsorújság kezelése (Ctrl+E) ablakban a beállított műsorújság-források jelennek meg.

- Fájl hozzáadása: a számítógépen tárolt XMLTV-fájl (.xml vagy .xml.gz) felvétele.
- URL hozzáadása: internetes XMLTV-műsorújság címének megadása.

Az alapértelmezés szerint bejelölt „Az egyes lejátszási listákban megadott műsorújság használata is” lehetőség engedélyezi a forrásokhoz tartozó adásrendek automatikus importálását. Számos lista az első sorában hivatkozik erre az adatforrásra; a program a kézzel felvett műsorújságokat is betölti, az ismétlődő tételeket azonban csak egyszer dolgozza fel.

A kijelölt forrás helyi menüjét az Alkalmazásgombbal vagy a Shift+F10 billentyűkombinációval nyithatja meg; innen érhető el az URL másolása, az Átnevezés (F2) és a Törlés (Delete). A módosítások megőrzéséhez nyomja meg az OK gombot.

### A műsorújság importálása {#import-epg}

A Fájl > Műsorújság importálása az adatbázisba (Ctrl+I) letölti valamennyi beállított forrás adatait, majd betölti őket a helyi műsorújság-adatbázisba. A művelet a háttérben fut, így közben tovább nézhet műsort vagy böngészhet a programban. A folyamat befejezéséről a program értesíti. Nagy méretű műsorújságok feldolgozása több percig is tarthat.

A program időnként automatikusan, külön értesítés nélkül is frissíti a műsorújságot. A csatornákat a műsorújság-azonosító és a csatornanév alapján társítja az adatokhoz; a névegyeztetés az ország- és minőségjelölések szokásos eltéréseit is figyelembe veszi.

Ha egy importált műsorújság adatai nem jelennek meg valamely csatornánál, ellenőrizze, hogy a beállított forrás valóban tartalmazza-e az adott csatornát, majd futtassa újra az importálást. A folyamat részletes naplót készít; ezzel kapcsolatban lásd a Hibaelhárítás című részt.

### Most adásban {#whats-on-now}

A Fájl > Most adásban (Ctrl+W) ablak az összes csatorna aktuális műsorát felsorolja „műsorcím – csatornanév” formában.

- Betűk begépelésével az első olyan műsorra ugorhat, amelynek címe a beírt karakterekkel kezdődik.
- A Tab a Szűrő mezőre lép; itt a listát műsorcím vagy csatornanév alapján szűkítheti.
- Az Enter vagy a Lejátszás gomb elindítja az adott csatornát.
- A Felvétel ütemezése paranccsal, illetve az adott műsor helyi menüjéből beállíthatja annak rögzítését.
- Az Escape bezárja az ablakot.

### Csatorna műsorújsága (Műsorújság megtekintése) {#channel-epg}

A Műsorújság megtekintése… parancs a csatorna helyi menüjében érhető el. Megnyitásakor a program a jelenleg futó műsortól kezdve a műsorújságban szereplő legkésőbbi adásig sorolja fel az adott csatorna programját. A lista első eleme az éppen adásban lévő műsor.

- A Tab a lista és a kijelölt műsor leírása között vált.
- A műsor kijelölése után az Alkalmazásgomb vagy a Shift+F10 megnyomásával érhető el a Felvétel ütemezése parancs.
- Az Escape bezárja az ablakot.

A műsor helyi menüjében az Értesítés kérése műsorkezdés előtt… paranccsal állíthatja be, hogy a program a kezdés előtt figyelmeztesse. Ez a lehetőség a csatorna műsorújságában, a Most adásban ablakban és a műsorújság keresési találatainál érhető el, ha a kiválasztott adás még nem kezdődött el. Az előzetes értesítés időtartama 0–120 perc között állítható; alapértéke 5 perc. A 0 azt jelenti, hogy a program a kezdéskor értesít. A Mégse nem hoz létre új beállítást. Ugyanahhoz a csatornához és kezdési időponthoz ismételten megadott érték a meglévő bejegyzést frissíti.

A Felvételek > Értesítések műsorkezdés előtt… ablakban áttekintheti a rögzített időpontokat, az előzetes értesítés hosszát és az egyes bejegyzések állapotát. A kijelölt, még el nem kezdődött műsornál az Értesítés kérése műsorkezdés előtt… gombbal vagy az Enter billentyűvel módosíthatja a figyelmeztetés időzítését. A Törlés gomb és a Delete billentyű egyetlen bejegyzést távolít el; az Összes értesítés törlése valamennyi tételt törli. Mindkét művelet megerősítést kér. A Frissítés gomb újra megjeleníti az aktuális adatokat. Legfeljebb 500 bejegyzés tárolható; a korábbi figyelmeztetések előzményei nem szorítják ki a még várakozó műsorokat. A törlés sem a felvételeket, sem azok ütemezését nem módosítja.

Amikor elérkezik az értesítés időpontja, egy párbeszédablak közli a műsor címét, a csatornát és a kezdés helyi idő szerinti dátumát, valamint időpontját. A Csatorna megnyitása választás csak kifejezett kérésre indítja el az adást; a Bezárás és az Escape érintetlenül hagyja a lejátszást. A program mindig az aktuális lejátszási listából próbálja egyértelműen azonosítani a csatornát, nem tárolt műsor-URL-címet nyit meg. Más párbeszédablak fölött nem jelenít meg új figyelmeztetést: arra az ablak bezárása után kerülhet sor, amennyiben a műsor még nem ért véget.

A beállított értesítések a program újraindítása után is megmaradnak, megjelenítésükhöz azonban az alkalmazásnak futnia kell. A rendszertálcán működő példány is értesít; a bezárt program nem indul el önállóan, és a funkció nem ébreszti fel az alvó számítógépet. Visszatéréskor a már elkezdődött, de még folyamatban lévő műsorról megjelenhet a figyelmeztetés; a befejeződött adásokhoz tartozó bejegyzések lejárnak. Az alkalmazás a teljes kilépés előtt figyelmeztet, ha még vannak értesítésre váró műsorok. A frissítés vagy a rendszer által kikényszerített bezárás esetén ez a kérdés elmaradhat.

Az értesítés a kiválasztott műsorújság-bejegyzés időpontjára vonatkozik; az adásrend későbbi változását nem követi automatikusan. Ilyenkor törölje a korábbi beállítást, majd adja meg ismét a friss műsorújság alapján. Ez a funkció nem ütemez felvételt, ezért rögzítéshez továbbra is a Felvétel ütemezése parancs szükséges. Az alkalmazás az értesítési adatokat külön fájlban őrzi, műsor-URL-címek és jelszavak nélkül; ez az állomány nem része a beállítások titkosított exportjának. Ha a figyelmeztetés megjelenítése után a program a lezárás állapotának mentése előtt megszakad, az újraindításkor ismét megjelenhet az üzenet.

## Műsorarchívum {#catch-up}

Az archívumot biztosító csatornákon a korábban sugárzott műsorok utólag is megtekinthetők. Az ilyen csatornák helyi menüjéből megnyitható Műsorarchívum ablak dátummal és időponttal együtt sorolja fel a korábbi műsorokat.

- A Fel és Le nyílbillentyűvel mozoghat a műsorok között.
- Az Enter lejátssza a kijelölt műsort.
- Az Alkalmazásgomb vagy a Shift+F10 megnyitja a helyi menüt. A Megnyitás paranccsal lejátszhatja a kijelölt műsort, a Letöltés lehetőséggel pedig fájlba mentheti.
- A Tab a műsorlista és a kijelölt elem leírása között vált.
- Az Escape bezárja az ablakot.

Ha egy archív műsor megtekintése után bezárja a beépített lejátszót, a program visszatér a műsorarchívum listájához, és a kijelölés az imént megtekintett műsoron marad.

Az archívum időbeli terjedelme szolgáltatónként eltér; rendszerint az elmúlt néhány nap műsorai érhetők el.

### Archív műsorok letöltése {#catch-up-downloads}

A Letöltés parancs az archív műsort a letöltési mappába menti; ennek beállításáról a Felvételek című részben olvashat. A fájlnév a csatorna nevét és a műsor eredeti sugárzási időpontját tartalmazza. Minden letöltéshez külön ablak tartozik, amely egyetlen, csak olvasható mezőben jelzi az előrehaladást, az eltelt és a becsült hátralévő időt, valamint az addig letöltött adatmennyiséget.

- Az Escape megnyomása vagy az ablak bezárása csak elrejti a letöltési ablakot; maga a folyamat tovább fut.
- A Nézet > Letöltések megjelenítése (Ctrl+Shift+D) paranccsal ismét előhívhatja a letöltési ablakokat.
- A Mégse gomb megerősítés után megszakítja a letöltést. A megszakított letöltés később nem folytatható.

Ha a letöltés nem sikerül, az ablak jelzi a hiba okát. Átmeneti probléma esetén a program néhányszor automatikusan újrapróbálkozik. Sok szolgáltató fiókonként egyszerre csak egy adatfolyamot engedélyez. Ha a szolgáltató megtagadja a letöltést, állítsa le az ugyanehhez a fiókhoz tartozó egyéb lejátszást, majd próbálja meg újra.

## Beépített lejátszó {#built-in-player}

A beépített lejátszó a programon belül játssza le a csatornákat. A lejátszó ablaka egy csatorna elindításakor nyílik meg, kivéve, ha a Beállítások > Lejátszó megjelenítése az Enter lenyomására lehetőség ki van kapcsolva. Utóbbi esetben a lejátszás elindul, de az ablak nem jelenik meg.

A lejátszó kezelőelemei Tab-sorrendben: Szünet vagy Lejátszás, Leállítás, Rögzítés, Átküldés, Teljes képernyő, Hangerőszabályzó és Hangsáv kiválasztása.

A lejátszó fontosabb billentyűparancsai:

- Szóköz: aktiválja a fókuszban lévő gombot; ha például a Szünet gombon áll, szünetelteti a lejátszást, újbóli megnyomásakor pedig folytatja.
- Ctrl+P: lejátszás vagy szünet.
- Ctrl+S: lejátszás leállítása.
- Ctrl+R: az éppen nézett adás rögzítésének elindítása, illetve leállítása.
- Fel és Le nyílbillentyű: a hangerő módosítása 2 százalékpontos lépésekben. Ctrl+Fel és Ctrl+Le: 5 százalékpontos lépésekben változtatja a hangerőt.
- A: a következő hangsáv kiválasztása.
- S: váltás a feliratsávok között. A sorban a Kikapcsolva lehetőség is szerepel. Sávot a Lejátszás > Feliratok menüben választhat; külső állomány megnyitására a Feliratfájl betöltése parancs szolgál.
- Shift+S: a feliratok automatikus felolvasásának be- vagy kikapcsolása.
- C: az aktuális felirat felolvasása; ha éppen nem látható szöveg, a legutóbb megjelenített bejegyzés ismételt meghallgatása.
- Page Up és Page Down: lépkedés a már megjelent feliratok között visszafelé, illetve előre a legutóbbi bejegyzésig.
- I: az aktuális csatorna nevének, a jelenlegi és a következő műsor címének, kezdési és befejezési idejének, valamint a rögzítés állapotának bemondása.
- D: a hangkimeneti eszköz kiválasztása.
- Ctrl+C: az adás átküldése másik eszközre.
- F11: a teljes képernyős nézet be- vagy kikapcsolása. A teljes képernyős nézetből az Escape billentyűvel léphet ki.
- Ctrl+W: elrejti a lejátszóablakot; a lejátszás folytatódik.
- Ctrl+Q: bezárja a lejátszóablakot, és leállítja az adást.

Ugyanezek a parancsok a lejátszó Lejátszás menüjéből is elérhetők. Ha egy élő adás megszakad, a lejátszó automatikusan megkísérli az újracsatlakozást, és megtartja a korábban kiválasztott hangsávot.

A Lejátszás > Elalvásidőzítő… paranccsal beállíthatja, hogy a beépített lejátszás 1–1440 perc múlva leálljon. Az időzítést 0 megadásával kapcsolhatja ki. A következő ablakban a leállítást megelőző fokozatos halkítás időtartamát adhatja meg másodpercben. Alapértéke 5; 0 esetén a hangerő változatlan marad. Legfeljebb 300 másodperces halkítás állítható be, amely nem lehet hosszabb a teljes visszaszámlálásnál. A Mégse bármelyik ablakban megőrzi a korábbi időzítést.

A fokozatos halkítás kizárólag a beépített lejátszó műsorhangját érinti; a képernyőolvasó, a feliratfelolvasás és a külső lejátszók hangereje, valamint a felvételek tartalma nem változik. Ha közben módosítja a hangerőt, a program az új értéket veszi alapul. Az időzítés törlésekor és a következő lejátszás indításakor a felhasználó által választott szint áll vissza. A visszaszámlálás csatornaváltás, újracsatlakozás és a helyben tárolt adáson belüli ugrás után is folytatódik; a kézi leállítás vagy a lejátszóablak bezárása megszünteti. Lejáratakor a felvételek folytatódnak, és a számítógép bekapcsolva marad. A halkítás beállított időtartamát a program megjegyzi, az aktív visszaszámlálás azonban újraindítás után nem folytatódik.

A Lejátszás > Élő adás helyi tárolása… paranccsal ideiglenesen megőrizheti az élő műsor már beérkezett részét. A funkció kezdetben ki van kapcsolva. Engedélyezésekor 1–30 perces megőrzési idő és 64–4096 MiB közötti, adatforrásonként érvényes tárhelykorlát állítható be; az alapérték 10 perc és 512 MiB. Az időtartamnál megadott 0 kikapcsolja a helyi tárolást. Bármelyik határ elérésekor a legrégebbi részletek törlődnek. Ha folyamatban lévő felvételek miatt több adatforrás marad aktív, azok tárhelyigénye összeadódik; ehhez a fájlrendszer járulékos helyfoglalása is hozzájárul. A megőrzött előzmény az alkalmazás bezárása után nem érhető el.

A Lejátszás > Élő adás visszatekerése… paranccsal másodpercben adhatja meg, mennyivel korábbi részhez kíván visszatérni. A tényleges ugrási pontot az adás kulcsképei határozzák meg, ezért az eltérhet a kért időponttól. A Visszatérés az élő adáshoz lehetőség a legutóbb teljesen beérkezett részletre lép; ez néhány másodperccel követheti a szolgáltató élő adását. A visszatekerés nem változtatja meg a lejátszási sebességet, és nem nyit új szolgáltatói kapcsolatot. Hosszabb szüneteltetéskor a korábbi pozíció kikerülhet a megőrzött időszakból; ekkor a műsor a még elérhető legrégebbi részlettől folytatódik, amiről állapotüzenet tájékoztat.

A helyi tárolás a beépített lejátszó élő adásaihoz használható; külső lejátszókra és távoli eszközökre nem terjed ki. Hálózati kimaradás vagy lassú háttértár mellett továbbra is előfordulhat várakozás. Egyes források, például különálló hang- vagy feliratsávot használó HLS-adások nem alakíthatók át a szükséges helyi formátumra a sávok megőrzésével. Ha az indítás meghiúsul, kapcsolja ki a tárolást, majd kísérelje meg a közvetlen lejátszást.

Ebben az üzemmódban külső feliratfájl nem tölthető be, mert időzítése nem rendelhető megbízhatóan az élő adáshoz. A támogatott, adásba ágyazott feliratok a műsorral együtt haladnak. Visszatekeréskor a korábbi feliratfelolvasási munkamenet megszűnik, így az előző pozícióhoz tartozó szöveg nem kerül át az új időponthoz. A helyi tárolás önmagában nem teszi lehetővé az egyébként nem támogatott élő feliratok felismerését vagy felolvasását.

### Hangsávok {#audio-tracks}

Egy csatorna több hangsávot is tartalmazhat, például különböző nyelvű hangot vagy audionarrációt. Az A billentyű a következő hangsávra vált; ugyanezt a Lejátszás > Hangsáv menüből is megteheti. A Tab billentyűvel elérhető Hangsáv kiválasztása mező mindig az aktuálisan hallható sáv nevét jelzi.

A program megjegyzi az adott csatornához kézzel kiválasztott hangsávot, és a következő lejátszáskor ismét azt választja ki. Az automatikus választási lehetőségekről az Előnyben részesített hangsáv című részben olvashat.

### Feliratfelolvasás {#subtitle-speech}

Ha az adás tartalmaz feliratot, annak szövege a képen jelenik meg. Külső állomány megnyitására a Lejátszás > Feliratfájl betöltése parancs szolgál. A Lejátszás > Feliratok felolvasása (Shift+S) bekapcsolásával a betöltött SRT-, ASS-, SSA- vagy WebVTT-fájl bejegyzései a megjelenésük időpontjában hallhatók, a lejátszóablak elrejtése után is. Az aktuális szöveg a kezelőelemek után külön mezőben szintén megjelenik. A beépített lejátszó az adásba ágyazott feliratokat jelenleg nem olvassa fel. Az ASS/SSA-fájlok feldolgozásakor a párbeszédek szövege hangzik el; a formázási utasítások és a vektoros rajzelemek nem kerülnek felolvasásra.

A Beállítások > Feliratfelolvasás almenüben kiválaszthatja, hogy a képernyőolvasó vagy az alkalmazás saját beszédhangja szólaltassa meg a szöveget. Utóbbi kizárólag Windows rendszeren, SAPI-támogatással használható. A felolvasási sebességet a Beállítások > Feliratfelolvasás > Az alkalmazás felolvasási sebessége… paranccsal módosíthatja. A -10 és +10 közötti skálán a 0 az alapérték. A választás a műsor ütemét és a képernyőolvasó beszédét nem befolyásolja.

Az alkalmazás felolvasási hangerejét és kimeneti eszközét ugyanitt, a médialejátszó beállításaitól függetlenül módosíthatja. A kipróbáláshoz a program próbamondatot játszik le. A választást ezt követően megerősítheti; elutasítás esetén az előző beállítás marad érvényben. Vezetékes vagy Bluetooth-fejhallgatót, illetve külön hangkártyát akkor választhat, ha azt a rendszer az alkalmazás beszédhangjához elérhető kimenetként felsorolja.

Az eszköz elérhetetlenné válásakor a felolvasás alapértelmezés szerint a kapcsolat helyreállásáig szünetel. Külön engedélyezheti a rendszer alapértelmezett kimenetére történő átváltást. Ezek a beállítások az alkalmazás beszédhangjára vonatkoznak; a képernyőolvasó hangerejét és kimenetét annak saját beállításaiban módosíthatja.

A Lejátszás > Aktuális felirat felolvasása (C) paranccsal az éppen látható szöveget hallgathatja meg; ennek hiányában a legutóbbi bejegyzés hangzik el. Az Előző felirat (Page Up) és a Következő felirat (Page Down) segítségével visszatérhet a korábbi bejegyzésekhez, így ismét meghallgathatja az elmulasztott mondatokat. A lejátszás aktuális időpontját követő szövegek nem érhetők el. A parancsok az automatikus felolvasás kikapcsolt állapotában is használhatók.

A főablak Beállítások > Feliratfelolvasás almenüjéből szintén elérhető az aktuális és az előző bejegyzés meghallgatása, valamint a Friss feliratok áttekintése… ablak.

Az MPV szöveges feliratai az alkalmazás által indított és felügyelt munkamenetben olvashatók fel; az önállóan elindított példányokra ez nem vonatkozik. A képként tárolt feliratok szövegfelismerése nem támogatott. Más külső lejátszóknál a feliratok képi megjelenítése önmagában nem biztosít felolvasási lehetőséget.

Az egyes programok támogatottságát a Beállítások > Feliratfelolvasás > A feliratkezelés támogatottsága… ablakban ellenőrizheti. Az „elérhető”, „ez a lejátszó nem támogatja” és „még nincs ellenőrizve” állapotok eltérő jelentésűek; az utóbbi nem tekinthető a működés igazolásának.

### Hangkimeneti eszköz {#audio-output-device}

A Lejátszás > Hangkimeneti eszköz (D) paranccsal kiválaszthatja, melyik hangszórón vagy fejhallgatón szóljon a beépített lejátszó hangja. Így például a műsor és a képernyőolvasó hangját eltérő kimenetre irányíthatja. Az „A rendszer alapértelmezett eszköze” beállítás a Windowsban kijelölt kimenetet követi. A program megjegyzi a választását.

### A lejátszó vezérlése a főablakból {#player-from-main-window}

A főablak Lejátszó menüjéből anélkül vezérelheti a beépített lejátszót, hogy annak ablakára kellene váltania:

- Beépített lejátszó megjelenítése: Ctrl+Shift+J.
- Lejátszás/szünet: Ctrl+Shift+P.
- Leállítás: Ctrl+Shift+S.
- Átküldés / kapcsolódás: Ctrl+Shift+C.
- Ctrl+Fel és Ctrl+Le: a hangerő módosítása.

## Médialejátszó {#media-player}

A Beállítások > Használandó médialejátszó menüpont határozza meg, melyik program játssza le a csatornákat. Választhatja a Beépített lejátszót vagy egy külső programot, például VLC-t, MPC-t, MPC-BE-t, MPV-t, PotPlayert, Kodit vagy SMPlayert. Az Egyéni lejátszó… lehetőséggel más program végrehajtható fájlját is megadhatja.

A rögzítés, az archív műsorok letöltése és az átküldés a kiválasztott médialejátszótól függetlenül ugyanúgy használható. Az ebben az útmutatóban ismertetett hangsávkezelési funkciók és lejátszóbillentyűk azonban kifejezetten a beépített lejátszóra vonatkoznak.

## Előnyben részesített hangsáv {#preferred-audio-track}

A Beállítások > Előnyben részesített hangsáv menüpontban szabályozhatja, hogy a beépített lejátszó automatikusan melyik hangsávot használja.

- Az „Audionarrációs hangsáv előnyben részesítése, ha elérhető” beállítás minden olyan csatornán ezt a sávot választja, ahol a program felismeri. Több nyelven használatos megnevezést is azonosít – például audio description, AD, Audiodeskription és Hörfilm –, és a műsorszolgáltató által az audionarrációhoz rendelt jelölést is figyelembe veszi.
- A szövegmezőben vesszővel elválasztva adhat meg hangsávneveket vagy nyelveket, a kívánt sorrendben, a legfontosabbal kezdve; például: audionarráció, magyar. Ha a mezőt üresen hagyja, a program megtartja azt a hangsávot, amellyel a csatorna alapértelmezés szerint elindul.

Ha a lejátszóban kézzel választ hangsávot, a program ezt megjegyzi az adott csatornához, és a következő lejátszáskor az automatikus szabályok helyett ezt használja. Azoknál a csatornáknál, amelyekhez még nem tartozik egyedi választás, a legutóbb kézzel kiválasztott hangsávot veszi alapul.

A felvételek ugyanezeket a szabályokat követik. Hangfelvételnél csak az a sáv kerül a fájlba, amelyet lejátszáskor is hallana; videofelvételnél valamennyi hangsáv megmarad, a kiválasztott pedig alapértelmezettként lesz megjelölve.

## Felvételek {#recordings}

A program bármely csatorna adását képes fájlba rögzíteni akkor is, ha közben másik csatornát néz, vagy éppen semmilyen lejátszás nincs folyamatban.

- A Felvételek > Rögzítés indítása (Ctrl+Shift+R) a főablakban kijelölt csatorna rögzítését kezdi meg. A parancs ismételt használata leállítja a folyamatot.
- A csatorna helyi menüjében található Rögzítés parancs ugyanezt teszi. A beépített lejátszó Rögzítés parancsa (Ctrl+R) az éppen nézett adást rögzíti.
- A Felvételek > Rögzítés leállítása paranccsal befejezheti a kijelölt csatornán folyó felvételt. Az Összes rögzítés leállítása valamennyi aktív felvételt befejezi.
- A Felvételek > Felvételek mappájának megnyitása paranccsal megnyithatja a mentett fájlokat tartalmazó mappát.
- A Felvételek > Letöltési mappa beállítása… paranccsal választhatja ki ezt a mappát. Az archív műsorok letöltött fájljai is ide kerülnek.
- Minden rögzítéshez külön naplófájl készül a felvételek mappáján belül található logs könyvtárban. Ha a rögzítés figyelmeztetéssel vagy hibával fejeződik be, az értesítés összesíti a naplóban talált figyelmeztetéseket, hibákat és végzetes hibákat. A részletek a naplófájlban olvashatók. A fájl végén összefoglaló található a tervezett és a tényleges időtartamról, valamint az összes figyelmeztetésről és hibáról, típus és előfordulási időpont szerint csoportosítva.

Ha a beépített lejátszóban éppen nézett csatornát kezdi rögzíteni, a lejátszás és a rögzítés ugyanazt a szolgáltatói kapcsolatot használja. Emiatt a funkció olyan fiókokkal is működik, amelyek egyszerre csak egy adatfolyamot engedélyeznek.

A rögzítés leállítása néhány pillanatig tarthat, amíg a program szabályosan lezárja a fájlt. Az alkalmazás bezárásakor a folyamatban lévő rögzítések is leállnak; ezt megelőzően a program rövid időt hagy a fájlok véglegesítésére.

Ha az élő adás helyi tárolásának bekapcsolása után indítja el ugyanannak a forrásnak a rögzítését, a felvétel és a lejátszás közös bejövő adatfolyamot használhat. A mentés a legfrissebb elkészült részlettől kezdődik, nem a visszatekert lejátszási pozíciót követi. A lejátszó leállítása nem szünteti meg a felvételhez szükséges forrást. Amíg az utóbbi a helyi tárolóra támaszkodik, annak kikapcsolását a program megakadályozza. Egyetlen adatfolyamot engedélyező előfizetésnél másik csatorna megnyitását a folyamatban lévő rögzítés továbbra is korlátozhatja.

A Felvételek > Felvételi mappa ellenőrzése… paranccsal megvizsgálhatja a tényleges mentési hely elérhetőségét, írhatóságát és szabad kapacitását. Az ellenőrzés rövid írási próbát végez egy saját ideiglenes fájllal, amelyet utána eltávolít; a meglévő felvételeket nem módosítja és nem törli. A kézzel kért vizsgálat a háttérben fut. A megjelenő eredmény a ténylegesen ellenőrzött mappát, a szabad helyet és az indításhoz előírt alsó határt tartalmazza.

A Felvételek > Minimális szabad hely… menüpontban 0–65536 MiB közötti értéket adhat meg; alapértelmezése 256 MiB. Ha a felvétel indításakor ennél kevesebb hely áll rendelkezésre, a rögzítés nem indul el. A 0 csak ezt a mérethatárt kapcsolja ki: a mappának továbbra is írhatónak kell lennie, és a szabad kapacitást is meg kell tudni állapítani. Az előírt értékkel pontosan megegyező mennyiség elegendő az indításhoz.

Az ellenőrzés a kézzel indított és az ütemezett felvételek, valamint a rögzítőmotort használó archív műsorletöltések indításakor is megtörténik. Nem az ütemezés felvételekor mért, esetleg már elavult adatokra támaszkodik. Hiba esetén az ütemezett felvétel sikertelen állapotba kerül; a hely felszabadítása után szükség lehet az ismételt ütemezésre. Más programok és a folyamatban lévő felvételek később is fogyaszthatják a tárhelyet. A vizsgálat ezért nem garantálja a teljes műsor rögzíthetőségét, nem foglal le előre lemezterületet, és a felvétel közben nem tart fenn állandó szabadhely-tartalékot. Elegendő kapacitásról továbbra is a felhasználónak kell gondoskodnia.

### Rögzítési formátumok {#recording-formats}

A Felvételek > Rögzítési formátum menüponttal választhatja ki, milyen formátumban mentse a program a felvételeket:

- Eredeti minőség (újrakódolás nélkül, MKV): a szolgáltató által küldött kép- és hangadatokat érintetlenül menti, valamennyi hangsávval és feliratsávval együtt.
- Eredeti minőség (újrakódolás nélkül, MP4): ugyanazt a kép- és hangtartalmat MP4-fájlba menti, amelyet több eszköz képes lejátszani; a feliratok és a teletext nem kerülnek bele.
- Újrakódolás x264 használatával (MKV vagy MP4): kisebb méretű, újrakódolt fájlt készít, de a művelet lényegesen nagyobb processzorterheléssel jár.
- Csak hang (MP3 V0, FLAC, WAV, AAC M4A vagy Opus): kizárólag a hangot menti; különösen rádióadások rögzítésére alkalmas.

Kizárólag hangot tartalmazó adás felismerésekor a program hangrögzítési formátumot alkalmaz. Az Eredeti minőség (újrakódolás nélkül, MKA) lehetőséggel a kiválasztott hangsáv eredeti kódolását őrizheti meg Matroska-hangfájlban. Ez nem javítja a forrás minőségét, de elkerüli az újrakódolásból eredő veszteséget. Ha a sáv nem másolható MKA-konténerbe, a program nem végez automatikus átkódolást, hanem másik hangformátum kiválasztását kéri.

### Ütemezett felvételek {#scheduled-recordings}

Egy későbbi műsor rögzítéséhez válassza a Felvétel ütemezése parancsot a Műsorújság megtekintése vagy a Most adásban ablakban, illetve a megfelelő keresési találat helyi menüjében. Ha ugyanezt közvetlenül egy csatorna helyi menüjéből választja, először annak műsorújsága nyílik meg, hogy kijelölhesse a kívánt műsort.

A Felvételek > Ütemezett felvételek… ablak valamennyi ütemezett, folyamatban lévő és befejezett felvételt felsorolja az időponttal, a címmel, a csatornával, az állapottal és a formátummal együtt.

- A kijelölt felvételnél az Alkalmazásgomb vagy a Shift+F10 megnyitja a helyi menüt, amelyből a Frissítés, a Mégse és a Törlés érhető el.
- A műsorújságban kijelölt adás helyi menüjében a Rögzítés naponta parancs napi ismétlődést állít be. A Rögzítés hetente lehetőség hétnaponkénti ütemezést hoz létre. Az Azonos című műsorok rögzítése funkció az adott csatorna műsorújságában keresi meg a további alkalmakat, amíg a program fut.
- A listában egyszerre több felvétel is kijelölhető; a Ctrl+A az összes sort kiválasztja.
- A Delete vagy a numerikus billentyűzet Delete billentyűje megerősítés után eltávolítja a kijelölt felvételeket. Ha a kijelöltek között folyamatban lévő rögzítés is van, a program előbb leállítja az érintett felvételeket.
- Az Escape bezárja az ablakot.

Az ütemezett felvételek külön beavatkozás nélkül elindulnak, amennyiben a program fut; ez akkor is igaz, ha a főablak a rendszertálcára van minimalizálva. Az ablak tartalma megnyitáskor, valamint minden rögzítés elindulásakor, befejezésekor vagy megszakításakor automatikusan frissül, ezért a Frissítés parancsra csak ritkán van szükség.

Ha egy új felvétel időtartama részben vagy egészben egybeesik valamely korábban ütemezett rögzítésével, a program a hozzáadása előtt figyelmezteti Önt. A szolgáltató korlátozhatja az egyidejűleg használható adatfolyamok számát.

A program kilépés előtt megerősítést kér, ha van még indításra váró ütemezett felvétel, mert ezek csak az alkalmazás futása közben indulhatnak el. Ha ennek ellenére kilép, a várakozó felvételek nem indulnak el.

### Ütemezési ráhagyás {#schedule-padding}

A műsorok a gyakorlatban nem mindig pontosan a meghirdetett időben kezdődnek vagy fejeződnek be. A Felvételek > Ütemezési ráhagyás… beállítással megadhatja, hány perccel a műsor kezdete előtt induljon el az ütemezett felvétel, illetve a tervezett befejezés után mennyi ideig folytatódjon. A kézzel indított rögzítéseket ez a beállítás nem érinti. Az archív műsorok letöltésekor ugyanez a ráhagyás érvényesül: ha a szolgáltató ezt lehetővé teszi, a program a megadott percekkel kibővíti a lekért időszakot, és ismét megkísérli a letöltést, ha az elkészült fájl rövidebb a műsor várható időtartamánál.

### A számítógép leállítása a felvételek után {#shutdown-after-recordings}

A Felvételek > A számítógép leállítása a felvételek befejezése után lehetőséggel beállíthatja, hogy a számítógép valamennyi folyamatban lévő és ütemezett rögzítés befejeződése után automatikusan kikapcsoljon. A funkció például késő éjszakára ütemezett felvétel esetén lehet hasznos.

A számítógép nem áll le addig, amíg bármely felvétel folyamatban van vagy még indításra vár. Amikor minden feladat befejeződött, egy ablak 60 másodperces visszaszámlálást jelenít meg. A fókusz a Leállítás megszakítása gombra kerül, így az Enter vagy az Escape megnyomásával megszakíthatja a visszaszámlálást. A Leállítás most parancs azonnal kikapcsolja a számítógépet. A beállítás a leállítás végrehajtása vagy a visszaszámlálás megszakítása után automatikusan inaktívvá válik.

## Átküldés {#casting}

Az átküldéssel a helyi hálózaton található televízión, hangszórón vagy más lejátszóeszközön folytathatja egy csatorna lejátszását. A támogatott eszközök közé tartoznak a Chromecast- és más Google Cast-eszközök, az AirPlay-hangszórók, a DLNA- és UPnP-megjelenítők, a Sonos-hangszórók, a Roku-lejátszók, valamint a Kodi.

A Fájl > Átküldés ide… parancs megkeresi a hálózaton elérhető eszközöket, majd típusukkal együtt felsorolja őket. Jelölje ki a kívánt eszközt, és válassza a Kapcsolódás parancsot. Sikeres kapcsolódás után a csatorna lejátszása a kiválasztott készüléken folytatódik. A hangszórók – például az AirPlay- és Sonos-eszközök – csak a csatorna hangját játsszák le. A kapcsolat megszakításához válassza ismét a Fájl > Átküldés ide… parancsot.

A beépített lejátszó Átküldés gombja és Ctrl+C billentyűparancsa, valamint a Lejátszó > Átküldés / kapcsolódás… (Ctrl+Shift+C) parancs egyaránt ezt a műveletet indítja.

Az átküldéshez a számítógépnek és a fogadó eszköznek ugyanahhoz a helyi hálózathoz kell kapcsolódnia.

## Fiókadatok {#account-info}

A Fájl > Fiókadatok (Ctrl+Shift+A) megjeleníti az Xtream Codes- és Stalker Portal-fiókok állapotát. A részletekből megtudhatja, hogy a fiók aktív-e, mikor jár le, hány nap van még hátra az érvényességéből, illetve próbafiókról van-e szó. Emellett az engedélyezett és az éppen használt párhuzamos kapcsolatok száma is megjelenik. A program a lejátszási listák internetes címeiből felismert fiókokat is felsorolja.

Válasszon fiókot a listából; a részletes adatok az alatta található, csak olvasható mezőben jelennek meg. A Frissítés ismét lekéri az adatokat a szolgáltatótól, az Adatok másolása pedig a vágólapra helyezi őket. A program soha nem jeleníti meg a jelszavakat.

## Beállítások {#options}

A Beállítások menü a program működését szabályozó lehetőségeket tartalmazza. A program minden változtatást azonnal elment.

- Használandó médialejátszó: lásd a Médialejátszó című részt.
- Előnyben részesített hangsáv: lásd az azonos című szakaszt.
- Nyelv: lásd a Nyelv című részt.
- Minimalizálás a rendszertálcára: lásd a Rendszertálca című részt.
- Lejátszó megjelenítése az Enter lenyomására: ha engedélyezve van, csatorna indításakor megjelenik a beépített lejátszó ablaka. Kikapcsolt állapotban a lejátszás elindul, miközben a fókusz a csatornalistán marad.
- Adás-URL megjelenítése: engedélyezésekor a főablakban az Epizódleírás után megjelenik az Adás-URL mező.
- Frissítések automatikus keresése: lásd a Frissítések című részt.
- Automatikus bemondások: meghatározhatja a lejátszással és a csatornákkal kapcsolatos tájékoztatás részletességét. A választható szintek: Nincs, Csak hibák, Fontos események és Részletes állapotjelentés.
- Billentyűparancsok: megnyitáskor a magyar parancsnevek és a hozzájuk rendelt billentyűkombinációk között kereshet; üres keresőkifejezéssel valamennyi módosítható művelet megjelenik. A beépített lejátszó parancsait külön jelölés azonosítja. Módosíthatja az egyes műveletekhez rendelt billentyűkombinációt. A program nem fogad el ütköző hozzárendeléseket. Mentés után indítsa újra az alkalmazást.
- A Beállítások exportálása paranccsal titkosított biztonsági mentést készíthet a lejátszási listákról, a műsorújság-forrásokról, a kedvencekről és az egyéni beállításokról. Visszaállításukra a Beállítások importálása szolgál. Őrizze meg a mentés jelszavát: a szolgáltatói bejelentkezési adatok helyreállításához is szükség lesz rá.

### Nyelv {#language}

A Beállítások > Nyelv menüpontban választhatja ki a program felületi nyelvét. Az Automatikus beállítás a Windows vagy az asztali környezet nyelvét követi; ha ahhoz nem érhető el fordítás, a program angolul jelenik meg. Az új nyelv teljes körű alkalmazásához újra kell indítani a programot.

A program angol, spanyol, arab, brazíliai portugál, francia, német, orosz, török, olasz, lengyel, hindi, egyszerűsített kínai, japán és magyar nyelven érhető el. A fordítások javítását és új nyelvek hozzáadását a fejlesztő örömmel fogadja; további részletekért lásd a Segítségkérés című részt.

### Rendszertálca {#system-tray}

Ha a Beállítások > Minimalizálás a rendszertálcára lehetőség engedélyezve van, a főablak bezárásakor vagy minimalizálásakor az alkalmazás nem lép ki, hanem az értesítési területen fut tovább. Így az ütemezett felvételek a háttérben is elindulhatnak és folytatódhatnak. A rendszertálca ikonjának aktiválásával újból megjelenítheti a főablakot. Az ikon helyi menüjében többek között az Ablak visszaállítása, a Lejátszó vezérlőelemei, folyamatban lévő felvétel esetén a Rögzítések leállítása, valamint a Kilépés található. A Kilépés parancs ugyanazt a megerősítő kérdést jeleníti meg, mint az ablak bezárásakor: név szerint felsorolja az indításra váró felvételeket, egyúttal mindegyiknél feltünteti a helyi idő szerinti ütemezett kezdést. A műveletet ekkor még megszakíthatja, így elkerülheti valamelyik rögzítés elmaradását.

A program teljes bezárásához használja a Fájl > Kilépés (Ctrl+Q) parancsot.

## Frissítések {#updates}

Windows alatt a program képes önmagát frissíteni. A Súgó > Frissítések keresése… paranccsal azonnal ellenőrizheti, hogy elérhető-e új verzió. A Beállítások > Frissítések automatikus keresése beállítás engedélyezésekor a program ugyanezt időnként a háttérben is elvégzi.

Ha új verzió érhető el, a program ismerteti a változásokat, majd megkérdezi, kívánja-e telepíteni. A letöltött csomagot a telepítés megkezdése előtt ellenőrzi. A frissítés teljes folyamata alatt egyetlen ablak látható, amely minden lépésnél közli, mi történik. Letöltés közben a Mégse gombbal szakíthatja meg a műveletet. Az ablak a program bezárása és a telepítés során sem tűnik el, végül pedig értesít az új verzió elindulásáról. A beállítások, a kedvencek és a felvételek megmaradnak.

Linux alatt az új csomagot a korábbi verzió fölé kell telepíteni.

A Súgó > Újdonságok parancs verziónként, a legfrissebbel kezdve sorolja fel a változásokat. A szakaszcímek mindig a felület nyelvén olvashatók. A három legutóbbi verzió jegyzetei fordítás után magyarul jelennek meg. A fordítás esetenként csak röviddel az adott kiadás közzététele után készül el; addig, valamint a régebbi verzióknál a jegyzetek angolul olvashatók. A háromnál régebbi kiadások jegyzetei alapértelmezés szerint rejtve vannak; a „Régebbi kiadások megjelenítése (angolul)” gombbal lehet őket megjeleníteni, majd ismét elrejteni.

## Hibaelhárítás {#troubleshooting}

- A Súgó > Naplómappa megnyitása paranccsal elérheti a naplókat tartalmazó mappát. Itt található többek között a műsorújság importálásának naplója, valamint minden egyes rögzítés külön naplófájlja.
- A Súgó > Napló- és hibakeresési adatok másolása olyan jelentést helyez a vágólapra, amely tartalmazza a program verzióját, a rendszer alapadatait és a legutóbbi naplósorokat. Ez közvetlenül beilleszthető egy hibajelentésbe. A program a másoláskor kiszűri a felismerhető hozzáférési adatokat tartalmazó naplósorokat; helyüket a [***] jelölés mutatja. A helyi napló változatlan marad. A szűrés nem garantálja minden bizalmas adat felismerését, ezért nyilvános megosztás előtt mindig ellenőrizze a jelentés tartalmát.

Gyakori problémák:

- A csatorna nem játszható le: sok szolgáltató fiókonként egyszerre csak egy adatfolyamot engedélyez. Állítsa le az ugyanahhoz a fiókhoz tartozó egyéb lejátszást, rögzítést vagy letöltést, majd próbálja újra.
- Egy csatornához nem jelenik meg műsorújság: ellenőrizze, hogy valamelyik beállított műsorújság-forrás tartalmazza-e az adott csatornát, majd importálja újra az adatokat.
- A lejátszás akadozik: a beépített lejátszó automatikusan szabályozza a pufferelést. Ha nagyobb puffert szeretne, az iptvclient.conf fájlban növelheti az internal_player_buffer_seconds és az internal_player_max_buffer_seconds értékét.
- A Műsorarchívum azt jelzi, hogy egy műsor nem érhető el: a műsor valószínűleg már kívül esik a szolgáltató által megőrzött időszakon.

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
- Delete: eltávolítja a kijelölt csatornát a Kedvencek kategóriából.
- Ctrl+Shift+R: a kijelölt csatorna rögzítésének elindítása vagy leállítása.
- Ctrl+Shift+D: a folyamatban lévő archív műsorletöltések ablakainak megjelenítése.
- Ctrl+Shift+J: a beépített lejátszó megjelenítése.
- Ctrl+0: visszatérés az előző csatornához. Ctrl+H: választás a legutóbb lejátszott csatornák közül. Ctrl+G: csatornaszám megadása.
- Ctrl+Shift+I: az aktuális és a következő műsor, valamint a rögzítés állapotának bemondása.
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
- S: váltás a feliratsávok között. I: tájékoztatás az éppen játszott műsorról. Shift+S: a feliratok automatikus felolvasásának kapcsolása. C: az aktuális szöveg meghallgatása. Page Up és Page Down: lépkedés a már megjelent bejegyzések között visszafelé, illetve előre.
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

A Súgó > Névjegy… megjeleníti az éppen használt verziót, és hivatkozásokat tartalmaz mind a Telegram-csoporthoz, mind a GitHub-oldalhoz. Hibajelentés készítésekor a Súgó > Napló- és hibakeresési adatok másolása paranccsal a kivizsgáláshoz szükséges technikai adatokat is a vágólapra helyezheti.

# A korábbi funkciójavaslatok ellenőrzése és a most elkészített bővítések

Kiegészítés: a helyi tárolás és a fokozatos halkítás helyreállított bővítését a [külön leírás](local-live-buffer.hu.md) ismerteti. Az alábbi, hiányzó pufferről és halkításról szóló megállapítások az eredeti 94-es pull request állapotát rögzítik.

Ellenőrzött alap: v1.150.44, 2026. október 27.

A programban már létezik napi, heti és sorozatfelvétel; állítható az automatikus bemondások részletessége; módosíthatók a gyorsbillentyűk; kereshető a súgó, és másolható diagnosztikai jelentés. A sorozatfelvétel a műsorcím és a csatorna alapján keres, tehát az epizódismétlések biztos felismerését nem szabad neki tulajdonítani.

Az elkészített változtatások:

- Elalvásidőzítő a beépített lejátszó Lejátszás menüjében. 1 és 1440 perc közötti időtartam adható meg; 0-val kikapcsolható. A Mégse nem módosítja a korábbi beállítást. Az időzítő az adott lejátszóablakra vonatkozik, csatornaváltás után is érvényes; az ablak bezárásával megszűnik. Lejáratkor csak a beépített lejátszás áll le. A felvételek folytatódnak, a külső lejátszók működése nem változik. Fokozatos halkítás nem készült.
- Filmek és sorozatepizódok folytatási pontjának megjegyzése. A beépített lejátszó a videótárból megnyitott tételeknél felajánlja a mentett időponttól történő folytatást. Alapértelmezés szerint a Nem válasz van kijelölve. A lejátszás első 30 másodperce, valamint a befejezéshez közeli időpont nem lesz folytatási pont. Legfeljebb 200 tétel adatai maradnak meg; a könyvjelzők nem tartalmazzák a szolgáltatói címeket. A működés feltétele, hogy a forrás és a VLC lehetővé tegye a kívánt időpontra ugrást. A külső lejátszókra és az archív műsorokra ez a bővítés nem terjed ki.
- Keresés a tényleges gyorsbillentyűk és a magyar parancsnevek között. A Beállítások > Billentyűparancsok ablak megnyitásakor megadható a keresőkifejezés; üresen hagyva minden módosítható parancs megjelenik. A beépített lejátszó parancsai külön jelölést kapnak.
- A másolható diagnosztikai jelentésből a felismerhető hozzáférési adatokat tartalmazó naplósorok kiszűrése. A helyi napló változatlan marad. A jelentésben a kiszűrt sorok helyét [***] jelöli. Ez felismerési szabályokon alapuló védelem: tetszőleges, jelöletlen bizalmas szöveg teljes körű eltávolítását nem garantálja, ezért megosztás előtt továbbra is indokolt átnézni a tartalmat.

Fontos fennmaradó feladat: az élő adás visszatekerését biztosító saját helyi puffer nem készült el. Az egyszerű szüneteltetés és a szolgáltatói archívum már létezik, de egyik sem helyettesíti a korlátozott lemezhasználattal, helyes felirat-időzítéssel és közös adatkapcsolattal megvalósított visszatekerést. Ehhez külön fejlesztés és valódi lejátszási teszt szükséges.

A változtatások elkészítése nem jelent beolvasztást vagy kiadást. A natív Windows-, JAWS- és NVDA-próbát, valamint a valós szolgáltatói és telepített alkalmazással végzett ellenőrzést nem helyettesítik az automatikus tesztek. A végleges teszteredmények a pull request leírásában szerepelnek.

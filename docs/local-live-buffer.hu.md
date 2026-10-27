# Élő adás helyi tárolása és fokozatos halkítás

Ez a helyreállított fejlesztési csomag a 94-es pull request kódjára épül. Még nem kiadott programváltozat; a beépítéshez fejlesztői felülvizsgálat és valódi Windows-környezetben végzett próba szükséges. A megszakadás előtti teszteredmények helyett az új példány ellenőrzése az irányadó.

## Az élő adás megőrzése és visszatekerése

A beépített lejátszó Lejátszás menüjében az **Élő adás helyi tárolása…** paranccsal kapcsolható be a szolgáltatás. A megőrzési idő 1 és 30 perc, a tárhelykorlát pedig 64 és 4096 MiB között állítható. Alapértéke 10 perc és 512 MiB; a lehetőség kezdetben ki van kapcsolva. Az időtartamnál megadott 0 kikapcsolja a tárolást.

A program ideiglenes fájlokban őrzi a már beérkezett adást. Az időbeli vagy a méretbeli határ elérésekor a legrégebbi részleteket eltávolítja. A keret egyetlen adatforrásra vonatkozik, és a készülő részlet méretét is tartalmazza. Amennyiben felvételek miatt több forrás marad működésben, a keretek összeadódhatnak; a fájlrendszer járulékos helyigénye ezenfelül jelentkezik. A megőrzött előzmény a program bezárása után nem marad elérhető.

Az **Élő adás visszatekerése…** paranccsal másodpercben adható meg, mennyivel korábbi részhez kíván visszatérni. Az ugrás tényleges pontját az adás kulcsképei határozzák meg, ezért az nem feltétlenül egyezik meg másodpercre pontosan a kért időponttal. A **Visszatérés az élő adáshoz** parancs a legutóbb teljesen beérkezett részlethez lép, amely néhány másodperccel követheti a szolgáltatói élőképet. A visszatekerés nem lassítja le a műsort, és nem nyit új szolgáltatói adatfolyamot.

Hosszabb szüneteltetés alatt a korábbi pozíció kikerülhet a megőrzött tartományból. Ilyenkor a lejátszás a még rendelkezésre álló legrégebbi részlettől folytatódik; erről állapotüzenet tájékoztat. A helyi tárolás nem képes visszaállítani a szolgáltatótól be sem érkezett adatokat. Hálózati kimaradás, lassú háttértár vagy ritka kulcsképek mellett továbbra is előfordulhat várakozás.

Ha a rögzítés már a tárolás bekapcsolását követően indul, a felvétel és a lejátszó közös bejövő adatfolyamot használhat. A rögzítés a legfrissebb kész részlettől kezdődik, nem a néző visszatekert helyzetét követi. A lejátszás leállítása ilyenkor nem szünteti meg a felvételhez szükséges forrást. Folyamatban lévő rögzítés alatt a megosztott tárolás kikapcsolását a program megakadályozza. Egyetlen műsorfolyamot engedélyező szolgáltatónál másik csatorna megnyitását a meglévő felvétel továbbra is korlátozhatja.

A lehetőség a beépített lejátszó élő adásaira vonatkozik; külső lejátszóhoz vagy távoli eszközhöz nem biztosít általános visszatekerési támogatást. Nem minden forrás alakítható át a szükséges helyi formátumra a sávok megőrzésével. Különálló hang- vagy feliratsávot használó HLS-forrás, illetve nem támogatott kódolás esetén az indítás meghiúsulhat. Ilyenkor a tárolás kikapcsolásával a közvetlen lejátszás ismét megkísérelhető.

Az adásba ágyazott, a tárolási formátummal összeegyeztethető feliratok a műsorral együtt haladnak. Külső feliratfájl ebben az üzemmódban nem tölthető be, mert kezdőpontját nem lehet kellő bizonyossággal az élő adáshoz rendelni. Visszatekeréskor a korábbi feliratfelolvasási munkamenet megszűnik, így a régi szöveg nem maradhat az új pozícióhoz rendelve. A bővítés önmagában nem ad új élőfelirat-felismerési vagy felolvasási képességet a VLC-nek.

## Elalvásidőzítő fokozatos halkítással

A **Lejátszás > Elalvásidőzítő** paranccsal 1 és 1440 perc közötti időtartam választható; 0-val a működő időzítő törölhető. Bekapcsoláskor egy második párbeszédablakban a leállítást megelőző fokozatos halkítás hossza is megadható. Alapértéke 5 másodperc; 0 esetén nincs halkítás. Felső határa 300 másodperc, de nem haladhatja meg a teljes időzítés hosszát. A Mégse bármelyik ablakban érintetlenül hagyja a korábbi visszaszámlálást.

A halkítás kizárólag a beépített lejátszó műsorhangját érinti. Nem változtatja meg a képernyőolvasó, a feliratfelolvasás külön hangkimenete, a rendszer vagy a külső lejátszók hangerejét; a készülő felvételre sincs hatással. A hangerőszabályzó továbbra is a felhasználó által választott értéket mutatja. Ha halkítás közben módosítja ezt, az új beállítás lesz az alapérték. Törléskor, kézi leállítás után és a következő indításkor ez a kívánt szint áll vissza, nem a halkítás pillanatnyi értéke.

A visszaszámlálás csatornaváltás, automatikus újracsatlakozás és a tárolt adáson belüli ugrás után is érvényben marad. A kézi Leállítás parancs vagy a lejátszóablak bezárása megszünteti. Lejáratkor kizárólag a beépített lejátszás áll le; az időzítő nem állítja le a számítógépet. A halkítás választott időtartama megmarad, de az aktív visszaszámlálás a program újraindításakor nem folytatódik.

## Kiadás előtti ellenőrzés

Az automatikus próbák nem helyettesítik a Windows alatti VLC-lejátszást, a valós szolgáltatói teszteket, a fejhallgatóváltás kipróbálását vagy a JAWS és az NVDA segítségével végzett akadálymentességi vizsgálatot. A kiadás előtti elfogadáshoz ezeket a fejlesztőnek is ellenőriznie kell. A teljes magyar súgó későbbi véglegesítése külön feladat; ez a csomag a korábbi fordításokat nem írja át.

<!--
Podręcznik użytkownika Accessible IPTV Client, po polsku. Wzorzec angielski
znajduje się w docs/help/en.md. Uwaga dla tłumaczy: identyfikatory
{#topic ID} zostawić bez zmian; tłumaczyć tylko tekst nagłówka. Jeszcze
nietłumaczoną sekcję można po prostu pominąć; F1 otworzy wtedy sekcję
angielską.
-->

# Podręcznik użytkownika Accessible IPTV Client {#user-guide}

Accessible IPTV Client odtwarza telewizję na żywo, radio i wideo na żądanie od dostawców IPTV. Jest zbudowany dla klawiatury i czytników ekranu, takich jak NVDA, JAWS, Narrator i Orca, i radzi sobie z bardzo dużymi playlistami i programami telewizyjnymi.

Ten podręcznik opisuje każdą część programu. Naciśnij F1 w dowolnym miejscu programu, aby otworzyć go w sekcji o tym, czego właśnie używasz.

## Korzystanie z podręcznika {#using-help}

Okno podręcznika ma cztery części, w kolejności tabulacji:

- Tematy: lista sekcji. Przesuwanie się po niej strzałkami przesuwa tekst podręcznika do tej sekcji. Enter przechodzi od razu do tekstu.
- Tekst podręcznika: cały podręcznik jako jeden dokument tylko do odczytu. Czytaj go strzałkami lub poleceniem ciągłego czytania czytnika ekranu; zaznaczanie i kopiowanie tekstu działa jak w każdym dokumencie.
- Znajdź: wpisz słowo i naciśnij Enter, aby przejść do następnego miejsca, gdzie występuje.
- Zamknij.

Klawisze w oknie podręcznika:

- Ctrl+F: przejście do pola Znajdź.
- F3: znalezienie następnego trafienia. Shift+F3: znalezienie poprzedniego.
- F1: powrót do tej sekcji.
- Escape: zamknięcie podręcznika i powrót tam, gdzie byłeś.

F1 jest wrażliwe na kontekst. Naciśnięte na pozycji menu, w oknie dialogowym, we wbudowanym odtwarzaczu albo na kontrolce okna głównego otwiera podręcznik w sekcji o tym elemencie. Tam, gdzie sekcja jeszcze nie powstała, podręcznik otwiera się na początku. Pomoc > Podręcznik użytkownika zawsze otwiera go na początku.

Podręcznik jest częścią programu, więc działa bez połączenia z internetem. Jest pokazywany w języku interfejsu programu, gdy istnieje tłumaczenie, w przeciwnym razie po angielsku.

## Pierwsze kroki {#getting-started}

1. Otwórz Plik > Menedżer playlist (Ctrl+M) i dodaj swojego dostawcę: plik lub adres playlisty M3U, konto Xtream Codes albo konto Stalker Portal. Wybierz OK. Kanały ładują się w tle.
2. Jeśli dostawca daje ci adres przewodnika po programach (EPG), dodaj go w Plik > Menedżer EPG (Ctrl+E). Konta Xtream Codes mogą dodać go za ciebie.
3. Zaimportuj przewodnik poleceniem Plik > Importuj EPG do bazy danych (Ctrl+I). To działa w tle i daje znać, gdy skończy.
4. Wybierz kategorię, wybierz kanał i naciśnij Enter, aby go odtworzyć.

Playlisty, źródła przewodnika i ustawienia są zachowywane między sesjami, więc trzeba to zrobić tylko raz.

## Okno główne {#main-window}

Okno główne to miejsce, gdzie przeglądasz i odtwarzasz kanały. Tab przechodzi przez jego kontrolki w tej kolejności, a Shift+Tab wraca:

1. Widok playlisty: którą playlistę przeglądać.
2. Kategorie: grupy kanałów.
3. Szukaj: filtruje listę kanałów.
4. Kanały: kanały wybranej kategorii albo wyniki wyszukiwania.
5. Opis odcinka: co leci teraz na podświetlonym kanale.
6. Adres URL strumienia: adres podświetlonego kanału, widoczny tylko gdy Opcje > Pokaż adres URL strumienia jest włączone.

Po ostatniej kontrolce Tab wraca do pierwszej.

W Linuksie menu opisywane w tym podręczniku są pod przyciskiem Menu u góry okna.

### Widok playlisty {#playlist-view}

Gdy masz więcej niż jedną playlistę, lista Widok playlisty wybiera, co pokazują kategorie i kanały: wszystkie playlisty albo jedną. Twój wybór jest zapamiętywany.

### Kategorie {#categories}

Lista kategorii zawiera grupy kanałów z twoich playlist. Jej pierwsze wiersze to Wszystkie kanały, a po dodaniu ich - Ulubione. Każdy wiersz podaje, ile kanałów zawiera.

- Strzałki góra i dół przechodzą przez kategorie bez zmieniania listy kanałów, więc możesz ich najpierw posłuchać.
- Enter otwiera podświetloną kategorię i przechodzi do listy kanałów.
- Tab otwiera podświetloną kategorię i przechodzi do pola Szukaj.
- Strzałki lewo i prawo zwijają i rozwijają kategorię z podgrupami.

### Wyszukiwanie {#search}

Wpisz w polu Szukaj, aby filtrować listę kanałów, a potem naciśnij Enter lub Tab, aby zastosować filtr i iść dalej. Szukanie we Wszystkich kanałach zagląda też do przewodnika po programach, więc szukanie tytułu audycji może wypisać kanały, które ją pokazują. Wyczyść pole i naciśnij Enter, aby znowu zobaczyć całą kategorię.

### Lista kanałów {#channel-list}

Lista kanałów pokazuje kanały wybranej kategorii albo wyszukiwania.

- Enter odtwarza podświetlony kanał.
- Klawisz aplikacji, Shift+F10 albo klik prawym przyciskiem otwiera menu kanału: Odtwórz, Dodaj do ulubionych albo Usuń z ulubionych, Nagraj albo Zatrzymaj nagrywanie, Zaplanuj nagrywanie, Pokaż EPG..., oraz Powtórki dla kanałów, które mają archiwum.
- Ctrl+D dodaje kanał do ulubionych albo usuwa go. W kategorii Ulubione usuwa go klawisz Delete.
- Ctrl+Shift+R rozpoczyna nagrywanie kanału; naciśnięte ponownie, je zatrzymuje.

Ulubione kanały są oznaczone „(Ulubione)", a każdy wiersz podaje też audycję właśnie nadawaną, gdy przewodnik ją zna. Gdy wyszukiwanie znalazło też audycje, jego wiersze podają audycję i kanał, na którym leci.

### Opis odcinka i adres URL strumienia {#episode-description}

Tab z listy kanałów dochodzi do Opisu odcinka: audycja nadawana teraz na podświetlonym kanale, z czasami i opisem, oraz co leci dalej. Shift+Tab wraca od razu do listy kanałów. Tekst podąża za podświetlonym kanałem.

Gdy Opcje > Pokaż adres URL strumienia jest włączone, pole Adres URL strumienia przychodzi Tab później. Pokazuje adres kanału, co może pomóc przy zgłaszaniu problemu. Większość ludzi zostawia je wyłączone.

## Ulubione {#favorites}

Ulubione trzymają w jednym miejscu kanały, które oglądasz najczęściej. Naciśnij Ctrl+D na kanale, użyj jego menu albo Widok > Dodaj do ulubionych. Ulubione pojawiają się w kategorii Ulubione blisko początku listy kategorii, a Widok > Przejdź do ulubionych zaprowadzi cię tam.

Aby usunąć ulubiony kanał, naciśnij na nim ponownie Ctrl+D albo naciśnij Delete w kategorii Ulubione.

Ulubione są zapisywane według dostawcy i kanału, nie według adresu strumienia, więc przeżywają odświeżenie playlisty. Nic o twoim koncie nie jest z nimi zapisywane.

## Wideo na żądanie {#video-on-demand}

Widok > Wideo na żądanie (filmy && seriale) przełącza listę kategorii z kanałów na żywo na filmy i seriale twojego dostawcy. Kategorie nazywają się Movies albo Series, po czym następuje kategoria dostawcy. Wybranie serialu wypisuje jego odcinki w kolejności sezonów i odcinków. Naciśnij Enter, aby odtworzyć film albo odcinek.

Widok > Telewizja na żywo && Powtórki wraca do kanałów na żywo. Pole wyszukiwania czyści się przy przełączeniu.

Wideo na żądanie działa najlepiej z kontami Xtream Codes, które porządnie opisują swój katalog. Dla zwykłych playlist M3U program rozpoznaje filmy i seriale po nazwach grup i numeracji odcinków.

## Menedżer playlist {#playlist-manager}

Plik > Menedżer playlist (Ctrl+M) wypisuje twoje źródła playlist. Otwiera się z fokusem na liście.

- Dodaj plik: playlista M3U albo M3U8 na twoim komputerze.
- Dodaj URL: internetowy adres playlisty M3U.
- Dodaj Xtream Codes: konto Xtream Codes.
- Dodaj Stalker Portal: konto portalu Stalker (MAG).

Na źródle na liście klawisz aplikacji albo Shift+F10 otwiera jego menu: Kopiuj adres URL, Zmień nazwę (F2) i Usuń (Delete). Nadana źródłu nazwa jest tylko etykietą; nie zmienia źródła.

Wybierz OK, aby zachować zmiany, albo Anuluj, aby je porzucić. Po OK kanały ładują się na nowo.

### Konta Xtream Codes {#xtream-codes}

Konto Xtream Codes potrzebuje adresu serwera, nazwy użytkownika i hasła, które daje dostawca. Nazwa to twoja własna etykieta konta. Zostaw zaznaczone „Automatycznie dodaj adres URL XMLTV", aby przewodnik dostawcy trafił równocześnie do Menedżera EPG.

Konta Xtream Codes dają też wideo na żądanie, powtórki tam, gdzie dostawca je oferuje, oraz stan konta pod Plik > Informacje o koncie.

### Konta Stalker Portal {#stalker-portal}

Konto Stalker Portal potrzebuje adresu portalu i adresu MAC, który dostawca zarejestrował dla ciebie. Niektóre portale chcą też nazwy użytkownika i hasła. „Losowy MAC" wymyśla nowy adres MAC, przydatne tylko wtedy, gdy dostawca każe ci wybrać jeden. „Spróbuj dodać XMLTV dostawcy" dodaje przewodnik portalu, gdy go ma.

## Przewodnik po programach (EPG) {#epg}

Przewodnik po programach, czyli EPG, mówi, co leci na każdym kanale teraz i później. Pochodzi z plików XMLTV publikowanych przez dostawcę albo inne źródło. Program importuje je do lokalnej bazy danych i używa jej do opisu odcinka, Teraz w programie, Pokaż EPG..., list powtórek i wyszukiwań.

### Menedżer EPG {#epg-manager}

Plik > Menedżer EPG (Ctrl+E) wypisuje twoje źródła przewodnika.

- Dodaj plik: plik XMLTV na komputerze (.xml albo .xml.gz).
- Dodaj URL: internetowy adres przewodnika XMLTV.

Klawisz aplikacji albo Shift+F10 na źródle otwiera jego menu: Kopiuj adres URL, Zmień nazwę (F2) i Usuń (Delete). Wybierz OK, aby zachować zmiany.

### Importowanie przewodnika {#import-epg}

Plik > Importuj EPG do bazy danych (Ctrl+I) pobiera każde źródło przewodnika i ładuje je do bazy przewodnika. To działa w tle, więc możesz dalej oglądać i przeglądać, a komunikat daje znać, gdy skończy. Duże przewodniki mogą zająć kilka minut.

Przewodnik jest też od czasu do czasu odświeżany automatycznie, po cichu. Kanały są parowane z przewodnikiem po identyfikatorze i nazwach, łącznie ze zwykłymi wariantami kraju i jakości w nazwach kanałów.

Jeśli zaimportowany przewodnik nie pojawia się dla kanału, sprawdź, czy jedno z twoich źródeł go obejmuje, i zaimportuj ponownie. Importowanie prowadzi szczegółowy dziennik; zobacz Rozwiązywanie problemów.

### Teraz w programie {#whats-on-now}

Plik > Teraz w programie (Ctrl+W) wypisuje każdą audycję nadawaną teraz na wszystkich kanałach, w formie „audycja - kanał".

- Wpisywanie liter przeskakuje do pierwszej audycji zaczynającej się od nich.
- Tab przechodzi do pola Filtr; wpisywanie tam zwęża listę do pasujących audycji albo kanałów.
- Enter albo przycisk Odtwórz odtwarza kanał.
- Zaplanuj nagrywanie, albo menu audycji, planuje jej nagranie.
- Escape zamyka okno.

### Przewodnik kanału (Pokaż EPG) {#channel-epg}

Pokaż EPG..., w menu kanału, wypisuje audycje tego kanału od nadawanej teraz po tyle, ile przewodnik ma. Audycja nadawana teraz idzie pierwsza.

- Tab przełącza między listą a opisem podświetlonej audycji.
- Klawisz aplikacji albo Shift+F10 na audycji oferuje Zaplanuj nagrywanie.
- Escape zamyka okno.

## Powtórki {#catch-up}

Kanały, które trzymają archiwum, pozwalają oglądać audycje już nadane. Takie kanały mają Powtórki w swoim menu na liście kanałów. Otwiera okno powtórek kanału, wypisujące jego dawne audycje z datą i godziną.

- Strzałki góra i dół przechodzą przez audycje.
- Enter odtwarza podświetloną audycję.
- Klawisz aplikacji albo Shift+F10 otwiera jej menu: Otwórz, aby ją odtworzyć, i Pobierz, aby zapisać ją do pliku.
- Tab przechodzi do opisu audycji i z powrotem.
- Escape zamyka okno.

Po obejrzeniu audycji z powtórek i zamknięciu wbudowanego odtwarzacza wracasz do listy powtórek na tej samej audycji.

Jak daleko wstecz możesz sięgnąć, zależy od dostawcy, zwykle to kilka dni.

### Pobieranie powtórek {#catch-up-downloads}

Pobierz zapisuje audycję z powtórek do twojego folderu pobierania (zobacz Nagrania), nazwaną po kanale i nadaniu audycji. Każde pobieranie ma własne okno z postępem, upływającym czasem, pozostałym czasem i rozmiarem do tej pory, wszystko w jednym polu tylko do odczytu.

- Escape albo zamknięcie okna je ukrywa; pobieranie trwa dalej.
- Widok > Pokaż pobierane (Ctrl+Shift+D) przyprowadza okna pobierania z powrotem.
- Anuluj zatrzymuje pobieranie po zapytaniu o potwierdzenie. Anulowanego pobierania nie można wznowić.

Gdy pobieranie się nie powiedzie, okno mówi dlaczego i kilka razy próbuje znowu samodzielnie, gdy problem może być przejściowy. Wielu dostawców pozwala na jeden strumień naraz; zatrzymaj inne odtwarzanie tego samego konta, gdy pobieranie jest odmawiane.

## Wbudowany odtwarzacz {#built-in-player}

Wbudowany odtwarzacz odtwarza kanały wewnątrz programu. Otwiera się, gdy odtwarzasz kanał, chyba że Opcje > Pokaż odtwarzacz po naciśnięciu Enter jest wyłączone; wtedy odtwarzanie zaczyna się bez pokazywania okna.

Jego kontrolki w kolejności tabulacji: Odtwórz/Wstrzymaj, Zatrzymaj, Nagraj, Przesyłaj, Pełny ekran, suwak Głośność i Wybierz ścieżkę dźwiękową.

Klawisze w odtwarzaczu:

- Spacja: naciska przycisk z fokusem, czyli na Odtwórz/Wstrzymaj wstrzymuje i wznawia.
- Ctrl+P: odtwarzanie albo wstrzymanie.
- Ctrl+S: zatrzymanie.
- Ctrl+R: nagrywanie tego, co oglądasz, i zatrzymanie tego nagrania.
- Strzałki góra i dół: głośność skokami po 2%. Ctrl+Góra i Ctrl+Dół: skoki po 5%.
- A: następna ścieżka audio.
- D: wybór urządzenia wyjścia audio.
- Ctrl+C: przesyłanie na urządzenie.
- F11: pełny ekran włączony albo wyłączony. Escape z niego wychodzi.
- Ctrl+W: ukrycie okna odtwarzacza; odtwarzanie trwa dalej.
- Ctrl+Q: zamknięcie odtwarzacza i zatrzymanie odtwarzania.

Te same polecenia są w menu Odtwarzanie odtwarzacza. Odtwarzacz sam łączy się ponownie, gdy strumień na żywo się urwie, i trzyma wybraną ścieżkę audio.

### Ścieżki audio {#audio-tracks}

Kanały mogą nieść wiele ścieżek audio, na przykład inne języki albo audiodeskrypcję. Naciśnij A, aby przejść do następnej ścieżki, użyj Odtwarzanie > Ścieżka audio, albo Tab do Wybierz ścieżkę dźwiękową, które zawsze nazywa grającą ścieżkę.

Wybrana ścieżka jest zapamiętywana dla tego kanału i wraca następnym razem. O automatycznym wyborze zobacz Preferowana ścieżka audio.

### Urządzenie wyjścia audio {#audio-output-device}

Odtwarzanie > Urządzenie wyjścia audio... (D) wybiera głośniki albo słuchawki, których używa odtwarzacz, na przykład aby odsunąć dźwięk telewizji od czytnika ekranu. Domyślne systemu podąża za domyślnym urządzeniem Windows. Wybór jest zapamiętywany.

### Sterowanie odtwarzaczem z okna głównego {#player-from-main-window}

Menu Odtwarzacz w oknie głównym działa na wbudowanym odtwarzaczu bez przechodzenia do niego:

- Pokaż wbudowany odtwarzacz: Ctrl+Shift+J.
- Odtwórz/Wstrzymaj: Ctrl+Shift+P.
- Zatrzymaj: Ctrl+Shift+S.
- Przesyłaj / Połącz...: Ctrl+Shift+C.
- Ctrl+Góra i Ctrl+Dół zmieniają głośność.

## Odtwarzacz multimedialny {#media-player}

Opcje > Odtwarzacz multimedialny do użycia wybiera, co odtwarza twoje kanały: Wbudowany odtwarzacz, albo zewnętrzny odtwarzacz, taki jak VLC, MPC, MPC-BE, MPV, PotPlayer, Kodi albo SMPlayer. Niestandardowy odtwarzacz... pozwala wybrać każdy inny program po jego pliku.

Nagrywanie, pobieranie powtórek i przesyłanie działają tak samo przy każdym wybranym odtwarzaczu. Funkcje ścieżki audio i klawisze odtwarzacza opisane w tym podręczniku należą do wbudowanego odtwarzacza.

## Preferowana ścieżka audio {#preferred-audio-track}

Opcje > Preferowana ścieżka audio sprawia, że wbudowany odtwarzacz sam wybiera ścieżkę audio.

- „Preferuj ścieżkę audiodeskrypcji, jeśli kanał ją udostępnia" wszędzie wybiera audiodeskrypcję, gdzie jest oferowana. Rozpoznaje nazwy, jakich dostawcy naprawdę używają w wielu językach, jak audio description, AD, Audiodeskription i Hörfilm, oraz oznaczenie, jakie nadawcy kładą na takich ścieżkach.
- Pole tekstowe przyjmuje nazwy ścieżek albo języków, najbardziej pożądane najpierw, rozdzielone przecinkami, na przykład: audio description, Polish. Pozostawione puste, zostaje przy ścieżce, z którą kanał startuje.

Ścieżka wybrana ręcznie w odtwarzaczu jest zapamiętywana dla tego kanału i następnym razem ma pierwszeństwo przed tymi regułami. Ostatnia gdziekolwiek wybrana ścieżka jest używana na kanałach, gdzie nigdy nie wybrano.

Nagrania podążają za tym samym wyborem. Nagranie wyłącznie dźwiękowe trzyma tę jedną ścieżkę, którą byś słyszał, a nagranie wideo trzyma wszystkie ścieżki, oznaczając tę jako domyślną.

## Nagrania {#recordings}

Program może nagrywać dowolny kanał do pliku, podczas gdy oglądasz coś innego, albo gdy nic nie gra.

- Nagrania > Rozpocznij nagrywanie (Ctrl+Shift+R) nagrywa podświetlony kanał. Naciśnięte ponownie, się zatrzymuje.
- Nagraj w menu kanału robi to samo, a Nagraj we wbudowanym odtwarzaczu (Ctrl+R) nagrywa to, co oglądasz.
- Nagrania > Zatrzymaj nagrywanie zatrzymuje nagrywanie podświetlonego kanału, a Zatrzymaj wszystkie nagrania zatrzymuje wszystkie.
- Nagrania > Otwórz folder nagrań otwiera folder, gdzie zapisywane są pliki.
- Nagrania > Ustaw folder pobierania... wybiera ten folder. Pobieranie powtórek też tam trafia.

Nagrywanie oglądanego programu we wbudowanym odtwarzaczu używa tego samego połączenia z dostawcą, więc działa także przy kontach pozwalających na jeden strumień naraz.

Zatrzymanie nagrania może chwilę zająć, dopóki plik jest kończony. Zamknięcie programu pozwala bieżącym nagraniom samodzielnie dokończyć swoje pliki.

### Format nagrywania {#recording-formats}

Nagrania > Format nagrywania wybiera, jak nagrania są zapisywane:

- Jakość dostawcy (kopia, MKV): strumień dokładnie taki, jak nadany, ze wszystkimi ścieżkami audio i napisów. Zachowuje wszystko, co dostawca wysyła.
- Jakość dostawcy (kopia, MP4): ten sam obraz i dźwięk w pliku MP4, który odtwarza więcej urządzeń, bez napisów i teletekstu.
- Ponowne kodowanie x264 (MKV albo MP4): mniejszy, ponownie zakodowany plik. Zużywa znacznie więcej czasu procesora.
- Tylko dźwięk (MP3 V0, FLAC, WAV, AAC M4A albo Opus): tylko dźwięk, przydatne dla radia.

### Zaplanowane nagrania {#scheduled-recordings}

Aby nagrać przyszłą audycję, wybierz Zaplanuj nagrywanie na audycji w Pokaż EPG..., Teraz w programie albo w wierszu audycji w wynikach wyszukiwania. Zaplanuj nagrywanie na kanale otwiera jego przewodnik, abyś najpierw wybrał audycję.

Nagrania > Zaplanowane nagrania... wypisuje każde zaplanowane, trwające i zakończone nagranie z czasem, tytułem, kanałem, statusem i formatem.

- Klawisz aplikacji albo Shift+F10 na nagraniu otwiera jego menu: Odśwież, Anuluj i Usuń.
- Usuń zabiera podświetlone nagranie z listy; trwające jest najpierw zatrzymywane po zapytaniu.
- Escape zamyka okno.

Zaplanowane nagrania startują same, gdy program działa, także zminimalizowany do zasobnika systemowego.

### Margines nagrywania {#schedule-padding}

Audycje rzadko zaczynają się i kończą dokładnie na czas. Nagrania > Margines nagrywania... ustawia, ile minut przed audycją zaczyna się zaplanowane nagranie i ile minut po jej końcu nagrywa dalej. Nagrania ręczne nie są dotknięte.

### Wyłączanie po nagraniach {#shutdown-after-recordings}

Nagrania > Wyłącz komputer po zakończeniu nagrań wyłącza komputer, gdy każde trwające i zaplanowane nagranie się skończy, przydatne przy nocnym nagraniu.

Nigdy nie działa, gdy coś jeszcze nagrywa albo czeka w harmonogramie. Gdy przyjdzie czas, okno odlicza 60 sekund; focus jest na Anuluj wyłączanie, więc Enter albo Escape je zatrzymują, a Wyłącz teraz nie czeka. Opcja wyłącza się sama po jednym użyciu albo anulowaniu.

## Przesyłanie {#casting}

Przesyłanie wysyła kanał na telewizor albo głośnik w twojej sieci: urządzenia Chromecast, renderery DLNA i UPnP oraz urządzenia AirPlay, takie jak Apple TV i HomePod.

Plik > Przesyłaj do... przeszukuje twoją sieć i wypisuje znalezione urządzenia. Wybierz urządzenie i Połącz. Niektóre urządzenia AirPlay najpierw chcą Paruj..., które pyta o kod pokazany na telewizorze. Po połączeniu odtwarzanie kanału wysyła go na urządzenie. Ponowne wybranie Przesyłaj do... rozłącza.

Przycisk Przesyłaj we wbudowanym odtwarzaczu, Odtwarzacz > Przesyłaj / Połącz... (Ctrl+Shift+C) i Ctrl+C w odtwarzaczu robią to samo.

Do przesyłania komputer i urządzenie muszą być w tej samej sieci.

## Informacje o koncie {#account-info}

Plik > Informacje o koncie (Ctrl+Shift+A) pokazuje stan twoich kont Xtream Codes i Stalker Portal: czy konto jest aktywne, jego datę wygaśnięcia i pozostałe dni, czy jest próbne, oraz ile połączeń pozwala i ma otwartych. Konta znalezione w adresach playlist też są wypisywane.

Wybierz konto na liście; jego szczegóły pojawiają się w polu tylko do odczytu pod spodem. Odśwież ponownie pyta dostawcę, a Kopiuj szczegóły kładzie szczegóły w schowku. Hasła nigdy nie są pokazywane.

## Opcje {#options}

Menu Opcje zawiera ustawienia programu. Każde jest zapisywane od razu po zmianie.

- Odtwarzacz multimedialny do użycia: zobacz Odtwarzacz multimedialny.
- Preferowana ścieżka audio: zobacz Preferowana ścieżka audio.
- Język: zobacz Język.
- Minimalizuj do zasobnika systemowego: zobacz Zasobnik systemowy.
- Pokaż odtwarzacz po naciśnięciu Enter: włączone, odtwarzanie kanału pokazuje okno wbudowanego odtwarzacza. Wyłączone, odtwarzanie zaczyna się, a focus zostaje na liście kanałów.
- Pokaż adres URL strumienia: dodaje pole Adres URL strumienia za opisem odcinka w oknie głównym.
- Automatycznie sprawdzaj aktualizacje: zobacz Aktualizacje.

### Język {#language}

Opcje > Język wybiera język programu. Automatycznie podąża za językiem Windows albo pulpitu i używa angielskiego, gdy nie ma dla niego tłumaczenia. Zmiana wchodzi w całości po ponownym uruchomieniu programu.

Program jest dostępny po angielsku, hiszpańsku, arabsku, portugalsku brazylijskim, francusku, niemiecku, rosyjsku, turecku, włosku, polsku, hindi, chińsku uproszczonym, japońsku i węgiersku. Poprawki i nowe języki są mile widziane; zobacz Uzyskiwanie pomocy.

### Zasobnik systemowy {#system-tray}

Gdy Opcje > Minimalizuj do zasobnika systemowego jest włączone, zamknięcie albo zminimalizowanie okna głównego ukrywa je w obszarze powiadomień zamiast kończyć program, więc zaplanowane nagrania trwają dalej. Aktywuj ikonę zasobnika, aby przywrócić okno. Jego menu ma też Przywróć, Sterowanie odtwarzaczem, Zatrzymaj nagranie(a) gdy coś nagrywa, oraz Zakończ.

Aby całkiem zakończyć program, użyj Plik > Zakończ (Ctrl+Q).

## Aktualizacje {#updates}

Pod Windows program może aktualizować się sam. Pomoc > Sprawdź aktualizacje... szuka teraz nowej wersji, a Opcje > Automatycznie sprawdzaj aktualizacje sprawdza w tle od czasu do czasu.

Gdy jest aktualizacja, dowiesz się, co nowego, i zostaniesz zapytany, czy ją zainstalować. Pobieranie jest sprawdzane, zanim cokolwiek zostanie zainstalowane. Program zamyka się podczas aktualizacji i sam restartuje po jej zakończeniu, po czym mówi, czy się udała. Twoje ustawienia, ulubione i nagrania są zachowywane.

Pod Linuksem zainstaluj raczej nowy pakiet na starym.

## Rozwiązywanie problemów {#troubleshooting}

- Pomoc > Otwórz folder dzienników otwiera folder z plikami dziennika programu, łącznie z dziennikiem importów przewodnika i jednym dziennikiem na nagranie.
- Pomoc > Kopiuj dziennik i informacje diagnostyczne kopiuje raport z wersją programu, twoim systemem i świeżymi liniami dziennika do schowka, gotowy do wklejenia do zgłoszenia błędu. Zawiera twoje adresy strumieni, w których może być login dostawcy; przejrzyj go przed publicznym udostępnieniem.

Częste problemy:

- Kanał się nie odtwarza: wielu dostawców pozwala na jeden strumień na konto naraz. Zatrzymaj inne odtwarzanie, nagrania albo pobieranie tego samego konta i spróbuj ponownie.
- Kanał nie ma przewodnika: sprawdź, czy jedno z twoich źródeł EPG go obejmuje, i zaimportuj przewodnik ponownie.
- Odtwarzanie się tnie: wbudowany odtwarzacz sam reguluje swój bufor. Możesz podnieść internal_player_buffer_seconds i internal_player_max_buffer_seconds w iptvclient.conf dla cierpliwszego bufora.
- Powtórki mówią, że audycja nie jest dostępna: pewnie jest starsza niż archiwum dostawcy.

## Skróty klawiszowe {#keyboard-shortcuts}

Wszędzie:

- F1: pomoc o tym, czego używasz.

Okno główne:

- Ctrl+M: Menedżer playlist.
- Ctrl+E: Menedżer EPG.
- Ctrl+I: Importuj EPG do bazy danych.
- Ctrl+W: Teraz w programie.
- Ctrl+Shift+A: Informacje o koncie.
- Ctrl+D: dodanie wybranego kanału do ulubionych albo usunięcie.
- Delete: usunięcie wybranego kanału z ulubionych, w kategorii Ulubione.
- Ctrl+Shift+R: rozpoczęcie albo zatrzymanie nagrywania wybranego kanału.
- Ctrl+Shift+D: pokazanie okien pobierania powtórek.
- Ctrl+Shift+J: pokazanie wbudowanego odtwarzacza.
- Ctrl+Shift+P: odtwarzanie albo wstrzymanie wbudowanego odtwarzacza.
- Ctrl+Shift+S: zatrzymanie wbudowanego odtwarzacza.
- Ctrl+Shift+C: przesyłanie albo łączenie.
- Ctrl+Góra i Ctrl+Dół: głośność wbudowanego odtwarzacza.
- Enter: odtworzenie wybranego kanału.
- Klawisz aplikacji albo Shift+F10: menu kanału.
- Ctrl+Q: zakończenie.

Wbudowany odtwarzacz:

- Spacja: naciśnięcie przycisku z fokusem, na przykład Wstrzymaj.
- Ctrl+P: odtwarzanie albo wstrzymanie.
- Ctrl+S: zatrzymanie.
- Ctrl+R: nagrywanie.
- Góra i Dół: głośność skokami po 2%; z Ctrl, skoki po 5%.
- A: następna ścieżka audio.
- D: urządzenie wyjścia audio.
- Ctrl+C: przesyłanie.
- F11: pełny ekran; Escape z niego wychodzi.
- Ctrl+W: ukrycie odtwarzacza.
- Ctrl+Q: zamknięcie odtwarzacza.

Listy źródeł w Menedżerze playlist i Menedżerze EPG:

- F2: zmiana nazwy.
- Delete: usuwanie.

## Uzyskiwanie pomocy {#support}

Pytania, zgłoszenia błędów i nowości o wydaniach:

- Grupa Telegram SerrebiProjects: https://t.me/SerrebiProjects
- Zgłoszenia błędów i sugestie na GitHubie: https://github.com/serrebidev/Accessible-IPTV-Client/issues

Pomoc > O programie... pokazuje używaną wersję i linkuje obie. Przy zgłaszaniu problemu Pomoc > Kopiuj dziennik i informacje diagnostyczne daje szczegóły potrzebne do namierzenia go.

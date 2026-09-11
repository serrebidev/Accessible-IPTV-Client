<!--
Accessible IPTV Client Kullanım Kılavuzu, Türkçe. İngilizce kaynak
docs/help/en.md dosyasındadır. Çevirmenler için not: {#topic ID}
tanımlayıcılarını olduğu gibi bırakın; yalnızca başlık metnini çevirin.
Henüz çevrilmemiş bir bölüm atlanabilir; F1 o zaman İngilizce bölümü açar.
-->

# Accessible IPTV Client Kullanım Kılavuzu {#user-guide}

Accessible IPTV Client, IPTV sağlayıcılarından canlı televizyon, radyo ve isteğe bağlı video oynatır. Klavye ve NVDA, JAWS, Narrator ve Orca gibi ekran okuyucular için tasarlanmıştır ve çok büyük oynatma listeleri ile program rehberleriyle başa çıkar.

Bu kılavuz programın her bölümünü açıklar. Programın herhangi bir yerinde F1'e basın; kılavuz o an kullandığınız şeyin bölümünde açılır.

## Bu kılavuzu kullanma {#using-help}

Kılavuz penceresinin dört bölümü vardır, sekme sırasıyla:

- Konular: bölüm listesi. Ok tuşlarıyla gezinmek kılavuz metnini o bölüme taşır. Doğrudan metne girmek için Enter'a basın.
- Kılavuz metni: kılavuzun tamamı tek bir salt okunur belge olarak. Ok tuşlarıyla ya da ekran okuyucunuzun sürekli okuma komutuyla okuyun; metni seçmek ve kopyalamak her belgedeki gibi çalışır.
- Bul: bir kelime yazın ve geçtiği bir sonraki yere atlamak için Enter'a basın.
- Kapat.

Kılavuz penceresindeki tuşlar:

- Ctrl+F: Bul alanına gitmek.
- F3: bir sonraki eşleşmeyi bulmak. Shift+F3: öncekini bulmak.
- F1: bu bölüme geri dönmek.
- Escape: kılavuzu kapatmak ve neredeyseniz oraya dönmek.

F1 bağlama duyarlıdır. Bir menü öğesinde, bir pencerede, yerleşik oynatıcıda ya da ana pencerenin bir denetiminde basıldığında, kılavuzu o öğenin bölümünde açar. Henüz bir bölüm yazılmamış yerlerde kılavuz başında açılır. Yardım > Kullanım Kılavuzu her zaman başında açar.

Kılavuz programın parçasıdır, bu yüzden internet bağlantısı olmadan çalışır. Bir çevirisi varsa programın arayüz dilinde, yoksa İngilizce gösterilir.

## İlk adımlar {#getting-started}

1. Dosya > Oynatma listesi yöneticisi (Ctrl+M) penceresini açın ve sağlayıcınızı ekleyin: bir M3U oynatma listesi dosyası ya da adresi, bir Xtream Codes hesabı, ya da bir Stalker Portal hesabı. Tamam'ı seçin. Kanallar arka planda yüklenir.
2. Sağlayıcınız size program rehberi (EPG) adresi veriyorsa, Dosya > EPG Yöneticisi (Ctrl+E) içine ekleyin. Xtream Codes hesabı olanlar sizin için ekleyebilir.
3. Rehberi Dosya > EPG'yi veritabanına aktar (Ctrl+I) ile içe aktarın. Bu arka planda çalışır ve bitince haber verir.
4. Bir kategori seçin, bir kanal seçin ve oynatmak için Enter'a basın.

Oynatma listeleriniz, rehber kaynaklarınız ve ayarlarınız oturumlar arasında saklanır, bunu yalnızca bir kez yapmanız gerekir.

## Ana pencere {#main-window}

Ana pencerede kanallara göz atar ve oynatırsınız. Tab, denetimleri arasında bu sırayla gezinir; Shift+Tab geriye gider:

1. Çalma listesi görünümü: hangi oynatma listesine bakılacağı.
2. Kategoriler: kanal grupları.
3. Ara: kanal listesini süzer.
4. Kanallar: seçili kategorinin kanalları, ya da arama sonuçları.
5. Bölüm açıklaması: vurgulanan kanalda şimdi ne yayınlandığı.
6. Yayın URL'si: vurgulanan kanalın adresi; yalnızca Seçenekler > Yayın URL'sini göster açıkken görünür.

Son denetimden sonra Tab ilkine döner.

Linux'ta bu kılavuzun anlattığı menüler pencerenin üstündeki Menü düğmesinin altındadır.

### Çalma listesi görünümü {#playlist-view}

Birden fazla oynatma listeniz varsa, Çalma listesi görünümü listesi kategorilerin ve kanalların neyi göstereceğini seçer: tüm oynatma listeleri ya da tek biri. Seçiminiz hatırlanır.

### Kategoriler {#categories}

Kategori listesi, oynatma listelerinizdeki kanal gruplarını tutar. İlk satırları Tüm kanallar ve, bazılarını ekledikten sonra, Sık kullanılanlar'dır. Her satır kaç kanal içerdiğini söyler.

- Yukarı ve Aşağı oklar kanal listesini değiştirmeden kategoriler arasında gezinir; böylece önce onları dinleyebilirsiniz.
- Enter vurgulanan kategoriyi açar ve kanal listesine geçer.
- Tab vurgulanan kategoriyi açar ve Ara alanına geçer.
- Sol ve Sağ oklar, alt grupları olan bir kategoriyi kapatır ve açar.

### Arama {#search}

Kanal listesini süzmek için Ara alanına yazın, sonra süzmeyi uygulayıp devam etmek için Enter'a ya da Tab'a basın. Tüm kanallar içinde aramak program rehberine de bakar; bir program adıyla arama onu yayınlayan kanalları listeleyebilir. Alanı boşaltın ve tüm kategoriyi yeniden görmek için Enter'a basın.

### Kanal listesi {#channel-list}

Kanal listesi, seçili kategorinin ya da aramanın kanallarını gösterir.

- Enter vurgulanan kanalı oynatır.
- Uygulamalar tuşu, Shift+F10 ya da sağ tıklama kanalın menüsünü açar: Oynat, Sık kullanılanlara ekle ya da Sık kullanılanlardan kaldır, Kaydet ya da Kaydı durdur, Kayıt zamanla, EPG'yi görüntüle..., ve arşivi olan kanallar için Geri izleme.
- Ctrl+D kanalı sık kullanılanlara ekler ya da kaldırır. Sık kullanılanlar kategorisinde Delete kaldırır.
- Ctrl+Shift+R kanalın kaydını başlatır; yeniden basıldığında durdurur.

Sık kullanılan kanallar "(Sık kullanılan)" olarak işaretlenir ve her satır, rehberde varsa şu an yayında olan programı da adlandırır. Bir arama program da bulduysa, satırları programı ve onun yayınlandığı kanalı adlandırır.

### Bölüm açıklaması ve yayın URL'si {#episode-description}

Kanal listesinden Tab, Bölüm açıklamasına ulaşır: vurgulanan kanalda yayında olan program, saatleri ve açıklamasıyla, ve sonra ne geleceği. Shift+Tab doğrudan kanal listesine döner. Metin vurgulanan kanalı izler.

Seçenekler > Yayın URL'sini göster açıkken, Yayın URL'si alanı bir Tab sonra gelir. Kanalın adresini gösterir; sorun bildirirken yardımcı olabilir. Çoğu insan onu kapalı bırakır.

## Sık kullanılanlar {#favorites}

Sık kullanılanlar, en çok izlediğiniz kanalları tek yerde tutar. Bir kanalda Ctrl+D'ye basın, menüsünü kullanın ya da Görünüm > Sık kullanılanlara ekle'yi seçin. Sık kullanılanlar, kategori listesinin başına yakın Sık kullanılanlar kategorisinde görünür; Görünüm > Sık kullanılanlara git sizi oraya götürür.

Bir sık kullanılanı kaldırmak için üzerinde yeniden Ctrl+D'ye basın ya da Sık kullanılanlar kategorisinde Delete'e basın.

Sık kullanılanlar sağlayıcı ve kanala göre saklanır, yayın adresine göre değil; bu yüzden oynatma listesi güncellemesini aşar. Hesabınızla ilgili hiçbir şey onlarla birlikte saklanmaz.

## İstek üzerine video {#video-on-demand}

Görünüm > İstek üzerine video (filmler && diziler), kategori listesini canlı kanallardan sağlayıcınızın filmlerine ve dizilerine çevirir. Kategoriler, sağlayıcının kategorisiyle birlikte Movies ya da Series olarak adlandırılır. Bir dizi seçmek bölümlerini sezon ve bölüm sırasıyla listeler. Bir filmi ya da bölümü oynatmak için Enter'a basın.

Görünüm > Canlı TV && Geri izleme canlı kanallara döner. Geçişte arama alanı temizlenir.

İstek üzerine video, kataloğunu düzgün anlatan Xtream Codes hesaplarıyla en iyi çalışır. Düz M3U listelerinde program filmleri ve dizileri grup adlarından ve bölüm numaralandırmasından tanır.

## Oynatma listesi yöneticisi {#playlist-manager}

Dosya > Oynatma listesi yöneticisi (Ctrl+M) oynatma listesi kaynaklarınızı listeler. Odak listede olarak açılır.

- Dosya ekle: bilgisayarınızda bir M3U ya da M3U8 oynatma listesi.
- URL ekle: bir M3U oynatma listesinin internet adresi.
- Xtream Codes ekle: bir Xtream Codes hesabı.
- Stalker Portal ekle: bir Stalker (MAG) portal hesabı.

Listedeki bir kaynak üzerinde Uygulamalar tuşu ya da Shift+F10 menüsünü açar: URL'yi kopyala, Yeniden adlandır (F2) ve Sil (Delete). Bir kaynağa verdiğiniz ad yalnızca bir etikettir; kaynağı değiştirmez.

Değişikliklerinizi korumak için Tamam'ı, atmak için İptal'i seçin. Tamam'dan sonra kanallar yeniden yüklenir.

### Xtream Codes hesapları {#xtream-codes}

Bir Xtream Codes hesabı sunucu adresi, kullanıcı adı ve şifre gerektirir; sağlayıcınız verir. Ad, hesap için kendi etiketinizdir. Sağlayıcının program rehberi aynı anda EPG Yöneticisi'ne girsin diye "XMLTV URL'sini otomatik ekle" kutusunu işaretli bırakın.

Xtream Codes hesapları ayrıca istek üzerine video, sağlayıcının sunduğu yerlerde geri izleme ve Dosya > Hesap bilgileri altında hesap durumu verir.

### Stalker Portal hesapları {#stalker-portal}

Bir Stalker Portal hesabı portal adresini ve sağlayıcınızın sizin için kaydettiği MAC adresini gerektirir. Bazı portallar ayrıca kullanıcı adı ve şifre ister. "MAC'i rastgele oluştur" yeni bir MAC adresi uydurur; yalnızca sağlayıcı bir tane seçmenizi istediğinde faydalıdır. "Sağlayıcının XMLTV'sini eklemeyi dene", varsa portalın program rehberini ekler.

## Program rehberi (EPG) {#epg}

Program rehberi, yani EPG, her kanalda şimdi ve sonra ne yayınlandığını söyler. Sağlayıcınızın ya da başka bir kaynağın yayımladığı XMLTV rehber dosyalarından gelir. Program onları yerel bir veritabanına aktarır; bölüm açıklaması, Şimdi yayında, EPG'yi görüntüle..., geri izleme listeleri ve aramalar için bunu kullanır.

### EPG Yöneticisi {#epg-manager}

Dosya > EPG Yöneticisi (Ctrl+E) rehber kaynaklarınızı listeler.

- Dosya ekle: bilgisayarınızda bir XMLTV dosyası (.xml ya da .xml.gz).
- URL ekle: bir XMLTV rehberinin internet adresi.

Bir kaynak üzerinde Uygulamalar tuşu ya da Shift+F10 menüsünü açar: URL'yi kopyala, Yeniden adlandır (F2) ve Sil (Delete). Değişikliklerinizi korumak için Tamam'ı seçin.

### Rehberi içe aktarma {#import-epg}

Dosya > EPG'yi veritabanına aktar (Ctrl+I) her rehber kaynağını indirir ve rehber veritabanına yükler. Arka planda çalışır; izlemeye ve göz atmaya devam edebilirsiniz, ve bitince bir ileti haber verir. Büyük rehberler birkaç dakika sürebilir.

Rehber ayrıca zaman zaman kendiliğinden, sessizce tazelenir. Kanallar, rehberle kimlikleri ve adlarıyla eşleşir; kanal adlarındaki alışılmış ülke ve kalite çeşitleriyle birlikte.

İçe aktarılan rehber bir kanalda görünmüyorsa, kaynaklarınızdan birinin onu kapsadığını denetleyin, sonra yeniden içe aktarın. İçe aktarma ayrıntılı bir günlük tutar; bkz. Sorun giderme.

### Şimdi yayında {#whats-on-now}

Dosya > Şimdi yayında (Ctrl+W) şu an tüm kanallarda yayında olan her programı "program - kanal" biçiminde listeler.

- Harf yazmak, onlarla başlayan ilk programa atlar.
- Tab Filtre alanına geçer; orada yazmak listeyi eşleşen programlara ya da kanallara daraltır.
- Enter ya da Oynat düğmesi kanalı oynatır.
- Kayıt zamanla, ya da programın menüsü, kaydını zamanlar.
- Escape pencereyi kapatır.

### Kanal rehberi (EPG'yi görüntüle) {#channel-epg}

Bir kanalın menüsündeki EPG'yi görüntüle..., o kanalın programlarını yayında olandan rehberin sonuna kadar listeler. Yayında olan program ilk sırada gelir.

- Tab, liste ile vurgulanan programın açıklaması arasında geçiş yapar.
- Bir programda Uygulamalar tuşu ya da Shift+F10 Kayıt zamanla sunar.
- Escape pencereyi kapatır.

## Geri izleme {#catch-up}

Arşiv tutan kanallar, çoktan yayınlanmış programları izlemenizi sağlar. Bu kanalların kanal listesindeki menüsünde Geri izleme bulunur. Kanalın geri izleme penceresini açar; geçmiş programlarını tarih ve saatleriyle listeler.

- Yukarı ve Aşağı oklar programlar arasında gezinir.
- Enter vurgulanan programı oynatır.
- Uygulamalar tuşu ya da Shift+F10 menüsünü açar: Aç, oynatmak için; İndir, dosya olarak kaydetmek için.
- Tab programın açıklamasına geçer ve geri döner.
- Escape pencereyi kapatır.

Geri izlenen bir programı izledikten sonra yerleşik oynatıcıyı kapatınca, aynı programda geri izleme listesine dönersiniz.

Ne kadar geriye gidebileceğiniz sağlayıcınıza bağlıdır, çoğunlukla birkaç gün.

### Geri izleme indirmeleri {#catch-up-downloads}

İndir, geri izlenen bir programı indirme klasörünüze kaydeder (bkz. Kayıtlar); kanal ve programın yayın zamanıyla adlandırılır. Her indirmenin kendi penceresi vardır; ilerleme, geçen süre, kalan süre ve şimdiye kadarki boyut tek bir salt okunur alandadır.

- Escape, ya da pencereyi kapatmak, onu gizler; indirme sürer.
- Görünüm > İndirmeleri göster (Ctrl+Shift+D) indirme pencerelerini geri getirir.
- İptal, onay sorduktan sonra indirmeyi durdurur. İptal edilen indirme devam ettirilemez.

Bir indirme başarısız olursa pencere neden olduğunu söyler ve sorun geçici olabilirse birkaç kez kendiliğinden yeniden dener. Birçok sağlayıcı bir kerede yalnızca bir akışa izin verir; bir indirme reddedilirse aynı hesaptan diğer oynatmayı durdurun.

## Yerleşik oynatıcı {#built-in-player}

Yerleşik oynatıcı kanalları programın içinde oynatır. Bir kanal oynattığınızda açılır; Seçenekler > Enter'a basıldığında oynatıcıyı göster kapalıysa açılmaz; o zaman oynatma pencereyi göstermeden başlar.

Denetimleri, sekme sırasıyla: Oynat/Duraklat, Durdur, Kaydet, Yayınla, Tam ekran, Ses düzeyi kaydırıcısı ve Ses parçası seç.

Oynatıcıdaki tuşlar:

- Boşluk: odakta olan düğmeye basar; Oynat/Duraklat üzerinde duraklatır ve sürdürür.
- Ctrl+P: oynatma ya da duraklatma.
- Ctrl+S: durdurma.
- Ctrl+R: izlediğinizi kaydetme, ve o kaydı durdurma.
- Yukarı ve Aşağı oklar: ses düzeyi %2 adımlarla. Ctrl+Yukarı ve Ctrl+Aşağı: %5 adımlarla.
- A: sonraki ses parçası.
- D: ses çıkış cihazını seçme.
- Ctrl+C: bir cihaza yayınlama.
- F11: tam ekranı açma ya da kapatma. Escape tam ekrandan çıkar.
- Ctrl+W: oynatıcı penceresini gizleme; oynatma sürer.
- Ctrl+Q: oynatıcıyı kapatma ve oynatmayı durdurma.

Aynı komutlar oynatıcının Oynatma menüsündedir. Oynatıcı, canlı akış kesildiğinde kendiliğinden yeniden bağlanır ve seçtiğiniz ses parçasını tutar.

### Ses parçaları {#audio-tracks}

Kanallar birkaç ses parçası taşıyabilir: başka diller ya da sesli betimleme gibi. Sonraki parçaya geçmek için A'ya basın, Oynatma > Ses parçası'nı kullanın ya da Tab ile Ses parçası seç'e gidin; o, oynayan parçayı her zaman adlandırır.

Seçtiğiniz bir parça o kanal için hatırlanır ve gelecek sefer geri gelir. Otomatik seçim için bkz. Tercih edilen ses parçası.

### Ses çıkış cihazı {#audio-output-device}

Oynatma > Ses çıkış cihazı... (D), oynatıcının hangi hoparlörleri ya da kulaklıkları kullanacağını seçer; örneğin TV sesini ekran okuyucunuzdan uzak tutmak için. Sistem varsayılanı, Windows'un varsayılan cihazını izler. Seçim hatırlanır.

### Oynatıcıyı ana pencereden yönetme {#player-from-main-window}

Ana penceredeki Oynatıcı menüsü, ona geçmeden yerleşik oynatıcıya etki eder:

- Yerleşik oynatıcıyı göster: Ctrl+Shift+J.
- Oynat/Duraklat: Ctrl+Shift+P.
- Durdur: Ctrl+Shift+S.
- Yayınla / Bağlan...: Ctrl+Shift+C.
- Ctrl+Yukarı ve Ctrl+Aşağı ses düzeyini değiştirir.

## Medya oynatıcı {#media-player}

Seçenekler > Kullanılacak medya oynatıcı, kanallarınızı neyin oynatacağını seçer: Yerleşik oynatıcı, ya da VLC, MPC, MPC-BE, MPV, PotPlayer, Kodi ya da SMPlayer gibi bir dış oynatıcı. Özel oynatıcı..., başka herhangi bir programı dosyasından seçmenize izin verir.

Kayıt, geri izleme indirmeleri ve yayınlama, hangi oynatıcıyı seçerseniz aynı çalışır. Ses parçası özellikleri ve bu kılavuzda anlatılan oynatıcı tuşları yerleşik oynatıcıya aittir.

## Tercih edilen ses parçası {#preferred-audio-track}

Seçenekler > Tercih edilen ses parçası, yerleşik oynatıcının kendiliğinden bir ses parçası seçmesini sağlar.

- "Kanalda varsa sesli betimleme parçasını tercih et", sunulduğu her yerde sesli betimlemeyi seçer. Sağlayıcıların birçok dilde gerçekten kullandığı adları tanır: audio description, AD, Audiodeskription ve Hörfilm gibi; ayrıca yayıncıların bu parçalara koyduğu işareti de tanır.
- Metin alanı parça adlarını ya da dilleri alır, en çok istenenler önce, virgülle ayrılmış; örneğin: audio description, Turkish. Boş bırakılırsa, kanalın hangi parçayla başladığıyla kalır.

Oynatıcıda elle seçilen bir parça o kanal için hatırlanır ve bir dahaki sefere bu kurallara üstünlük eder. Herhangi bir yerde en son seçilen parça, hiç seçim yapmadığınız kanallarda kullanılır.

Kayıtlar aynı seçimi izler. Yalnızca ses kaydı duyacağınız tek parçayı tutar; video kaydı tüm parçaları tutar ve onu varsayılan olarak işaretler.

## Kayıtlar {#recordings}

Program, siz başka bir şey izlerken ya da hiçbir şey oynamazken herhangi bir kanalı dosyaya kaydedebilir.

- Kayıtlar > Kaydı başlat (Ctrl+Shift+R) vurgulanan kanalı kaydeder. Yeniden basıldığında durur.
- Bir kanalın menüsündeki Kaydet aynı şeyi yapar; yerleşik oynatıcıdaki Kaydet (Ctrl+R) izlediğinizi kaydeder.
- Kayıtlar > Kaydı durdur vurgulanan kanalın kaydını durdurur; Tüm kayıtları durdur hepsini durdurur.
- Kayıtlar > Kayıt klasörünü aç, dosyaların kaydedildiği klasörü açar.
- Kayıtlar > İndirme klasörünü ayarla... o klasörü seçer. Geri izleme indirmeleri de oraya gider.

Yerleşik oynatıcıda izlediğinizi kaydetmek sağlayıcıyla aynı bağlantıyı kullanır; bir kerede yalnızca bir akışa izin veren hesaplarda bile çalışır.

Kaydı durdurmak, dosya tamamlanırken bir an sürebilir. Programı kapatmak, devam eden kayıtların dosyalarını kendi başlarına bitirmesine izin verir.

### Kayıt biçimi {#recording-formats}

Kayıtlar > Kayıt biçimi, kayıtların nasıl saklanacağını seçer:

- Sağlayıcı kalitesi (kopya, MKV): akış, yayımlandığı gibi, tüm ses ve altyazı parçalarıyla. Sağlayıcının gönderdiği her şeyi tutar.
- Sağlayıcı kalitesi (kopya, MP4): aynı görüntü ve ses, daha çok cihazın oynattığı bir MP4 dosyasında; altyazı ve teletext olmadan.
- x264 yeniden kodlama (MKV ya da MP4): daha küçük, yeniden kodlanmış dosya. Çok daha fazla işlemci zamanı kullanır.
- Yalnızca ses (MP3 V0, FLAC, WAV, AAC M4A ya da Opus): yalnızca ses; radyo için kullanışlı.

### Zamanlanmış kayıtlar {#scheduled-recordings}

Gelecek bir programı kaydetmek için EPG'yi görüntüle..., Şimdi yayında ya da arama sonuçlarındaki bir program satırında bir program üzerinde Kayıt zamanla'yı seçin. Bir kanalda Kayıt zamanla, önce programı seçebilmeniz için onun rehberini açar.

Kayıtlar > Zamanlanmış kayıtlar... her zamanlanmış, süren ve bitmiş kaydı zamanı, başlığı, kanalı, durumu ve biçimiyle listeler.

- Bir kayıtta Uygulamalar tuşu ya da Shift+F10 menüsünü açar: Yenile, İptal ve Sil.
- Sil, vurgulanan kaydı listeden çıkarır; süren olan önce sorulup durdurulur.
- Escape pencereyi kapatır.

Zamanlanmış kayıtlar, program çalışırken kendi kendine başlar; sistem tepsisine küçültülmüşken bile.

### Zamanlama payı {#schedule-padding}

Programlar nadiren tam zamanında başlar ve biter. Kayıtlar > Zamanlama payı..., zamanlanmış bir kaydın bir programdan kaç dakika önce başlayacağını ve bitiminden kaç dakika sonra kaydetmeye devam edeceğini ayarlar. Elle yapılan kayıtlar etkilenmez.

### Kayıtlardan sonra kapatma {#shutdown-after-recordings}

Kayıtlar > Kayıtlar bittiğinde bilgisayarı kapat, her süren ve zamanlanmış kayıt bittiğinde bilgisayarı kapatır; gece yarısı kaydı için kullanışlıdır.

Hâlâ bir şey kaydediyorken ya da programda beklerken hiçbir zaman devreye girmez. Zamanı gelince bir pencere 60 saniye geriye sayar; odak Kapatmayı iptal et üzerindedir, Enter ya da Escape onu durdurur, Şimdi kapat beklemez. Seçenek, bir kez kullanıldıktan ya da iptal edildikten sonra kendiliğinden kapanır.

## Yayınlama {#casting}

Yayınlama, bir kanalı ağınızda bir TV'ye ya da hoparlöre gönderir: Chromecast cihazları, DLNA ve UPnP işleyicileri, ve Apple TV ile HomePod gibi AirPlay cihazları.

Dosya > Şuraya yayınla... ağınızı tarar ve bulduğu cihazları listeler. Bir cihaz ve Bağlan'ı seçin. Bazı AirPlay cihazları önce Eşleştir... ister; TV'de gösterilen kodu sorar. Bağlandıktan sonra bir kanal oynatmak onu cihaza gönderir. Yeniden Şuraya yayınla... seçmek bağlantıyı keser.

Yerleşik oynatıcıdaki Yayınla düğmesi, Oynatıcı > Yayınla / Bağlan... (Ctrl+Shift+C) ve oynatıcıda Ctrl+C aynı şeyi yapar.

Yayınlamak için bilgisayar ve cihaz aynı ağda olmalıdır.

## Hesap bilgileri {#account-info}

Dosya > Hesap bilgileri (Ctrl+Shift+A) Xtream Codes ve Stalker Portal hesaplarınızın durumunu gösterir: hesabın etkin olup olmadığı, bitiş tarihi ve kalan günler, deneme olup olmadığı, kaç bağlantıya izin verdiği ve kaçının açık olduğu. Oynatma listesi adreslerinde bulunan hesaplar da listelenir.

Listedeki bir hesabı seçin; ayrıntıları aşağıdaki salt okunur alanda görünür. Yenile sağlayıcıya yeniden sorar; Ayrıntıları kopyala ayrıntıları panoya koyar. Şifreler asla gösterilmez.

## Seçenekler {#options}

Seçenekler menüsü programın ayarlarını tutar. Her biri değiştirdiğiniz anda kaydedilir.

- Kullanılacak medya oynatıcı: bkz. Medya oynatıcı.
- Tercih edilen ses parçası: bkz. Tercih edilen ses parçası.
- Dil: bkz. Dil.
- Sistem tepsisine küçült: bkz. Sistem tepsisi.
- Enter'a basıldığında oynatıcıyı göster: açıkken, kanal oynatmak yerleşik oynatıcı penceresini gösterir. Kapalıyken, oynatma başlar ve odak kanal listesinde kalır.
- Yayın URL'sini göster: ana pencerede bölüm açıklamasından sonra Yayın URL'si alanını ekler.
- Güncellemeleri otomatik denetle: bkz. Güncellemeler.

### Dil {#language}

Seçenekler > Dil, programın dilini seçer. Otomatik, Windows'unuzu ya da masaüstünüzün dilini izler ve çevirisi yoksa İngilizce'yi kullanır. Değişiklik, programı yeniden başlattıktan sonra tam uygulanır.

Program; İngilizce, İspanyolca, Arapça, Brezilya Portekizcesi, Fransızca, Almanca, Rusça, Türkçe, İtalyanca, Lehçe, Hintçe, Basitleştirilmiş Çince, Japonca ve Macarca kullanılabilir. Düzeltmeler ve yeni diller memnuniyetle karşılanır; bkz. Yardım alma.

### Sistem tepsisi {#system-tray}

Seçenekler > Sistem tepsisine küçült açıkken, ana pencereyi kapatmak ya da küçültmek programdan çıkmak yerine onu bildirim alanında gizler; böylece zamanlanmış kayıtlar sürer. Pencereyi geri getirmek için tepsi simgesini etkinleştirin. Menüsünde ayrıca Geri yükle, Oynatıcı denetimleri, bir şey kaydedilirken Kaydı durdur, ve Çıkış vardır.

Programdan tümüyle çıkmak için Dosya > Çıkış (Ctrl+Q) kullanın.

## Güncellemeler {#updates}

Windows'ta program kendini güncelleyebilir. Yardım > Güncellemeleri denetle... şimdi yeni bir sürüm arar; Seçenekler > Güncellemeleri otomatik denetle zaman zaman arka planda denetler.

Güncelleme olduğunda, yenilikler söylenir ve kurulup kurulmayacağı sorulur. İndirme, bir şey kurulmadan önce denetlenir. Program güncelleme sırasında kapanır ve sonunda kendiliğinden yeniden başlar; sonra başarılı olup olmadığını söyler. Ayarlarınız, sık kullanılanlarınız ve kayıtlarınız korunur.

Linux'ta, yeni paketi eskinin üzerine kurun.

## Sorun giderme {#troubleshooting}

- Yardım > Günlük klasörünü aç, programın günlük dosyalarının klasörünü açar; rehber içe aktarmalarının günlüğü ve kayıt başına bir günlük dahil.
- Yardım > Günlüğü ve hata ayıklama bilgilerini kopyala, programın sürümünü, sisteminizi ve güncel günlük satırlarını içeren bir raporu panoya kopyalar; hata raporuna yapıştırmaya hazır. Akış adreslerinizi içerir; sağlayıcı girişinizi barındırabilir. Herkese açık paylaşmadan önce gözden geçirin.

Sık sorunlar:

- Bir kanal oynatmıyor: birçok sağlayıcı hesap başına bir kerede yalnızca bir akışa izin verir. Aynı hesabın diğer oynatmasını, kaydını ya da indirmesini durdurun ve yeniden deneyin.
- Bir kanalın rehberi yok: EPG kaynaklarınızdan birinin onu kapsadığını denetleyin ve rehberi yeniden içe aktarın.
- Oynatma takılıyor: yerleşik oynatıcı arabelleğini kendisi ayarlar. Daha sabırlı bir arabellek için iptvclient.conf içindeki internal_player_buffer_seconds ve internal_player_max_buffer_seconds değerlerini yükseltebilirsiniz.
- Geri izleme programın kullanılabilir olmadığını söylüyor: büyük olasılıkla sağlayıcınızın arşivinden daha eski.

## Klavye kısayolları {#keyboard-shortcuts}

Her yerde:

- F1: kullandığınız şeyle ilgili yardım.

Ana pencere:

- Ctrl+M: Oynatma listesi yöneticisi.
- Ctrl+E: EPG Yöneticisi.
- Ctrl+I: EPG'yi veritabanına aktar.
- Ctrl+W: Şimdi yayında.
- Ctrl+Shift+A: Hesap bilgileri.
- Ctrl+D: seçili kanalı sık kullanılanlara ekleme, ya da kaldırma.
- Delete: seçili kanalı sık kullanılanlardan kaldırma; Sık kullanılanlar kategorisinde.
- Ctrl+Shift+R: seçili kanalın kaydını başlatma ya da durdurma.
- Ctrl+Shift+D: geri izleme indirme pencerelerini gösterme.
- Ctrl+Shift+J: yerleşik oynatıcıyı gösterme.
- Ctrl+Shift+P: yerleşik oynatıcıyı oynatma ya da duraklatma.
- Ctrl+Shift+S: yerleşik oynatıcıyı durdurma.
- Ctrl+Shift+C: yayınlama ya da bağlanma.
- Ctrl+Yukarı ve Ctrl+Aşağı: yerleşik oynatıcının ses düzeyi.
- Enter: seçili kanalı oynatma.
- Uygulamalar tuşu ya da Shift+F10: kanalın menüsü.
- Ctrl+Q: çıkış.

Yerleşik oynatıcı:

- Boşluk: odaklı düğmeye basmak; örneğin Duraklat.
- Ctrl+P: oynatma ya da duraklatma.
- Ctrl+S: durdurma.
- Ctrl+R: kaydetme.
- Yukarı ve Aşağı: ses düzeyi %2 adımlarla; Ctrl ile %5 adımlarla.
- A: sonraki ses parçası.
- D: ses çıkış cihazı.
- Ctrl+C: yayınlama.
- F11: tam ekran; Escape tam ekrandan çıkar.
- Ctrl+W: oynatıcıyı gizleme.
- Ctrl+Q: oynatıcıyı kapatma.

Oynatma listesi yöneticisi ve EPG Yöneticisi'ndeki kaynak listeleri:

- F2: yeniden adlandırma.
- Delete: silme.

## Yardım alma {#support}

Sorular, hata raporları ve sürüm haberleri:

- SerrebiProjects Telegram grubu: https://t.me/SerrebiProjects
- GitHub'da hata raporları ve öneriler: https://github.com/serrebidev/Accessible-IPTV-Client/issues

Yardım > Hakkında..., kullandığınız sürümü gösterir ve ikisine de bağlantı verir. Sorun bildirirken Yardım > Günlüğü ve hata ayıklama bilgilerini kopyala, izlenmesi için gereken ayrıntıları verir.

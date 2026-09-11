<!--
Guida utente di Accessible IPTV Client, in italiano. Il riferimento inglese è
docs/help/en.md. Nota per i traduttori: mantenere gli identificativi
{#topic ID} invariati; tradurre solo il testo dell'intestazione. Una sezione
non ancora tradotta può semplicemente essere omessa; F1 aprirà allora la
sezione in inglese.
-->

# Guida utente di Accessible IPTV Client {#user-guide}

Accessible IPTV Client riproduce televisione in diretta, radio e video on demand da provider IPTV. È costruito per la tastiera e per i lettori di schermo come NVDA, JAWS, Narrator e Orca, e regge playlist e guide ai programmi molto grandi.

Questa guida spiega ogni parte del programma. Premere F1 in un punto qualsiasi del programma per aprirla alla sezione su ciò che si sta usando in quel momento.

## Usare questa guida {#using-help}

La finestra della guida ha quattro parti, in ordine di tabulazione:

- Argomenti: l'elenco delle sezioni. Muoversi con le frecce sposta il testo della guida a quella sezione. Premere Invio per entrare direttamente nel testo.
- Testo della guida: tutta la guida come un unico documento di sola lettura. Leggerlo con le frecce o con il comando di lettura continua del proprio lettore di schermo; selezionare e copiare il testo funziona come in qualsiasi documento.
- Trova: digitare una parola e premere Invio per saltare al punto successivo in cui compare.
- Chiudi.

Tasti nella finestra della guida:

- Ctrl+F: andare al campo Trova.
- F3: trovare la corrispondenza successiva. Shift+F3: trovare la precedente.
- F1: tornare a questa sezione.
- Escape: chiudere la guida e tornare a dove si era.

F1 è sensibile al contesto. Premuto su una voce di menu, in una finestra di dialogo, nel lettore integrato o su un controllo della finestra principale, apre la guida alla sezione su quell'elemento. Dove non è ancora stata scritta una sezione, la guida si apre all'inizio. Aiuto > Guida utente la apre sempre all'inizio.

La guida fa parte del programma, quindi funziona senza connessione a Internet. Viene mostrata nella lingua dell'interfaccia del programma quando esiste una traduzione, altrimenti in inglese.

## Primi passi {#getting-started}

1. Aprire File > Gestione playlist (Ctrl+M) e aggiungere il proprio provider: un file o un indirizzo di playlist M3U, un account Xtream Codes, o un account Stalker Portal. Scegliere OK. I canali si caricano in background.
2. Se il provider fornisce un indirizzo della guida ai programmi (EPG), aggiungerlo in File > Gestione EPG (Ctrl+E). Gli account Xtream Codes possono aggiungerlo per voi.
3. Importare la guida con File > Importa EPG nel database (Ctrl+I). Viene eseguita in background e avvisa quando ha finito.
4. Scegliere una categoria, scegliere un canale e premere Invio per riprodurlo.

Playlist, sorgenti della guida e impostazioni restano tra le sessioni: va fatto solo una volta.

## La finestra principale {#main-window}

La finestra principale è dove si sfogliano e si riproducono i canali. Tab passa tra i controlli in quest'ordine, e Shift+Tab torna indietro:

1. Vista playlist: quale playlist sfogliare.
2. Categorie: i gruppi di canali.
3. Cerca: filtra l'elenco dei canali.
4. Canali: i canali della categoria scelta, o i risultati della ricerca.
5. Descrizione dell'episodio: cosa va in onda ora sul canale evidenziato.
6. URL del flusso: l'indirizzo del canale evidenziato, visibile solo quando Opzioni > Mostra l'URL del flusso è attiva.

Dopo l'ultimo controllo, Tab torna al primo.

Su Linux, i menu descritti da questa guida si trovano sotto il pulsante Menu in alto alla finestra.

### Vista playlist {#playlist-view}

Quando si ha più di una playlist, l'elenco Vista playlist sceglie cosa mostrano categorie e canali: tutte le playlist, o una sola. La scelta viene ricordata.

### Categorie {#categories}

L'elenco delle categorie contiene i gruppi di canali delle playlist. Le sue prime righe sono Tutti i canali e, una volta aggiunti, Preferiti. Ogni riga dice quanti canali contiene.

- Le frecce su e giù scorrono le categorie senza cambiare l'elenco dei canali, così si possono prima ascoltare.
- Invio apre la categoria evidenziata e passa all'elenco dei canali.
- Tab apre la categoria evidenziata e passa al campo Cerca.
- Le frecce sinistra e destra comprono ed espandono una categoria con sottogruppi.

### Ricerca {#search}

Digitare nel campo Cerca per filtrare l'elenco dei canali, poi premere Invio o Tab per applicare il filtro e proseguire. Cercare in Tutti i canali interroga anche la guida ai programmi, quindi una ricerca per titolo di trasmissione può elencare i canali che la trasmettono. Svuotare il campo e premere Invio per rivedere tutta la categoria.

### L'elenco dei canali {#channel-list}

L'elenco dei canali mostra i canali della categoria o ricerca scelta.

- Invio riproduce il canale evidenziato.
- Il tasto applicazioni, Shift+F10 o un clic destro apre il menu del canale: Riproduci, Aggiungi ai preferiti o Rimuovi dai preferiti, Registra o Ferma la registrazione, Programma registrazione, Visualizza EPG…, e Replay per i canali che hanno un archivio.
- Ctrl+D aggiunge il canale ai preferiti o lo rimuove. Nella categoria Preferiti, Canc lo rimuove.
- Ctrl+Shift+R avvia la registrazione del canale; premuto di nuovo, la ferma.

I canali preferiti sono marcati "(Preferito)", e ogni riga nomina anche la trasmissione in onda quando la guida la conosce. Quando una ricerca ha trovato anche trasmissioni, le sue righe nominano la trasmissione e il canale su cui va.

### Descrizione dell'episodio e URL del flusso {#episode-description}

Tab dall'elenco dei canali raggiunge la Descrizione dell'episodio: la trasmissione in onda sul canale evidenziato, con orari e descrizione, e cosa viene dopo. Shift+Tab torna subito all'elenco dei canali. Il testo segue il canale evidenziato.

Quando Opzioni > Mostra l'URL del flusso è attiva, il campo URL del flusso arriva un Tab dopo. Mostra l'indirizzo del canale, utile quando si segnala un problema. La maggior parte lo lascia spento.

## Preferiti {#favorites}

I preferiti tengono in un posto solo i canali che si guardano di più. Premere Ctrl+D su un canale, usare il suo menu, o Visualizza > Aggiungi ai preferiti. I preferiti compaiono nella categoria Preferiti vicina all'inizio dell'elenco delle categorie, e Visualizza > Vai ai preferiti porta lì.

Per togliere un preferito, premere di nuovo Ctrl+D su di esso, o Canc nella categoria Preferiti.

I preferiti sono salvati per provider e canale, non per indirizzo di flusso: sopravvivono quindi a un aggiornamento della playlist. Nulla del proprio account è salvato con loro.

## Video on demand {#video-on-demand}

Visualizza > Video on demand (film && serie) cambia l'elenco delle categorie dai canali in diretta ai film e alle serie del provider. Le categorie si chiamano Movies o Series seguiti dalla categoria del provider. Scegliere una serie elenca i suoi episodi in ordine di stagione ed episodio. Premere Invio per riprodurre un film o un episodio.

Visualizza > TV in diretta && Replay torna ai canali in diretta. Il campo di ricerca si svuota al cambio.

Il video on demand funziona meglio con gli account Xtream Codes, che descrivono bene il loro catalogo. Per le semplici playlist M3U il programma riconosce film e serie dai nomi dei gruppi e dalla numerazione degli episodi.

## Gestione playlist {#playlist-manager}

File > Gestione playlist (Ctrl+M) elenca le sorgenti delle playlist. Si apre con il focus sull'elenco.

- Aggiungi file: una playlist M3U o M3U8 sul computer.
- Aggiungi URL: l'indirizzo Internet di una playlist M3U.
- Aggiungi Xtream Codes: un account Xtream Codes.
- Aggiungi Stalker Portal: un account portale Stalker (MAG).

Su una sorgente dell'elenco, il tasto applicazioni o Shift+F10 apre il suo menu: Copia URL, Rinomina (F2) e Elimina (Canc). Un nome dato a una sorgente è solo un'etichetta; non cambia la sorgente.

Scegliere OK per mantenere le modifiche, o Annulla per scartarle. I canali si ricaricano dopo OK.

### Account Xtream Codes {#xtream-codes}

Un account Xtream Codes richiede l'indirizzo del server, il nome utente e la password, che dà il provider. Il nome è la propria etichetta per l'account. Lasciare spuntata "Aggiungi automaticamente l'URL XMLTV" per aggiungere la guida del provider alla Gestione EPG allo stesso tempo.

Gli account Xtream Codes danno anche video on demand, replay dove il provider lo offre, e lo stato dell'account in File > Informazioni account.

### Account Stalker Portal {#stalker-portal}

Un account Stalker Portal richiede l'indirizzo del portale e l'indirizzo MAC registrato dal provider. Alcuni portali vogliono anche utente e password. "MAC casuale" inventa un nuovo indirizzo MAC, utile solo quando il provider chiede di sceglierne uno. "Prova ad aggiungere l'XMLTV del provider" aggiunge la guida del portale quando ce l'ha.

## Guida ai programmi (EPG) {#epg}

La guida ai programmi, o EPG, dice cosa va in onda su ciascun canale ora e dopo. Proviene da file XMLTV pubblicati dal provider o da un'altra fonte. Il programma li importa in un database locale, e lo usa per la descrizione dell'episodio, In onda ora, Visualizza EPG…, gli elenchi di replay e le ricerche.

### Gestione EPG {#epg-manager}

File > Gestione EPG (Ctrl+E) elenca le sorgenti della guida.

- Aggiungi file: un file XMLTV sul computer (.xml o .xml.gz).
- Aggiungi URL: l'indirizzo Internet di una guida XMLTV.

Il tasto applicazioni o Shift+F10 su una sorgente apre il suo menu: Copia URL, Rinomina (F2) e Elimina (Canc). Scegliere OK per mantenere le modifiche.

### Importare la guida {#import-epg}

File > Importa EPG nel database (Ctrl+I) scarica ogni sorgente della guida e la carica nel database della guida. Va in background, così si può continuare a guardare e sfogliare, e un messaggio avvisa quando ha finito. Le guide grandi possono impiegare diversi minuti.

La guida viene anche rinfrescata automaticamente di tanto in tanto, in silenzio. I canali sono abbinati alla guida dal loro identificativo e dai nomi, incluse le usuali varianti di paese e qualità nei nomi dei canali.

Se una guida importata non compare per un canale, controllare che una delle sorgenti lo copra, poi importare di nuovo. L'importazione scrive un registro dettagliato; vedere Risoluzione dei problemi.

### In onda ora {#whats-on-now}

File > In onda ora (Ctrl+W) elenca ogni trasmissione in onda adesso su tutti i canali, come "trasmissione - canale".

- Digitare lettere salta alla prima trasmissione che inizia con esse.
- Tab passa al campo Filtro; digitare lì restringe l'elenco alle trasmissioni o canali corrispondenti.
- Invio o il pulsante Riproduci riproduce il canale.
- Programma registrazione, o il menu della trasmissione, ne programma la registrazione.
- Escape chiude la finestra.

### Guida del canale (Visualizza EPG) {#channel-epg}

Visualizza EPG…, nel menu di un canale, elenca le trasmissioni di quel canale da quella in onda fino a dove arriva la guida. La trasmissione in onda viene prima.

- Tab alterna tra l'elenco e la descrizione della trasmissione evidenziata.
- Il tasto applicazioni o Shift+F10 su una trasmissione offre Programma registrazione.
- Escape chiude la finestra.

## Replay {#catch-up}

I canali che tengono un archivio permettono di guardare trasmissioni già andate in onda. Questi canali hanno Replay nel loro menu nell'elenco dei canali. Apre la finestra di replay del canale, che elenca le trasmissioni passate con data e ora.

- Le frecce su e giù scorrono le trasmissioni.
- Invio riproduce la trasmissione evidenziata.
- Il tasto applicazioni o Shift+F10 apre il suo menu: Apri, per riprodurla, e Scarica, per salvarla in un file.
- Tab passa alla descrizione della trasmissione e torna.
- Escape chiude la finestra.

Chiudendo il lettore integrato dopo aver guardato una trasmissione in replay, si torna all'elenco dei replay alla stessa trasmissione.

Quanto indietro si possa andare dipende dal provider, di solito pochi giorni.

### Download dei replay {#catch-up-downloads}

Scarica salva una trasmissione in replay nella cartella dei download (vedi Registrazioni), nominata per canale e mandata in onda della trasmissione. Ogni download ha la sua finestra con avanzamento, tempo trascorso, tempo rimanente e dimensione finora, tutto in un campo di sola lettura.

- Escape, o chiudere la finestra, la nasconde; il download continua.
- Visualizza > Mostra download (Ctrl+Shift+D) riporta le finestre di download.
- Annulla ferma il download dopo aver chiesto conferma. Un download annullato non può essere ripreso.

Se un download fallisce, la finestra dice perché e riprova da sola qualche volta quando il problema può essere temporaneo. Molti provider permettono un solo flusso alla volta; fermare altra riproduzione dello stesso account se un download è rifiutato.

## Lettore integrato {#built-in-player}

Il lettore integrato riproduce i canali dentro il programma. Si apre quando si riproduce un canale, salvo che Opzioni > Mostra il lettore con Invio sia spenta; allora la riproduzione parte senza mostrare la finestra.

I suoi controlli, in ordine di tabulazione: Riproduci/Pausa, Ferma, Registra, Trasmetti, Schermo intero, il cursore del Volume e Scegli traccia audio.

Tasti nel lettore:

- Spazio: preme il pulsante con il focus, così su Riproduci/Pausa mette in pausa e riprende.
- Ctrl+P: riprodurre o mettere in pausa.
- Ctrl+S: fermare.
- Ctrl+R: registrare ciò che si guarda, e fermare quella registrazione.
- Frecce su e giù: volume a passi del 2%. Ctrl+Su e Ctrl+Giù: passi del 5%.
- A: traccia audio successiva.
- D: scegliere il dispositivo di uscita audio.
- Ctrl+C: trasmettere a un dispositivo.
- F11: schermo intero acceso o spento. Escape lo lascia.
- Ctrl+W: nascondere la finestra del lettore; la riproduzione continua.
- Ctrl+Q: chiudere il lettore e fermare la riproduzione.

Gli stessi comandi sono nel menu Riproduzione del lettore. Il lettore si riconnette da solo quando un flusso in diretta si interrompe, e mantiene la traccia audio scelta.

### Tracce audio {#audio-tracks}

I canali possono portare più tracce audio, come altre lingue o audiodescrizione. Premere A per passare alla traccia successiva, usare Riproduzione > Traccia audio, o Tab fino a Scegli traccia audio, che nomina sempre la traccia in riproduzione.

Una traccia scelta è ricordata per quel canale e torna la volta successiva. Per sceglierle in automatico vedere Traccia audio preferita.

### Dispositivo di uscita audio {#audio-output-device}

Riproduzione > Dispositivo di uscita audio… (D) sceglie gli altoparlanti o le cuffie che il lettore usa, per esempio per tenere lontano il suono della TV dal proprio lettore di schermo. Predefinito di sistema segue il dispositivo predefinito di Windows. La scelta è ricordata.

### Pilotare il lettore dalla finestra principale {#player-from-main-window}

Il menu Lettore della finestra principale agisce sul lettore integrato senza passarci:

- Mostra lettore integrato: Ctrl+Shift+J.
- Riproduci/Pausa: Ctrl+Shift+P.
- Ferma: Ctrl+Shift+S.
- Trasmetti / Connetti…: Ctrl+Shift+C.
- Ctrl+Su e Ctrl+Giù cambiano il volume.

## Lettore multimediale {#media-player}

Opzioni > Lettore multimediale da usare sceglie cosa riproduce i canali: il Lettore integrato, o un lettore esterno come VLC, MPC, MPC-BE, MPV, PotPlayer, Kodi o SMPlayer. Lettore personalizzato… permette di scegliere qualsiasi altro programma dal suo file.

Registrazione, download di replay e trasmissione funzionano uguale con qualsiasi lettore scelto. Le funzioni della traccia audio e i tasti del lettore descritti in questa guida appartengono al lettore integrato.

## Traccia audio preferita {#preferred-audio-track}

Opzioni > Traccia audio preferita fa scegliere da solo una traccia audio al lettore integrato.

- "Preferisci una traccia di audiodescrizione quando il canale ne ha una" sceglie l'audiodescrizione ovunque sia offerta. Riconosce i nomi che i provider usano davvero in più lingue, come audio description, AD, Audiodeskription e Hörfilm, e la marcatura che i broadcaster mettono su tali tracce.
- Il campo di testo accetta nomi di tracce o lingue, le più volute per prime, separate da virgole, per esempio: audio description, Italian. Lasciato vuoto, resta la traccia con cui un canale parte.

Una traccia scelta a mano nel lettore è ricordata per quel canale e ha la precedenza su queste regole la prossima volta che lo si guarda. L'ultima traccia scelta in qualsiasi posto è usata per i canali dove non ne è mai stata scelta una.

Le registrazioni seguono la stessa scelta. Una registrazione di solo audio tiene l'unica traccia che si sarebbe sentita, e una video tiene tutte le tracce marcando quella come predefinita.

## Registrazioni {#recordings}

Il programma può registrare qualsiasi canale in un file mentre si guarda altro, o senza nulla in riproduzione.

- Registrazioni > Avvia registrazione (Ctrl+Shift+R) registra il canale evidenziato. Premuto di nuovo, si ferma.
- Registra nel menu di un canale fa lo stesso, e Registra nel lettore integrato (Ctrl+R) registra ciò che si sta guardando.
- Registrazioni > Ferma la registrazione ferma la registrazione del canale evidenziato, e Ferma tutte le registrazioni le ferma tutte.
- Registrazioni > Apri cartella delle registrazioni apre la cartella dove i file sono salvati.
- Registrazioni > Imposta cartella download… sceglie quella cartella. I download dei replay vanno lì anch'essi.

Registrare ciò che si guarda nel lettore integrato usa la stessa connessione al provider, quindi funziona anche con account che permettono un solo flusso alla volta.

Fermare una registrazione può richiedere un attimo mentre il file viene concluso. Chiudere il programma lascia che le registrazioni in corso concludano i loro file da sole.

### Formato di registrazione {#recording-formats}

Registrazioni > Formato di registrazione sceglie come sono salvate le registrazioni:

- Qualità del provider (copia, MKV): il flusso esattamente come trasmesso, con tutte le tracce audio e dei sottotitoli. Tutto ciò che il provider manda viene mantenuto.
- Qualità del provider (copia, MP4): la stessa immagine e suono in un file MP4, che più dispositivi riproducono, senza sottotitoli e teletext.
- Ricodifica x264 (MKV o MP4): un file ricodificato più piccolo. Usa molto più tempo di processore.
- Solo audio (MP3 V0, FLAC, WAV, AAC M4A o Opus): solo il suono, utile per la radio.

### Registrazioni programmate {#scheduled-recordings}

Per registrare una trasmissione futura, scegliere Programma registrazione su una trasmissione in Visualizza EPG…, In onda ora o una riga di trasmissione nei risultati della ricerca. Programma registrazione su un canale apre la sua guida per scegliere prima la trasmissione.

Registrazioni > Registrazioni programmate… elenca ogni registrazione programmata, in corso e conclusa con orario, titolo, canale, stato e formato.

- Il tasto applicazioni o Shift+F10 su una registrazione apre il suo menu: Aggiorna, Annulla ed Elimina.
- Elimina toglie la registrazione evidenziata dall'elenco; una in corso viene prima fermata dopo aver chiesto.
- Escape chiude la finestra.

Le registrazioni programmate partono da sole mentre il programma gira, anche minimizzato nella barra delle applicazioni.

### Margine di programmazione {#schedule-padding}

Le trasmissioni raramente iniziano e finiscono esattamente in orario. Registrazioni > Margine di programmazione… fissa quanti minuti prima di una trasmissione parte una registrazione programmata, e quanti minuti dopo la sua fine continua a registrare. Le registrazioni manuali non sono toccate.

### Spegnere dopo le registrazioni {#shutdown-after-recordings}

Registrazioni > Spegni il computer al termine delle registrazioni spegne il computer quando ogni registrazione in corso e programmata è conclusa, utile per una registrazione notturna.

Non scatta mai mentre qualcosa sta ancora registrando o aspetta in coda. Arrivato il momento, una finestra conter alla rovescia 60 secondi; il focus è su Annulla spegnimento, così Invio o Escape la fermano, e Spegni ora non aspetta. L'opzione si spegne da sola una volta usata o annullata.

## Trasmissione {#casting}

La trasmissione manda un canale a una TV o un altoparlante della propria rete: dispositivi Chromecast, renderer DLNA e UPnP, e dispositivi AirPlay come Apple TV e HomePod.

File > Trasmetti a… esplora la rete ed elenca i dispositivi trovati. Scegliere un dispositivo e Connetti. Alcuni dispositivi AirPlay chiedono prima Associa…, che richiede il codice mostrato sulla TV. Una volta connesso, riprodurre un canale lo manda al dispositivo. Scegliere di nuovo Trasmetti a… disconnette.

Il pulsante Trasmetti del lettore integrato, Lettore > Trasmetti / Connetti… (Ctrl+Shift+C) e Ctrl+C nel lettore fanno lo stesso.

Per la trasmissione, il computer e il dispositivo devono essere sulla stessa rete.

## Informazioni account {#account-info}

File > Informazioni account (Ctrl+Shift+A) mostra lo stato degli account Xtream Codes e Stalker Portal: se l'account è attivo, la sua data di scadenza e i giorni restanti, se è di prova, e quante connessioni permette e ha aperte. Gli account trovati negli indirizzi delle playlist sono elencati anch'essi.

Scegliere un account nell'elenco; i suoi dettagli compaiono nel campo di sola lettura sotto. Aggiorna richiede di nuovo al provider, e Copia dettagli mette i dettagli negli appunti. Le password non sono mai mostrate.

## Opzioni {#options}

Il menu Opzioni contiene le impostazioni del programma. Ognuna è salvata appena la si cambia.

- Lettore multimediale da usare: vedere Lettore multimediale.
- Traccia audio preferita: vedere Traccia audio preferita.
- Lingua: vedere Lingua.
- Riduci a icona nella barra delle applicazioni: vedere Barra delle applicazioni.
- Mostra il lettore con Invio: attiva, riprodurre un canale mostra la finestra del lettore integrato. Spenta, la riproduzione parte e il focus resta nell'elenco dei canali.
- Mostra l'URL del flusso: aggiunge il campo URL del flusso dopo la descrizione dell'episodio nella finestra principale.
- Controlla automaticamente gli aggiornamenti: vedere Aggiornamenti.

### Lingua {#language}

Opzioni > Lingua sceglie la lingua del programma. Automatico segue la lingua di Windows o del desktop e usa l'inglese quando non c'è traduzione. Il cambio si applica completamente dopo il riavvio del programma.

Il programma è disponibile in inglese, spagnolo, arabo, portoghese brasiliano, francese, tedesco, russo, turco, italiano, polacco, hindi, cinese semplificato, giapponese e ungherese. Correzioni e nuove lingue sono benvenute; vedere Ottenere aiuto.

### Barra delle applicazioni {#system-tray}

Quando Opzioni > Riduci a icona nella barra delle applicazioni è attiva, chiudere o minimizzare la finestra principale la nasconde nell'area di notifica invece di uscire, così le registrazioni programmate continuano. Attivare l'icona della barra per riportare la finestra. Il suo menu ha anche Ripristina, Controlli del lettore, Ferma registrazione(i) mentre qualcosa registra, ed Esci.

Per uscire del tutto dal programma, usare File > Esci (Ctrl+Q).

## Aggiornamenti {#updates}

Su Windows il programma può aggiornarsi da solo. Aiuto > Controlla aggiornamenti… cerca ora una nuova versione, e Opzioni > Controlla automaticamente gli aggiornamenti controlla in background di tanto in tanto.

Quando c'è un aggiornamento, si dice cosa c'è di nuovo e si chiede se installarlo. Il download è controllato prima di installare qualsiasi cosa. Il programma si chiude durante l'aggiornamento e riparte da solo alla fine, poi dice se è riuscito. Impostazioni, preferiti e registrazioni sono conservati.

Su Linux, installare il nuovo pacchetto sopra il vecchio.

## Risoluzione dei problemi {#troubleshooting}

- Aiuto > Apri cartella dei registri apre la cartella con i file di registro del programma, incluso il registro delle importazioni della guida e un registro per registrazione.
- Aiuto > Copia registro e informazioni di debug copia negli appunti un rapporto con la versione del programma, il sistema e righe di registro recenti, pronto da incollare in una segnalazione di errore. Contiene gli indirizzi dei flussi, che possono includere l'accesso del provider; controllarlo prima di condividerlo pubblicamente.

Problemi comuni:

- Un canale non si riproduce: molti provider permettono un solo flusso per account alla volta. Fermare altra riproduzione, registrazione o download dello stesso account e riprovare.
- Un canale non ha la guida: controllare che una delle sorgenti EPG lo copra, e importare di nuovo la guida.
- La riproduzione scatta: il lettore integrato regola da solo il suo buffer. Si possono alzare internal_player_buffer_seconds e internal_player_max_buffer_seconds in iptvclient.conf per un buffer più paziente.
- Il replay dice che la trasmissione non è disponibile: probabilmente è più vecchia dell'archivio del provider.

## Scorciatoie da tastiera {#keyboard-shortcuts}

Ovunque:

- F1: aiuto su ciò che si sta usando.

Finestra principale:

- Ctrl+M: Gestione playlist.
- Ctrl+E: Gestione EPG.
- Ctrl+I: Importa EPG nel database.
- Ctrl+W: In onda ora.
- Ctrl+Shift+A: Informazioni account.
- Ctrl+D: aggiungere il canale selezionato ai preferiti, o toglierlo.
- Canc: togliere il canale selezionato dai preferiti, nella categoria Preferiti.
- Ctrl+Shift+R: avviare o fermare la registrazione del canale selezionato.
- Ctrl+Shift+D: mostrare le finestre di download dei replay.
- Ctrl+Shift+J: mostrare il lettore integrato.
- Ctrl+Shift+P: riprodurre o mettere in pausa il lettore integrato.
- Ctrl+Shift+S: fermare il lettore integrato.
- Ctrl+Shift+C: trasmettere o connettere.
- Ctrl+Su e Ctrl+Giù: volume del lettore integrato.
- Invio: riprodurre il canale selezionato.
- Tasto applicazioni o Shift+F10: il menu del canale.
- Ctrl+Q: uscire.

Lettore integrato:

- Spazio: premere il pulsante con il focus, come Pausa.
- Ctrl+P: riprodurre o mettere in pausa.
- Ctrl+S: fermare.
- Ctrl+R: registrare.
- Su e Giù: volume a passi del 2%; con Ctrl, passi del 5%.
- A: traccia audio successiva.
- D: dispositivo di uscita audio.
- Ctrl+C: trasmettere.
- F11: schermo intero; Escape lo lascia.
- Ctrl+W: nascondere il lettore.
- Ctrl+Q: chiudere il lettore.

Elenchi delle sorgenti nella Gestione playlist e nella Gestione EPG:

- F2: rinominare.
- Canc: eliminare.

## Ottenere aiuto {#support}

Domande, segnalazioni di errori e notizie delle versioni:

- Il gruppo Telegram SerrebiProjects: https://t.me/SerrebiProjects
- Segnalazioni di errori e suggerimenti su GitHub: https://github.com/serrebidev/Accessible-IPTV-Client/issues

Aiuto > Informazioni… mostra la versione in uso e collega entrambi. Quando si segnala un problema, Aiuto > Copia registro e informazioni di debug dà i dettagli necessari per trovarlo.

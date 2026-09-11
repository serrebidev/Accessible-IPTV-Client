<!--
Guide de l'utilisateur d'Accessible IPTV Client, en français. La référence
anglaise se trouve dans docs/help/en.md. Note aux traducteurs : conserver les
identifiants {#topic ID} tels quels ; ne traduire que le texte du titre. Une
section pas encore traduite peut simplement être omise ; F1 ouvrira alors la
section anglaise.
-->

# Guide de l'utilisateur d'Accessible IPTV Client {#user-guide}

Accessible IPTV Client lit la télévision en direct, la radio et la vidéo à la demande de fournisseurs IPTV. Il est conçu pour le clavier et pour les lecteurs d'écran tels que NVDA, JAWS, Narrator et Orca, et il gère des listes de lecture et des guides de programmes très volumineux.

Ce guide explique chaque partie du programme. Appuyez sur F1 n'importe où dans le programme pour l'ouvrir à la section sur ce que vous utilisez à ce moment-là.

## Utiliser ce guide {#using-help}

La fenêtre du guide comporte quatre parties, dans l'ordre de tabulation :

- Rubriques : la liste des sections. S'y déplacer avec les flèches déplace le texte du guide vers cette section. Appuyez sur Entrée pour entrer directement dans le texte.
- Texte du guide : tout le guide en un seul document en lecture seule. Lisez-le avec les flèches ou avec la commande de lecture continue de votre lecteur d'écran ; sélectionner et copier du texte fonctionne comme dans n'importe quel document.
- Rechercher : tapez un mot et appuyez sur Entrée pour sauter à l'endroit suivant où il apparaît.
- Fermer.

Touches dans la fenêtre du guide :

- Ctrl+F : aller au champ Rechercher.
- F3 : trouver l'occurrence suivante. Shift+F3 : trouver l'occurrence précédente.
- F1 : revenir à cette section.
- Échap : fermer le guide et revenir à l'endroit d'où vous venez.

F1 est contextuel. Appuyé sur un élément de menu, dans une boîte de dialogue, dans le lecteur intégré ou sur un contrôle de la fenêtre principale, il ouvre le guide à la section sur cet élément. Là où aucune section n'a encore été écrite, le guide s'ouvre à son début. Aide > Guide de l'utilisateur l'ouvre toujours au début.

Le guide fait partie du programme ; il fonctionne donc sans connexion Internet. Il s'affiche dans la langue de l'interface du programme lorsqu'une traduction existe, sinon en anglais.

## Premiers pas {#getting-started}

1. Ouvrez Fichier > Gestionnaire de listes de lecture (Ctrl+M) et ajoutez votre fournisseur : un fichier ou une adresse de liste M3U, un compte Xtream Codes, ou un compte Stalker Portal. Choisissez OK. Les chaînes se chargent en arrière-plan.
2. Si votre fournisseur vous donne une adresse de guide de programmes (EPG), ajoutez-la dans Fichier > Gestionnaire EPG (Ctrl+E). Les comptes Xtream Codes peuvent l'ajouter pour vous.
3. Importez le guide avec Fichier > Importer l'EPG dans la base de données (Ctrl+I). Cela s'exécute en arrière-plan et vous prévient une fois terminé.
4. Choisissez une catégorie, choisissez une chaîne et appuyez sur Entrée pour la lire.

Vos listes de lecture, sources de guide et réglages sont conservés entre les sessions ; il ne faut donc le faire qu'une seule fois.

## La fenêtre principale {#main-window}

La fenêtre principale est l'endroit où vous parcourez les chaînes et les lisez. Tab parcourt ses contrôles dans cet ordre, et Shift+Tab revient en arrière :

1. Vue de la liste de lecture : quelle liste parcourir.
2. Catégories : les groupes de chaînes.
3. Rechercher : filtre la liste des chaînes.
4. Chaînes : les chaînes de la catégorie choisie, ou les résultats de recherche.
5. Description de l'épisode : ce qui passe maintenant sur la chaîne surlignée.
6. URL du flux : l'adresse de la chaîne surlignée, affichée uniquement si Options > Afficher l'URL du flux est activé.

Après le dernier contrôle, Tab revient au premier.

Sous Linux, les menus que décrit ce guide se trouvent sous le bouton Menu en haut de la fenêtre.

### Vue de la liste de lecture {#playlist-view}

Quand vous avez plusieurs listes de lecture, la liste Vue de la liste de lecture choisit ce que les catégories et les chaînes affichent : toutes les listes, ou une seule. Votre choix est mémorisé.

### Catégories {#categories}

La liste des catégories contient les groupes de chaînes de vos listes. Ses premières lignes sont Toutes les chaînes puis, une fois que vous en avez ajouté, Favoris. Chaque ligne indique combien de chaînes elle contient.

- Les flèches haut et bas parcourent les catégories sans changer la liste des chaînes, pour que vous puissiez d'abord les écouter.
- Entrée ouvre la catégorie surlignée et passe à la liste des chaînes.
- Tab ouvre la catégorie surlignée et passe au champ Rechercher.
- Les flèches gauche et droite replient et déplient une catégorie qui a des sous-groupes.

### Recherche {#search}

Tapez dans le champ Rechercher pour filtrer la liste des chaînes, puis appuyez sur Entrée ou Tab pour appliquer le filtre et continuer. Chercher dans Toutes les chaînes interroge aussi le guide de programmes ; une recherche sur le titre d'une émission peut donc lister les chaînes qui la diffusent. Videz le champ et appuyez sur Entrée pour revoir toute la catégorie.

### La liste des chaînes {#channel-list}

La liste des chaînes affiche les chaînes de la catégorie ou de la recherche choisie.

- Entrée lit la chaîne surlignée.
- La touche Applications, Shift+F10 ou un clic droit ouvre le menu de la chaîne : Lire, Ajouter aux favoris ou Retirer des favoris, Enregistrer ou Arrêter l'enregistrement, Programmer l'enregistrement, Afficher l'EPG…, et Rattrapage pour les chaînes qui ont une archive.
- Ctrl+D ajoute la chaîne aux favoris ou la retire. Dans la catégorie Favoris, Suppr la retire.
- Ctrl+Shift+R démarre l'enregistrement de la chaîne ; appuyé de nouveau, il l'arrête.

Les chaînes favorites sont marquées « (Favori) », et chaque ligne nomme aussi l'émission à l'antenne quand le guide la connaît. Quand une recherche a aussi trouvé des émissions, ses lignes nomment l'émission et la chaîne qui la diffuse.

### Description de l'épisode et URL du flux {#episode-description}

Tab depuis la liste des chaînes atteint la Description de l'épisode : l'émission à l'antenne sur la chaîne surlignée, avec ses horaires et sa description, et ce qui vient ensuite. Shift+Tab revient directement à la liste des chaînes. Le texte suit la chaîne surlignée.

Quand Options > Afficher l'URL du flux est activé, le champ URL du flux arrive un Tab plus loin. Il montre l'adresse de la chaîne, utile pour signaler un problème. La plupart des gens le laissent désactivé.

## Favoris {#favorites}

Les favoris gardent au même endroit les chaînes que vous regardez le plus. Appuyez sur Ctrl+D sur une chaîne, utilisez son menu, ou Affichage > Ajouter aux favoris. Les favoris apparaissent dans la catégorie Favoris près du haut de la liste des catégories, et Affichage > Aller aux favoris vous y conduit.

Pour retirer un favori, appuyez de nouveau sur Ctrl+D dessus, ou sur Suppr dans la catégorie Favoris.

Les favoris sont stockés par fournisseur et chaîne, pas par adresse de flux ; ils survivent donc à une actualisation de la liste. Rien sur votre compte n'est stocké avec eux.

## Vidéo à la demande {#video-on-demand}

Affichage > Vidéo à la demande (films && séries) bascule la liste des catégories des chaînes en direct vers les films et séries de votre fournisseur. Les catégories s'appellent Movies ou Series suivis de la catégorie du fournisseur. Choisir une série liste ses épisodes dans l'ordre des saisons et des épisodes. Appuyez sur Entrée pour lire un film ou un épisode.

Affichage > TV en direct && Rattrapage revient aux chaînes en direct. Le champ de recherche se vide au changement.

La vidéo à la demande fonctionne mieux avec les comptes Xtream Codes, qui décrivent correctement leur catalogue. Pour les simples listes M3U, le programme reconnaît les films et les séries d'après leurs noms de groupe et leur numérotation d'épisodes.

## Gestionnaire de listes de lecture {#playlist-manager}

Fichier > Gestionnaire de listes de lecture (Ctrl+M) liste vos sources de listes de lecture. Il s'ouvre avec le focus sur la liste.

- Ajouter un fichier : une liste M3U ou M3U8 sur votre ordinateur.
- Ajouter une URL : l'adresse Internet d'une liste M3U.
- Ajouter Xtream Codes : un compte Xtream Codes.
- Ajouter un Stalker Portal : un compte portail Stalker (MAG).

Sur une source de la liste, la touche Applications ou Shift+F10 ouvre son menu : Copier l'URL, Renommer (F2) et Supprimer (Suppr). Un nom que vous donnez à une source n'est qu'une étiquette ; il ne change pas la source.

Choisissez OK pour conserver vos modifications, ou Annuler pour les abandonner. Les chaînes se rechargent après OK.

### Comptes Xtream Codes {#xtream-codes}

Un compte Xtream Codes a besoin de l'adresse du serveur, de votre nom d'utilisateur et de votre mot de passe, que votre fournisseur vous donne. Le nom est votre propre étiquette pour le compte. Laissez cochée « Ajouter automatiquement l'URL XMLTV » pour ajouter le guide du fournisseur au Gestionnaire EPG en même temps.

Les comptes Xtream Codes vous donnent aussi la vidéo à la demande, le rattrapage là où le fournisseur l'offre, et l'état du compte sous Fichier > Informations du compte.

### Comptes Stalker Portal {#stalker-portal}

Un compte Stalker Portal a besoin de l'adresse du portail et de l'adresse MAC que votre fournisseur a enregistrée pour vous. Certains portails veulent aussi un nom d'utilisateur et un mot de passe. « Générer une MAC aléatoire » invente une nouvelle adresse MAC, utile seulement quand le fournisseur vous demande d'en choisir une. « Tenter d'ajouter le XMLTV du fournisseur » ajoute le guide du portail quand il en a un.

## Guide de programmes (EPG) {#epg}

Le guide de programmes, l'EPG, vous dit ce qui passe sur chaque chaîne maintenant et plus tard. Il provient de fichiers XMLTV publiés par votre fournisseur ou une autre source. Le programme les importe dans une base de données locale, puis l'utilise pour la description de l'épisode, À l'affiche maintenant, Afficher l'EPG…, les listes de rattrapage et les recherches.

### Gestionnaire EPG {#epg-manager}

Fichier > Gestionnaire EPG (Ctrl+E) liste vos sources de guide.

- Ajouter un fichier : un fichier XMLTV sur votre ordinateur (.xml ou .xml.gz).
- Ajouter une URL : l'adresse Internet d'un guide XMLTV.

La touche Applications ou Shift+F10 sur une source ouvre son menu : Copier l'URL, Renommer (F2) et Supprimer (Suppr). Choisissez OK pour conserver vos modifications.

### Importer le guide {#import-epg}

Fichier > Importer l'EPG dans la base de données (Ctrl+I) télécharge chaque source de guide et la charge dans la base de données du guide. Cela s'exécute en arrière-plan ; vous pouvez continuer à regarder et à parcourir, et un message vous prévient à la fin. Les grands guides peuvent prendre plusieurs minutes.

Le guide est aussi rafraîchi automatiquement de temps en temps, en silence. Les chaînes sont rapprochées du guide par leur identifiant et leurs noms, y compris les variantes habituelles de pays et de qualité dans les noms de chaînes.

Si un guide importé n'apparaît pas pour une chaîne, vérifiez qu'une de vos sources la couvre, puis importez à nouveau. L'importation écrit un journal détaillé ; voir Dépannage.

### À l'affiche maintenant {#whats-on-now}

Fichier > À l'affiche maintenant (Ctrl+W) liste chaque émission à l'antenne en ce moment sur toutes les chaînes, sous la forme « émission - chaîne ».

- Taper des lettres saute à la première émission qui commence par elles.
- Tab passe au champ Filtre ; y taper resserre la liste sur les émissions ou chaînes correspondantes.
- Entrée ou le bouton Lire lit la chaîne.
- Programmer l'enregistrement, ou le menu de l'émission, programme son enregistrement.
- Échap ferme la fenêtre.

### Guide de la chaîne (Afficher l'EPG) {#channel-epg}

Afficher l'EPG…, dans le menu d'une chaîne, liste les émissions de cette chaîne de celle à l'antenne jusqu'où va le guide. L'émission à l'antenne vient en premier.

- Tab alterne entre la liste et la description de l'émission surlignée.
- La touche Applications ou Shift+F10 sur une émission propose Programmer l'enregistrement.
- Échap ferme la fenêtre.

## Rattrapage {#catch-up}

Les chaînes qui tiennent une archive permettent de regarder des émissions déjà diffusées. Ces chaînes ont Rattrapage dans leur menu de la liste des chaînes. Il ouvre la fenêtre de rattrapage de la chaîne, qui liste ses émissions passées avec date et heure.

- Les flèches haut et bas parcourent les émissions.
- Entrée lit l'émission surlignée.
- La touche Applications ou Shift+F10 ouvre son menu : Ouvrir, pour la lire, et Télécharger, pour l'enregistrer en fichier.
- Tab passe à la description de l'émission et revient.
- Échap ferme la fenêtre.

Quand vous fermez le lecteur intégré après avoir regardé une émission de rattrapage, vous revenez à la liste de rattrapage à la même émission.

Jusqu'où vous pouvez remonter dépend de votre fournisseur, en général quelques jours.

### Téléchargements de rattrapage {#catch-up-downloads}

Télécharger enregistre une émission de rattrapage dans votre dossier de téléchargement (voir Enregistrements), nommée d'après la chaîne et la diffusion de l'émission. Chaque téléchargement a sa propre fenêtre avec la progression, le temps écoulé, le temps restant et la taille actuelle, tout dans un champ en lecture seule.

- Échap, ou fermer la fenêtre, la cache ; le téléchargement continue.
- Affichage > Afficher les téléchargements (Ctrl+Shift+D) ramène les fenêtres de téléchargement.
- Annuler arrête le téléchargement après vous avoir demandé confirmation. Un téléchargement annulé ne peut pas être repris.

Si un téléchargement échoue, la fenêtre dit pourquoi et réessaie automatiquement quelques fois quand le problème peut être passager. Beaucoup de fournisseurs n'autorisent qu'un flux à la fois ; arrêtez les autres lectures du même compte si un téléchargement est refusé.

## Lecteur intégré {#built-in-player}

Le lecteur intégré lit les chaînes à l'intérieur du programme. Il s'ouvre quand vous lisez une chaîne, sauf si Options > Afficher le lecteur avec Entrée est désactivé ; la lecture démarre alors sans montrer la fenêtre.

Ses contrôles, dans l'ordre de tabulation : Lecture/Pause, Arrêter, Enregistrer, Diffuser, Plein écran, le curseur de Volume et Choisir la piste audio.

Touches du lecteur :

- Espace : appuie sur le bouton ayant le focus, donc sur Lecture/Pause, met en pause et reprend.
- Ctrl+P : lire ou mettre en pause.
- Ctrl+S : arrêter.
- Ctrl+R : enregistrer ce que vous regardez, puis arrêter cet enregistrement.
- Flèches haut et bas : volume par pas de 2 %. Ctrl+Haut et Ctrl+Bas : pas de 5 %.
- A : piste audio suivante.
- D : choisir le périphérique de sortie audio.
- Ctrl+C : diffuser vers un appareil.
- F11 : plein écran activé ou désactivé. Échap quitte le plein écran.
- Ctrl+W : masquer la fenêtre du lecteur ; la lecture continue.
- Ctrl+Q : fermer le lecteur et arrêter la lecture.

Les mêmes commandes se trouvent dans le menu Lecture du lecteur. Le lecteur se reconnecte tout seul quand un flux en direct se coupe, et garde la piste audio que vous avez choisie.

### Pistes audio {#audio-tracks}

Les chaînes peuvent porter plusieurs pistes audio, comme d'autres langues ou l'audiodescription. Appuyez sur A pour passer à la piste suivante, utilisez Lecture > Piste audio, ou Tab jusqu'à Choisir la piste audio, qui nomme toujours la piste en lecture.

Une piste choisie est mémorisée pour cette chaîne et revient la prochaine fois. Pour les choisir automatiquement, voir Piste audio préférée.

### Périphérique de sortie audio {#audio-output-device}

Lecture > Périphérique de sortie audio… (D) choisit les haut-parleurs ou le casque que le lecteur utilise, par exemple pour éloigner le son du téléviseur de votre lecteur d'écran. Par défaut du système suit le périphérique par défaut de Windows. Le choix est mémorisé.

### Piloter le lecteur depuis la fenêtre principale {#player-from-main-window}

Le menu Lecteur de la fenêtre principale agit sur le lecteur intégré sans basculer vers lui :

- Afficher le lecteur intégré : Ctrl+Shift+J.
- Lecture/Pause : Ctrl+Shift+P.
- Arrêter : Ctrl+Shift+S.
- Diffuser / Connecter… : Ctrl+Shift+C.
- Ctrl+Haut et Ctrl+Bas changent le volume.

## Lecteur multimédia {#media-player}

Options > Lecteur multimédia à utiliser choisit ce qui lit vos chaînes : le Lecteur intégré, ou un lecteur externe comme VLC, MPC, MPC-BE, MPV, PotPlayer, Kodi ou SMPlayer. Lecteur personnalisé… permet de choisir n'importe quel autre programme par son fichier.

L'enregistrement, les téléchargements de rattrapage et la diffusion fonctionnent pareil quel que soit le lecteur choisi. Les fonctions de piste audio et les touches du lecteur décrites dans ce guide appartiennent au lecteur intégré.

## Piste audio préférée {#preferred-audio-track}

Options > Piste audio préférée fait choisir une piste audio par le lecteur intégré lui-même.

- « Préférer une piste d'audiodescription lorsque la chaîne en propose une » choisit l'audiodescription partout où elle est offerte. Il reconnaît les noms que les fournisseurs utilisent réellement en plusieurs langues, comme audio description, AD, Audiodeskription et Hörfilm, ainsi que le marquage que les diffuseurs posent sur ces pistes.
- Le champ de texte accepte des noms de pistes ou des langues, les plus voulus en premier, séparés par des virgules, par exemple : audio description, French. Laissez-le vide pour garder la piste avec laquelle une chaîne démarre.

Une piste choisie à la main dans le lecteur est mémorisée pour cette chaîne et prime sur ces règles la prochaine fois que vous la regardez. La dernière piste choisie n'importe où sert pour les chaînes où vous n'en avez jamais choisi.

Les enregistrements suivent le même choix. Un enregistrement audio seul garde l'unique piste que vous auriez entendue, et un enregistrement vidéo garde toutes les pistes en marquant celle-ci par défaut.

## Enregistrements {#recordings}

Le programme peut enregistrer n'importe quelle chaîne dans un fichier pendant que vous regardez autre chose, ou sans rien lire du tout.

- Enregistrements > Démarrer l'enregistrement (Ctrl+Shift+R) enregistre la chaîne surlignée. Appuyé de nouveau, il s'arrête.
- Enregistrer dans le menu d'une chaîne fait pareil, et Enregistrer dans le lecteur intégré (Ctrl+R) enregistre ce que vous regardez.
- Enregistrements > Arrêter l'enregistrement arrête l'enregistrement de la chaîne surlignée, et Arrêter tous les enregistrements les arrête tous.
- Enregistrements > Ouvrir le dossier des enregistrements ouvre le dossier où les fichiers sont enregistrés.
- Enregistrements > Définir le dossier de téléchargement… choisit ce dossier. Les téléchargements de rattrapage y vont aussi.

Enregistrer ce que vous regardez dans le lecteur intégré utilise la même connexion au fournisseur ; cela fonctionne donc même avec les comptes qui n'autorisent qu'un flux à la fois.

Arrêter un enregistrement peut prendre un moment pendant que le fichier se finalise. Fermer le programme laisse les enregistrements en cours finir leurs fichiers d'eux-mêmes.

### Format d'enregistrement {#recording-formats}

Enregistrements > Format d'enregistrement choisit comment les enregistrements sont sauvegardés :

- Qualité du fournisseur (copie, MKV) : le flux exactement tel que diffusé, avec toutes les pistes audio et de sous-titres. Garde tout ce que le fournisseur envoie.
- Qualité du fournisseur (copie, MP4) : la même image et le même son dans un fichier MP4, que plus d'appareils lisent, sans sous-titres ni télétexte.
- Réencodage x264 (MKV ou MP4) : un fichier réencodé plus petit. Utilise beaucoup plus de temps processeur.
- Audio seulement (MP3 V0, FLAC, WAV, AAC M4A ou Opus) : le son seul, utile pour la radio.

### Enregistrements programmés {#scheduled-recordings}

Pour enregistrer une émission à venir, choisissez Programmer l'enregistrement sur une émission dans Afficher l'EPG…, À l'affiche maintenant ou une ligne d'émission dans les résultats de recherche. Programmer l'enregistrement sur une chaîne ouvre son guide pour que vous choisissiez d'abord l'émission.

Enregistrements > Enregistrements programmés… liste chaque enregistrement programmé, en cours et terminé avec son heure, son titre, sa chaîne, son état et son format.

- La touche Applications ou Shift+F10 sur un enregistrement ouvre son menu : Actualiser, Annuler et Supprimer.
- Supprimer retire l'enregistrement surligné de la liste ; un enregistrement en cours est d'abord arrêté après vous avoir demandé.
- Échap ferme la fenêtre.

Les enregistrements programmés démarrent tout seuls pendant que le programme tourne, même réduit dans la barre d'état système.

### Marge de programmation {#schedule-padding}

Les émissions commencent et finissent rarement exactement à l'heure. Enregistrements > Marge de programmation… fixe combien de minutes avant une émission un enregistrement programmé commence, et combien de minutes après sa fin il continue d'enregistrer. Les enregistrements manuels ne sont pas concernés.

### Éteindre après les enregistrements {#shutdown-after-recordings}

Enregistrements > Éteindre l'ordinateur à la fin des enregistrements éteint l'ordinateur une fois que chaque enregistrement en cours et programmé est terminé, utile pour un enregistrement de fin de soirée.

Il ne se déclenche jamais tant que quelque chose enregistre encore ou attend dans le planning. Le moment venu, une fenêtre décompte 60 secondes ; le focus est sur Annuler l'extinction, donc Entrée ou Échap l'arrête, et Éteindre maintenant n'attend pas. L'option se désactive toute seule une fois utilisée ou annulée.

## Diffusion {#casting}

La diffusion envoie une chaîne vers un téléviseur ou une enceinte de votre réseau : appareils Chromecast, rendereurs DLNA et UPnP, et appareils AirPlay comme Apple TV et HomePod.

Fichier > Diffuser vers… analyse votre réseau et liste les appareils trouvés. Choisissez un appareil puis Connecter. Certains appareils AirPlay demandent d'abord Appairer…, qui réclame le code affiché sur le téléviseur. Une fois connecté, la lecture d'une chaîne l'envoie vers l'appareil. Choisir de nouveau Diffuser vers… déconnecte.

Le bouton Diffuser du lecteur intégré, Lecteur > Diffuser / Connecter… (Ctrl+Shift+C) et Ctrl+C dans le lecteur font pareil.

Pour la diffusion, l'ordinateur et l'appareil doivent être sur le même réseau.

## Informations du compte {#account-info}

Fichier > Informations du compte (Ctrl+Shift+A) montre l'état de vos comptes Xtream Codes et Stalker Portal : si le compte est actif, sa date d'expiration et les jours restants, s'il s'agit d'un essai, et combien de connexions il autorise et a ouvertes. Les comptes trouvés dans des adresses de listes sont aussi listés.

Choisissez un compte dans la liste ; ses détails apparaissent dans le champ en lecture seule en dessous. Actualiser redemande au fournisseur, et Copier les détails met les détails dans le presse-papiers. Les mots de passe ne sont jamais montrés.

## Options {#options}

Le menu Options contient les réglages du programme. Chacun est sauvegardé dès que vous le modifiez.

- Lecteur multimédia à utiliser : voir Lecteur multimédia.
- Piste audio préférée : voir Piste audio préférée.
- Langue : voir Langue.
- Réduire dans la barre d'état système : voir Barre d'état système.
- Afficher le lecteur avec Entrée : activé, lire une chaîne montre la fenêtre du lecteur intégré. Désactivé, la lecture démarre et le focus reste dans la liste des chaînes.
- Afficher l'URL du flux : ajoute le champ URL du flux après la description de l'épisode dans la fenêtre principale.
- Vérifier automatiquement les mises à jour : voir Mises à jour.

### Langue {#language}

Options > Langue choisit la langue du programme. Automatique suit votre langue Windows ou du bureau et utilise l'anglais quand il n'y a pas de traduction pour elle. Le changement s'applique complètement après un redémarrage du programme.

Le programme est disponible en anglais, espagnol, arabe, portugais du Brésil, français, allemand, russe, turc, italien, polonais, hindi, chinois simplifié, japonais et hongrois. Les corrections et les nouvelles langues sont bienvenues ; voir Obtenir de l'aide.

### Barre d'état système {#system-tray}

Quand Options > Réduire dans la barre d'état système est activé, fermer ou réduire la fenêtre principale la cache dans la zone de notification au lieu de quitter, ainsi les enregistrements programmés continuent. Activez l'icône de la barre pour ramener la fenêtre. Son menu a aussi Restaurer, Commandes du lecteur, Arrêter l'(les) enregistrement(s) pendant qu'un enregistrement tourne, et Quitter.

Pour quitter complètement le programme, utilisez Fichier > Quitter (Ctrl+Q).

## Mises à jour {#updates}

Sous Windows, le programme peut se mettre à jour lui-même. Aide > Vérifier les mises à jour… cherche une nouvelle version maintenant, et Options > Vérifier automatiquement les mises à jour vérifie en arrière-plan de temps en temps.

Quand une mise à jour est disponible, on vous dit ce qui est nouveau et on vous demande si vous voulez l'installer. Le téléchargement est vérifié avant que quoi que ce soit soit installé. Le programme se ferme pendant la mise à jour et redémarre tout seul à la fin, puis vous dit si elle a réussi. Vos réglages, favoris et enregistrements sont conservés.

Sous Linux, installez plutôt le nouveau paquet par-dessus l'ancien.

## Dépannage {#troubleshooting}

- Aide > Ouvrir le dossier des journaux ouvre le dossier avec les fichiers journaux du programme, y compris le journal des importations de guide et un journal par enregistrement.
- Aide > Copier le journal et les informations de débogage copie un rapport avec la version du programme, votre système et des lignes de journal récentes dans le presse-papiers, prêt à coller dans un rapport de bogue. Il contient vos adresses de flux, qui peuvent inclure votre identifiant fournisseur ; vérifiez-le avant de le partager publiquement.

Problèmes courants :

- Une chaîne ne se lit pas : beaucoup de fournisseurs n'autorisent qu'un flux par compte à la fois. Arrêtez les autres lectures, enregistrements ou téléchargements du même compte et réessayez.
- Une chaîne n'a pas de guide : vérifiez qu'une de vos sources EPG la couvre, et importez le guide à nouveau.
- La lecture saccade : le lecteur intégré règle son tampon tout seul. Vous pouvez augmenter internal_player_buffer_seconds et internal_player_max_buffer_seconds dans iptvclient.conf pour un tampon plus patient.
- Le rattrapage dit que l'émission n'est pas disponible : elle est probablement plus ancienne que l'archive de votre fournisseur.

## Raccourcis clavier {#keyboard-shortcuts}

Partout :

- F1 : aide sur ce que vous utilisez.

Fenêtre principale :

- Ctrl+M : Gestionnaire de listes de lecture.
- Ctrl+E : Gestionnaire EPG.
- Ctrl+I : Importer l'EPG dans la base de données.
- Ctrl+W : À l'affiche maintenant.
- Ctrl+Shift+A : Informations du compte.
- Ctrl+D : ajouter la chaîne sélectionnée aux favoris, ou la retirer.
- Suppr : retirer la chaîne sélectionnée des favoris, dans la catégorie Favoris.
- Ctrl+Shift+R : démarrer ou arrêter l'enregistrement de la chaîne sélectionnée.
- Ctrl+Shift+D : montrer les fenêtres de téléchargement de rattrapage.
- Ctrl+Shift+J : montrer le lecteur intégré.
- Ctrl+Shift+P : lire ou mettre en pause le lecteur intégré.
- Ctrl+Shift+S : arrêter le lecteur intégré.
- Ctrl+Shift+C : diffuser ou connecter.
- Ctrl+Haut et Ctrl+Bas : volume du lecteur intégré.
- Entrée : lire la chaîne sélectionnée.
- Touche Applications ou Shift+F10 : le menu de la chaîne.
- Ctrl+Q : quitter.

Lecteur intégré :

- Espace : appuyer sur le bouton ayant le focus, comme Pause.
- Ctrl+P : lire ou mettre en pause.
- Ctrl+S : arrêter.
- Ctrl+R : enregistrer.
- Haut et Bas : volume par pas de 2 % ; avec Ctrl, pas de 5 %.
- A : piste audio suivante.
- D : périphérique de sortie audio.
- Ctrl+C : diffuser.
- F11 : plein écran ; Échap quitte le plein écran.
- Ctrl+W : masquer le lecteur.
- Ctrl+Q : fermer le lecteur.

Listes de sources dans le Gestionnaire de listes de lecture et le Gestionnaire EPG :

- F2 : renommer.
- Suppr : supprimer.

## Obtenir de l'aide {#support}

Questions, rapports de bogues et nouvelles des versions :

- Le groupe Telegram SerrebiProjects : https://t.me/SerrebiProjects
- Rapports de bogues et suggestions sur GitHub : https://github.com/serrebidev/Accessible-IPTV-Client/issues

Aide > À propos… montre la version en cours d'exécution et lie les deux. Quand vous signalez un problème, Aide > Copier le journal et les informations de débogage donne les détails nécessaires pour le retrouver.

param(
    # Everything below can arrive later, in the session folder's command file:
    # with -SessionDir this helper shows its window first and is told what to
    # install once the download has finished (see "Attending the app").
    [int]$ParentPid = 0,
    [string]$InstallDir = "",
    [string]$StagingDir = "",
    [string]$BackupDir = "",
    [string]$InstallerPath = "",
    [string]$ExeName = "",
    # The folder the app and this helper talk through: status.json (what to
    # show), command.json (what to do), and "cancel" (the user pressed Cancel).
    [string]$SessionDir = "",
    [string]$RestartArgs = "",
    [string]$ReadyFile = "",
    [string]$Language = "en",
    # Tests only: prove the script starts and reads its arguments, then stop.
    [switch]$SelfTest
)

Set-Location $env:TEMP
$logPath = Join-Path $env:TEMP "AccessibleIPTVClient_update.log"
# Why the update failed, for the app to report when it starts again. The step
# log alone only ever reached the user as a path they had to go and open, so
# a failure could be reported six times over without anyone learning its cause
# (issue #26). updater.read_update_result reads this file.
$resultPath = Join-Path $env:TEMP "AccessibleIPTVClient_update_result.json"

function Write-Log {
    param([string]$Message)
    try {
        $stamp = (Get-Date).ToString("o")
        Add-Content -Path $logPath -Value "$stamp $Message"
    } catch { }
}

# Logged before anything that can fail, so an update that stops early still
# leaves a line saying the helper ran at all (issue #26 left no trace).
Write-Log "Update helper started (PID $PID, PowerShell $($PSVersionTable.PSVersion)). InstallDir=$InstallDir InstallerPath=$InstallerPath StagingDir=$StagingDir"

if ($SelfTest) {
    if ($ReadyFile) { New-Item -ItemType File -Path $ReadyFile -Force | Out-Null }
    exit 0
}

try { Remove-Item -LiteralPath $resultPath -Force -ErrorAction SilentlyContinue } catch { }

trap {
    Write-Log "Unhandled error: $($_.Exception.Message) at line $($_.InvocationInfo.ScriptLineNumber)"
    continue
}

# Windows PowerShell 5.1 reads a BOM-less script through the machine's legacy
# ANSI code page. Keep this file ASCII and encode translated text as JSON
# Unicode escapes; ConvertFrom-Json restores real Unicode strings for WinForms
# and screen readers. The helper cannot use the Python gettext catalogue while
# the application directory is being replaced, so it carries this small,
# self-contained set and falls back to English for an unknown language.
$UpdateMessagesJson = @'
{
  "en": {
    "prepare": "Preparing the update. The application is closing; installation will start as soon as it closes.",
    "consent": "Windows will now ask for permission to install the update. Please allow it.",
    "install": "Installing the update. This can take a minute; please leave this window open.",
    "start": "Starting the updated application...",
    "error": "The update did not finish. Please try again from the Help menu in the application.",
    "complete": "Update complete. Version {version} is starting. This window will close by itself.",
    "cancel": "Cancel",
    "close": "Close",
    "restart": "The update is installed, but the application could not be started. Please open it yourself."
  },
  "es": {
    "prepare": "Preparando la actualizaci\u00f3n. La aplicaci\u00f3n se est\u00e1 cerrando; la instalaci\u00f3n comenzar\u00e1 en cuanto se cierre.",
    "consent": "Windows pedir\u00e1 ahora permiso para instalar la actualizaci\u00f3n. Perm\u00edtalo, por favor.",
    "install": "Instalando la actualizaci\u00f3n. Esto puede tardar un minuto; deje esta ventana abierta.",
    "start": "Iniciando la versi\u00f3n actualizada de la aplicaci\u00f3n...",
    "error": "La actualizaci\u00f3n no termin\u00f3. Int\u00e9ntelo de nuevo desde el men\u00fa Ayuda de la aplicaci\u00f3n.",
    "complete": "Actualizaci\u00f3n completada. La versi\u00f3n {version} se est\u00e1 iniciando. Esta ventana se cerrar\u00e1 sola.",
    "cancel": "Cancelar",
    "close": "Cerrar",
    "restart": "La actualizaci\u00f3n est\u00e1 instalada, pero no se pudo iniciar la aplicaci\u00f3n. \u00c1brala usted mismo."
  },
  "ar": {
    "prepare": "\u062c\u0627\u0631\u064d \u062a\u062d\u0636\u064a\u0631 \u0627\u0644\u062a\u062d\u062f\u064a\u062b. \u064a\u062a\u0645 \u0625\u063a\u0644\u0627\u0642 \u0627\u0644\u062a\u0637\u0628\u064a\u0642\u061b \u0633\u064a\u0628\u062f\u0623 \u0627\u0644\u062a\u062b\u0628\u064a\u062a \u0628\u0645\u062c\u0631\u062f \u0625\u063a\u0644\u0627\u0642\u0647.",
    "consent": "\u0633\u064a\u0637\u0644\u0628 Windows \u0627\u0644\u0622\u0646 \u0627\u0644\u0625\u0630\u0646 \u0628\u062a\u062b\u0628\u064a\u062a \u0627\u0644\u062a\u062d\u062f\u064a\u062b. \u064a\u064f\u0631\u062c\u0649 \u0627\u0644\u0633\u0645\u0627\u062d \u0628\u0630\u0644\u0643.",
    "install": "\u062c\u0627\u0631\u064d \u062a\u062b\u0628\u064a\u062a \u0627\u0644\u062a\u062d\u062f\u064a\u062b. \u0642\u062f \u064a\u0633\u062a\u063a\u0631\u0642 \u0630\u0644\u0643 \u062f\u0642\u064a\u0642\u0629\u061b \u064a\u064f\u0631\u062c\u0649 \u062a\u0631\u0643 \u0647\u0630\u0647 \u0627\u0644\u0646\u0627\u0641\u0630\u0629 \u0645\u0641\u062a\u0648\u062d\u0629.",
    "start": "\u062c\u0627\u0631\u064d \u062a\u0634\u063a\u064a\u0644 \u0627\u0644\u0625\u0635\u062f\u0627\u0631 \u0627\u0644\u0645\u062d\u062f\u0651\u062b \u0645\u0646 \u0627\u0644\u062a\u0637\u0628\u064a\u0642...",
    "error": "\u0644\u0645 \u064a\u0643\u062a\u0645\u0644 \u0627\u0644\u062a\u062d\u062f\u064a\u062b. \u064a\u064f\u0631\u062c\u0649 \u0627\u0644\u0645\u062d\u0627\u0648\u0644\u0629 \u0645\u0631\u0629 \u0623\u062e\u0631\u0649 \u0645\u0646 \u0642\u0627\u0626\u0645\u0629 \u0627\u0644\u0645\u0633\u0627\u0639\u062f\u0629 \u0641\u064a \u0627\u0644\u062a\u0637\u0628\u064a\u0642.",
    "complete": "\u0627\u0643\u062a\u0645\u0644 \u0627\u0644\u062a\u062d\u062f\u064a\u062b. \u064a\u062c\u0631\u064a \u062a\u0634\u063a\u064a\u0644 \u0627\u0644\u0625\u0635\u062f\u0627\u0631 {version}. \u0633\u062a\u063a\u0644\u0642 \u0647\u0630\u0647 \u0627\u0644\u0646\u0627\u0641\u0630\u0629 \u062a\u0644\u0642\u0627\u0626\u064a\u064b\u0627.",
    "cancel": "\u0625\u0644\u063a\u0627\u0621",
    "close": "\u0625\u063a\u0644\u0627\u0642",
    "restart": "\u062a\u0645 \u062a\u062b\u0628\u064a\u062a \u0627\u0644\u062a\u062d\u062f\u064a\u062b\u060c \u0644\u0643\u0646 \u062a\u0639\u0630\u0651\u0631 \u062a\u0634\u063a\u064a\u0644 \u0627\u0644\u062a\u0637\u0628\u064a\u0642. \u064a\u064f\u0631\u062c\u0649 \u0641\u062a\u062d\u0647 \u0628\u0646\u0641\u0633\u0643."
  },
  "pt": {
    "prepare": "Preparando a atualiza\u00e7\u00e3o. O aplicativo est\u00e1 sendo fechado; a instala\u00e7\u00e3o come\u00e7ar\u00e1 assim que ele for fechado.",
    "consent": "O Windows vai pedir permiss\u00e3o para instalar a atualiza\u00e7\u00e3o. Por favor, permita.",
    "install": "Instalando a atualiza\u00e7\u00e3o. Isso pode levar um minuto; deixe esta janela aberta.",
    "start": "Iniciando o aplicativo atualizado...",
    "error": "A atualiza\u00e7\u00e3o n\u00e3o foi conclu\u00edda. Tente novamente pelo menu Ajuda do aplicativo.",
    "complete": "Atualiza\u00e7\u00e3o conclu\u00edda. A vers\u00e3o {version} est\u00e1 iniciando. Esta janela se fechar\u00e1 sozinha.",
    "cancel": "Cancelar",
    "close": "Fechar",
    "restart": "A atualiza\u00e7\u00e3o foi instalada, mas o aplicativo n\u00e3o p\u00f4de ser iniciado. Abra-o voc\u00ea mesmo."
  },
  "fr": {
    "prepare": "Pr\u00e9paration de la mise \u00e0 jour. L\u2019application est en cours de fermeture ; l\u2019installation commencera d\u00e8s qu\u2019elle sera ferm\u00e9e.",
    "consent": "Windows va maintenant demander l\u2019autorisation d\u2019installer la mise \u00e0 jour. Veuillez l\u2019accepter.",
    "install": "Installation de la mise \u00e0 jour. Cela peut prendre une minute ; veuillez laisser cette fen\u00eatre ouverte.",
    "start": "D\u00e9marrage de la version mise \u00e0 jour de l\u2019application...",
    "error": "La mise \u00e0 jour ne s\u2019est pas termin\u00e9e. R\u00e9essayez depuis le menu Aide de l\u2019application.",
    "complete": "Mise \u00e0 jour termin\u00e9e. La version {version} d\u00e9marre. Cette fen\u00eatre se fermera toute seule.",
    "cancel": "Annuler",
    "close": "Fermer",
    "restart": "La mise \u00e0 jour est install\u00e9e, mais l'application n'a pas pu d\u00e9marrer. Veuillez l'ouvrir vous-m\u00eame."
  },
  "de": {
    "prepare": "Das Update wird vorbereitet. Die Anwendung wird beendet; die Installation beginnt, sobald das Programm geschlossen ist.",
    "consent": "Windows fragt jetzt nach der Berechtigung, das Update zu installieren. Bitte erlauben Sie es.",
    "install": "Das Update wird installiert. Dies kann eine Minute dauern; bitte lassen Sie dieses Fenster ge\u00f6ffnet.",
    "start": "Die aktualisierte Anwendung wird gestartet...",
    "error": "Das Update wurde nicht abgeschlossen. Bitte versuchen Sie es \u00fcber das Hilfe-Men\u00fc der Anwendung erneut.",
    "complete": "Update abgeschlossen. Version {version} wird gestartet. Dieses Fenster schlie\u00dft sich von selbst.",
    "cancel": "Abbrechen",
    "close": "Schlie\u00dfen",
    "restart": "Das Update ist installiert, aber die Anwendung konnte nicht gestartet werden. Bitte \u00f6ffnen Sie sie selbst."
  },
  "ru": {
    "prepare": "\u041f\u043e\u0434\u0433\u043e\u0442\u043e\u0432\u043a\u0430 \u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u044f. \u041f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u0435 \u0437\u0430\u043a\u0440\u044b\u0432\u0430\u0435\u0442\u0441\u044f; \u0443\u0441\u0442\u0430\u043d\u043e\u0432\u043a\u0430 \u043d\u0430\u0447\u043d\u0451\u0442\u0441\u044f \u0441\u0440\u0430\u0437\u0443 \u043f\u043e\u0441\u043b\u0435 \u0437\u0430\u043a\u0440\u044b\u0442\u0438\u044f.",
    "consent": "\u0421\u0435\u0439\u0447\u0430\u0441 Windows \u0437\u0430\u043f\u0440\u043e\u0441\u0438\u0442 \u0440\u0430\u0437\u0440\u0435\u0448\u0435\u043d\u0438\u0435 \u043d\u0430 \u0443\u0441\u0442\u0430\u043d\u043e\u0432\u043a\u0443 \u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u044f. \u041f\u043e\u0436\u0430\u043b\u0443\u0439\u0441\u0442\u0430, \u0440\u0430\u0437\u0440\u0435\u0448\u0438\u0442\u0435 \u0435\u0451.",
    "install": "\u0423\u0441\u0442\u0430\u043d\u043e\u0432\u043a\u0430 \u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u044f. \u042d\u0442\u043e \u043c\u043e\u0436\u0435\u0442 \u0437\u0430\u043d\u044f\u0442\u044c \u043c\u0438\u043d\u0443\u0442\u0443; \u043e\u0441\u0442\u0430\u0432\u044c\u0442\u0435 \u044d\u0442\u043e \u043e\u043a\u043d\u043e \u043e\u0442\u043a\u0440\u044b\u0442\u044b\u043c.",
    "start": "\u0417\u0430\u043f\u0443\u0441\u043a \u043e\u0431\u043d\u043e\u0432\u043b\u0451\u043d\u043d\u043e\u0439 \u0432\u0435\u0440\u0441\u0438\u0438 \u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u044f...",
    "error": "\u041e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u0435 \u043d\u0435 \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u043e. \u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u0435 \u043f\u043e\u043f\u044b\u0442\u043a\u0443 \u0447\u0435\u0440\u0435\u0437 \u043c\u0435\u043d\u044e \u00ab\u0421\u043f\u0440\u0430\u0432\u043a\u0430\u00bb \u0432 \u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u0438.",
    "complete": "\u041e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u0435 \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u043e. \u0412\u0435\u0440\u0441\u0438\u044f {version} \u0437\u0430\u043f\u0443\u0441\u043a\u0430\u0435\u0442\u0441\u044f. \u042d\u0442\u043e \u043e\u043a\u043d\u043e \u0437\u0430\u043a\u0440\u043e\u0435\u0442\u0441\u044f \u0441\u0430\u043c\u043e.",
    "cancel": "\u041e\u0442\u043c\u0435\u043d\u0430",
    "close": "\u0417\u0430\u043a\u0440\u044b\u0442\u044c",
    "restart": "\u041e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u0435 \u0443\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d\u043e, \u043d\u043e \u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u0435 \u043d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u044c. \u041e\u0442\u043a\u0440\u043e\u0439\u0442\u0435 \u0435\u0433\u043e \u0441\u0430\u043c\u043e\u0441\u0442\u043e\u044f\u0442\u0435\u043b\u044c\u043d\u043e."
  },
  "tr": {
    "prepare": "G\u00fcncelleme haz\u0131rlan\u0131yor. Uygulama kapan\u0131yor; kapand\u0131\u011f\u0131nda kurulum ba\u015flayacak.",
    "consent": "Windows \u015fimdi g\u00fcncellemeyi y\u00fcklemek i\u00e7in izin isteyecek. L\u00fctfen izin verin.",
    "install": "G\u00fcncelleme y\u00fckleniyor. Bu i\u015flem bir dakika s\u00fcrebilir; l\u00fctfen bu pencereyi a\u00e7\u0131k b\u0131rak\u0131n.",
    "start": "G\u00fcncellenmi\u015f uygulama ba\u015flat\u0131l\u0131yor...",
    "error": "G\u00fcncelleme tamamlanamad\u0131. L\u00fctfen uygulamadaki Yard\u0131m men\u00fcs\u00fcnden yeniden deneyin.",
    "complete": "G\u00fcncelleme tamamland\u0131. {version} s\u00fcr\u00fcm\u00fc ba\u015flat\u0131l\u0131yor. Bu pencere kendili\u011finden kapanacak.",
    "cancel": "\u0130ptal",
    "close": "Kapat",
    "restart": "G\u00fcncelleme kuruldu, ancak uygulama ba\u015flat\u0131lamad\u0131. L\u00fctfen kendiniz a\u00e7\u0131n."
  },
  "it": {
    "prepare": "Preparazione dell\u2019aggiornamento. L\u2019applicazione si sta chiudendo; l\u2019installazione inizier\u00e0 non appena sar\u00e0 chiusa.",
    "consent": "Ora Windows chieder\u00e0 l\u2019autorizzazione a installare l\u2019aggiornamento. Consentila.",
    "install": "Installazione dell\u2019aggiornamento. Potrebbe richiedere un minuto; lascia aperta questa finestra.",
    "start": "Avvio della versione aggiornata dell\u2019applicazione...",
    "error": "L\u2019aggiornamento non \u00e8 stato completato. Riprova dal menu Aiuto dell\u2019applicazione.",
    "complete": "Aggiornamento completato. La versione {version} si sta avviando. Questa finestra si chiuder\u00e0 da sola.",
    "cancel": "Annulla",
    "close": "Chiudi",
    "restart": "L'aggiornamento \u00e8 installato, ma non \u00e8 stato possibile avviare l'applicazione. Aprila tu stesso."
  },
  "pl": {
    "prepare": "Przygotowywanie aktualizacji. Program jest zamykany; instalacja rozpocznie si\u0119 zaraz po jego zamkni\u0119ciu.",
    "consent": "System Windows poprosi teraz o zgod\u0119 na zainstalowanie aktualizacji. Wyra\u017a j\u0105, prosz\u0119.",
    "install": "Instalowanie aktualizacji. Mo\u017ce to potrwa\u0107 minut\u0119; pozostaw to okno otwarte.",
    "start": "Uruchamianie zaktualizowanej wersji programu...",
    "error": "Aktualizacja nie zosta\u0142a uko\u0144czona. Spr\u00f3buj ponownie z menu Pomoc w aplikacji.",
    "complete": "Aktualizacja zako\u0144czona. Wersja {version} uruchamia si\u0119. To okno zamknie si\u0119 samo.",
    "cancel": "Anuluj",
    "close": "Zamknij",
    "restart": "Aktualizacja zosta\u0142a zainstalowana, ale nie uda\u0142o si\u0119 uruchomi\u0107 aplikacji. Otw\u00f3rz j\u0105 samodzielnie."
  },
  "hi": {
    "prepare": "\u0905\u092a\u0921\u0947\u091f \u0915\u0940 \u0924\u0948\u092f\u093e\u0930\u0940 \u0939\u094b \u0930\u0939\u0940 \u0939\u0948\u0964 \u0910\u092a\u094d\u0932\u093f\u0915\u0947\u0936\u0928 \u092c\u0902\u0926 \u0939\u094b \u0930\u0939\u093e \u0939\u0948; \u0907\u0938\u0915\u0947 \u092c\u0902\u0926 \u0939\u094b\u0924\u0947 \u0939\u0940 \u0907\u0902\u0938\u094d\u091f\u0949\u0932\u0947\u0936\u0928 \u0936\u0941\u0930\u0942 \u0939\u094b \u091c\u093e\u090f\u0917\u093e\u0964",
    "consent": "Windows \u0905\u092c \u0905\u092a\u0921\u0947\u091f \u0907\u0902\u0938\u094d\u091f\u0949\u0932 \u0915\u0930\u0928\u0947 \u0915\u0940 \u0905\u0928\u0941\u092e\u0924\u093f \u092e\u093e\u0901\u0917\u0947\u0917\u093e\u0964 \u0915\u0943\u092a\u092f\u093e \u0905\u0928\u0941\u092e\u0924\u093f \u0926\u0947\u0902\u0964",
    "install": "\u0905\u092a\u0921\u0947\u091f \u0907\u0902\u0938\u094d\u091f\u0949\u0932 \u0939\u094b \u0930\u0939\u093e \u0939\u0948\u0964 \u0907\u0938\u092e\u0947\u0902 \u090f\u0915 \u092e\u093f\u0928\u091f \u0932\u0917 \u0938\u0915\u0924\u093e \u0939\u0948; \u0915\u0943\u092a\u092f\u093e \u0907\u0938 \u0935\u093f\u0902\u0921\u094b \u0915\u094b \u0916\u0941\u0932\u093e \u091b\u094b\u0921\u093c \u0926\u0947\u0902\u0964",
    "start": "\u0905\u092a\u0921\u0947\u091f \u0915\u093f\u092f\u093e \u0917\u092f\u093e \u0910\u092a\u094d\u0932\u093f\u0915\u0947\u0936\u0928 \u0936\u0941\u0930\u0942 \u0939\u094b \u0930\u0939\u093e \u0939\u0948...",
    "error": "\u0905\u092a\u0921\u0947\u091f \u092a\u0942\u0930\u093e \u0928\u0939\u0940\u0902 \u0939\u0941\u0906\u0964 \u0915\u0943\u092a\u092f\u093e \u0910\u092a \u0915\u0947 \u0938\u0939\u093e\u092f\u0924\u093e \u092e\u0947\u0928\u0942 \u0938\u0947 \u092b\u093f\u0930 \u0938\u0947 \u092a\u094d\u0930\u092f\u093e\u0938 \u0915\u0930\u0947\u0902\u0964",
    "complete": "\u0905\u0926\u094d\u092f\u0924\u0928 \u092a\u0942\u0930\u093e \u0939\u0941\u0906\u0964 \u0938\u0902\u0938\u094d\u0915\u0930\u0923 {version} \u0936\u0941\u0930\u0942 \u0939\u094b \u0930\u0939\u093e \u0939\u0948\u0964 \u092f\u0939 \u0935\u093f\u0902\u0921\u094b \u0905\u092a\u0928\u0947 \u0906\u092a \u092c\u0902\u0926 \u0939\u094b \u091c\u093e\u090f\u0917\u0940\u0964",
    "cancel": "\u0930\u0926\u094d\u0926 \u0915\u0930\u0947\u0902",
    "close": "\u092c\u0902\u0926 \u0915\u0930\u0947\u0902",
    "restart": "\u0905\u0926\u094d\u092f\u0924\u0928 \u0938\u094d\u0925\u093e\u092a\u093f\u0924 \u0939\u094b \u0917\u092f\u093e, \u0932\u0947\u0915\u093f\u0928 \u0905\u0928\u0941\u092a\u094d\u0930\u092f\u094b\u0917 \u0936\u0941\u0930\u0942 \u0928\u0939\u0940\u0902 \u0939\u094b \u0938\u0915\u093e\u0964 \u0915\u0943\u092a\u092f\u093e \u0907\u0938\u0947 \u0938\u094d\u0935\u092f\u0902 \u0916\u094b\u0932\u0947\u0902\u0964"
  },
  "zh": {
    "prepare": "\u6b63\u5728\u51c6\u5907\u66f4\u65b0\u3002\u5e94\u7528\u7a0b\u5e8f\u6b63\u5728\u5173\u95ed\uff1b\u5173\u95ed\u540e\u5c06\u7acb\u5373\u5f00\u59cb\u5b89\u88c5\u3002",
    "consent": "Windows \u73b0\u5728\u4f1a\u8bf7\u6c42\u5b89\u88c5\u66f4\u65b0\u7684\u6743\u9650\u3002\u8bf7\u5141\u8bb8\u3002",
    "install": "\u6b63\u5728\u5b89\u88c5\u66f4\u65b0\u3002\u8fd9\u53ef\u80fd\u9700\u8981\u4e00\u5206\u949f\uff1b\u8bf7\u4fdd\u6301\u6b64\u7a97\u53e3\u6253\u5f00\u3002",
    "start": "\u6b63\u5728\u542f\u52a8\u66f4\u65b0\u540e\u7684\u5e94\u7528\u7a0b\u5e8f...",
    "error": "\u66f4\u65b0\u672a\u5b8c\u6210\u3002\u8bf7\u4ece\u5e94\u7528\u7a0b\u5e8f\u7684\u201c\u5e2e\u52a9\u201d\u83dc\u5355\u91cd\u8bd5\u3002",
    "complete": "\u66f4\u65b0\u5b8c\u6210\u3002\u7248\u672c {version} \u6b63\u5728\u542f\u52a8\u3002\u6b64\u7a97\u53e3\u5c06\u81ea\u52a8\u5173\u95ed\u3002",
    "cancel": "\u53d6\u6d88",
    "close": "\u5173\u95ed",
    "restart": "\u66f4\u65b0\u5df2\u5b89\u88c5\uff0c\u4f46\u65e0\u6cd5\u542f\u52a8\u5e94\u7528\u7a0b\u5e8f\u3002\u8bf7\u81ea\u884c\u6253\u5f00\u5b83\u3002"
  },
  "ja": {
    "prepare": "\u66f4\u65b0\u3092\u6e96\u5099\u3057\u3066\u3044\u307e\u3059\u3002\u30a2\u30d7\u30ea\u30b1\u30fc\u30b7\u30e7\u30f3\u3092\u7d42\u4e86\u3057\u3066\u3044\u307e\u3059\u3002\u7d42\u4e86\u5f8c\u3059\u3050\u306b\u30a4\u30f3\u30b9\u30c8\u30fc\u30eb\u3092\u958b\u59cb\u3057\u307e\u3059\u3002",
    "consent": "Windows \u304c\u66f4\u65b0\u306e\u30a4\u30f3\u30b9\u30c8\u30fc\u30eb\u306e\u8a31\u53ef\u3092\u6c42\u3081\u307e\u3059\u3002\u8a31\u53ef\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
    "install": "\u66f4\u65b0\u3092\u30a4\u30f3\u30b9\u30c8\u30fc\u30eb\u3057\u3066\u3044\u307e\u3059\u30021 \u5206\u307b\u3069\u304b\u304b\u308b\u5834\u5408\u304c\u3042\u308a\u307e\u3059\u3002\u3053\u306e\u30a6\u30a3\u30f3\u30c9\u30a6\u306f\u958b\u3044\u305f\u307e\u307e\u306b\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
    "start": "\u66f4\u65b0\u3055\u308c\u305f\u30a2\u30d7\u30ea\u30b1\u30fc\u30b7\u30e7\u30f3\u3092\u8d77\u52d5\u3057\u3066\u3044\u307e\u3059...",
    "error": "\u66f4\u65b0\u304c\u5b8c\u4e86\u3057\u307e\u305b\u3093\u3067\u3057\u305f\u3002\u30a2\u30d7\u30ea\u30b1\u30fc\u30b7\u30e7\u30f3\u306e\uff3b\u30d8\u30eb\u30d7\uff3d\u30e1\u30cb\u30e5\u30fc\u304b\u3089\u3082\u3046\u4e00\u5ea6\u304a\u8a66\u3057\u304f\u3060\u3055\u3044\u3002",
    "complete": "\u66f4\u65b0\u304c\u5b8c\u4e86\u3057\u307e\u3057\u305f\u3002\u30d0\u30fc\u30b8\u30e7\u30f3 {version} \u3092\u8d77\u52d5\u3057\u3066\u3044\u307e\u3059\u3002\u3053\u306e\u30a6\u30a3\u30f3\u30c9\u30a6\u306f\u81ea\u52d5\u7684\u306b\u9589\u3058\u307e\u3059\u3002",
    "cancel": "\u30ad\u30e3\u30f3\u30bb\u30eb",
    "close": "\u9589\u3058\u308b",
    "restart": "\u66f4\u65b0\u306f\u30a4\u30f3\u30b9\u30c8\u30fc\u30eb\u3055\u308c\u307e\u3057\u305f\u304c\u3001\u30a2\u30d7\u30ea\u3092\u8d77\u52d5\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f\u3002\u624b\u52d5\u3067\u958b\u3044\u3066\u304f\u3060\u3055\u3044\u3002"
  },
  "hu": {
    "prepare": "A friss\u00edt\u00e9s el\u0151k\u00e9sz\u00edt\u00e9se folyamatban van. Az alkalmaz\u00e1s bez\u00e1rul; a telep\u00edt\u00e9s a bez\u00e1r\u00e1s ut\u00e1n azonnal elindul.",
    "consent": "A Windows most enged\u00e9lyt k\u00e9r a friss\u00edt\u00e9s telep\u00edt\u00e9s\u00e9hez. K\u00e9rj\u00fck, enged\u00e9lyezze.",
    "install": "A friss\u00edt\u00e9s telep\u00edt\u00e9se folyamatban van. Ez k\u00f6r\u00fclbel\u00fcl egy percig tarthat; hagyja nyitva ezt az ablakot.",
    "start": "A friss\u00edtett alkalmaz\u00e1s ind\u00edt\u00e1sa...",
    "error": "A friss\u00edt\u00e9s nem fejez\u0151d\u00f6tt be. Pr\u00f3b\u00e1lja \u00fajra az alkalmaz\u00e1s S\u00fag\u00f3 men\u00fcj\u00e9b\u0151l.",
    "complete": "A friss\u00edt\u00e9s befejez\u0151d\u00f6tt. A(z) {version} verzi\u00f3 indul. Ez az ablak mag\u00e1t\u00f3l bez\u00e1rul.",
    "cancel": "M\u00e9gse",
    "close": "Bez\u00e1r\u00e1s",
    "restart": "A friss\u00edt\u00e9s telep\u00fclt, de az alkalmaz\u00e1st nem siker\u00fclt elind\u00edtani. K\u00e9rj\u00fck, nyissa meg saj\u00e1t maga."
  }
}
'@

function Get-UpdateMessages {
    param([string]$Code)
    try {
        $catalog = $UpdateMessagesJson | ConvertFrom-Json
        $normalized = if ($Code) { $Code.Trim().ToLowerInvariant() } else { "en" }
        $normalized = ($normalized -split '[-_]')[0]
        $property = $catalog.PSObject.Properties[$normalized]
        if (-not $property) { $property = $catalog.PSObject.Properties["en"] }
        return $property.Value
    } catch {
        return [PSCustomObject]@{
            prepare = "Preparing the update. Accessible IPTV Client is closing; installation will start as soon as it closes."
            install = "Installing the update. This can take a minute; please leave this window open."
            start = "Starting the updated Accessible IPTV Client..."
            consent = "Windows will now ask for permission to install the update. Please allow it."
            error = "The update did not finish. Please try again from the Help menu in the application."
            complete = "Update complete. Version {version} is starting. This window will close by itself."
            restart = "The update is installed, but the application could not be started. Please open it yourself."
            cancel = "Cancel"
            close = "Close"
        }
    }
}

$updateMessages = Get-UpdateMessages -Code $Language

# The app closes before the installer runs, so for the length of the update
# nothing was on screen: the window vanished, the installer worked silently, and
# a screen-reader user was left with no idea whether anything was happening or
# whether the app was ever coming back. This helper owns a small status window
# instead. It cannot be in the app itself (the app has to exit for the install
# to start), so it is shown here, kept up through the installer and the restart,
# and closed only once the new app has actually started.
#
# A WinForms window only stays alive while something pumps its messages, and
# this script spends nearly all of its time waiting - for the app to exit, for
# the installer to finish, for the restarted app to prove it survived. Plain
# Start-Sleep pumps nothing, so the window used to go unresponsive within
# seconds: Windows ghosts it, paints it blank and stops it answering the screen
# reader, which is exactly the "the window disappears" the update was supposed
# to stop. Every wait below therefore goes through Wait-Pumped.
# The one window of the whole update. Its controls are held here rather than
# looked up by name: $form.Controls["StatusLabel"] came back null on a user's
# machine (issue #31 logged "The property 'Text' cannot be found on this
# object" after every failed install), and because the lookup threw on the
# first line of Update-StatusMessage, the title was never updated again - the
# window sat on "Preparing the update..." for the rest of the update, which is
# exactly the "the update window disappears" users report.
$script:StatusLabel = $null
$script:StatusProgress = $null
$script:StatusButton = $null
$script:StatusMessage = ""
$script:StatusButtonAction = ""
$script:AllowStatusClose = $false
# How long the finished update stays on screen: long enough for "Update
# complete" to be spoken, short enough that the window is gone by the time the
# user starts using the application again. Nothing in it is clickable by then.
$script:CompleteLingerMs = 4000
$script:CancelRequested = $false
$script:StatusDismissed = $false

function Show-UpdateStatus {
    param([string]$Message)
    try {
        Add-Type -AssemblyName System.Windows.Forms
        Add-Type -AssemblyName System.Drawing
        [System.Windows.Forms.Application]::EnableVisualStyles()
    } catch {
        Write-Log "Could not load WinForms for the status window: $($_.Exception.Message)"
        return $null
    }
    $screen = [System.Windows.Forms.Screen]::PrimaryScreen
    $workArea = $screen.WorkingArea
    $form = New-Object System.Windows.Forms.Form
    # The title carries the message from the start, not just from the first
    # update. Nothing in this window can take focus, so the window itself is
    # what NVDA reads when it appears - its title - and a generic title meant
    # the first message ("Preparing the update...") was never spoken at all.
    $form.Text = "Accessible IPTV Client - $Message"
    $form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedDialog
    $form.StartPosition = [System.Windows.Forms.FormStartPosition]::Manual
    $form.Location = New-Object System.Drawing.Point(($workArea.Left + 60), ($workArea.Top + 60))
    $form.Size = New-Object System.Drawing.Size(440, 190)
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    # No close button, and Alt+F4 is refused below: this window is the only
    # thing on screen for the length of the update, and once it is gone
    # nothing else reports what is happening.
    $form.ControlBox = $false
    $form.ShowInTaskbar = $true
    $form.TopMost = $true
    $form.Add_FormClosing({
        if (-not $script:AllowStatusClose) {
            $_.Cancel = $true
            Write-Log "Refused an attempt to close the status window."
        }
    })

    $statusLabel = New-Object System.Windows.Forms.Label
    $statusLabel.Name = "StatusLabel"
    $statusLabel.Text = $Message
    $statusLabel.AutoSize = $false
    $statusLabel.SetBounds(16, 16, 392, 76)
    $statusLabel.TabIndex = 0
    $form.Controls.Add($statusLabel)

    # A marquee bar is the one thing that says "still working" without any
    # text to re-read, and it keeps the window visibly alive between steps.
    $progress = New-Object System.Windows.Forms.ProgressBar
    $progress.Name = "StatusProgress"
    $progress.Style = [System.Windows.Forms.ProgressBarStyle]::Marquee
    $progress.MarqueeAnimationSpeed = 30
    $progress.SetBounds(16, 100, 392, 20)
    $progress.TabIndex = 1
    $form.Controls.Add($progress)

    # The only control that can ever take focus, and only while it has
    # something to do: Cancel during the download, Close on a failure. The
    # window is otherwise unfocusable on purpose, so NVDA reads its title.
    $button = New-Object System.Windows.Forms.Button
    $button.Name = "StatusButton"
    $button.SetBounds(308, 128, 100, 26)
    $button.TabIndex = 2
    $button.Visible = $false
    $button.Add_Click({
        if ($script:StatusButtonAction -eq "cancel") {
            $script:CancelRequested = $true
            Write-Log "The user pressed Cancel."
            Set-StatusButton -Action ""
        } elseif ($script:StatusButtonAction -eq "close") {
            $script:StatusDismissed = $true
        }
    })
    $form.Controls.Add($button)

    $script:StatusLabel = $statusLabel
    $script:StatusProgress = $progress
    $script:StatusButton = $button
    $script:StatusMessage = $Message
    $script:StatusWindow = $form
    try {
        $form.Show()
        $form.Activate()
        $script:StatusWindowHandle = $form.Handle
        # The app starts this helper as a hidden background process, and
        # Windows applies that to the first window the process shows: without
        # this the status window existed, with the right title, but was never
        # on screen until something forced it to the foreground. That is the
        # update window that "disappears" while the app is still closing.
        Show-StatusWindowForReal -Handle $form.Handle
        [System.Windows.Forms.Application]::DoEvents()
    } catch { }
    return $form
}

# SW_SHOWNORMAL, whatever STARTUPINFO asked for.
function Show-StatusWindowForReal {
    param([IntPtr]$Handle)
    if ($Handle -eq [IntPtr]::Zero) { return }
    if (-not ("UpdateHelperFocus" -as [type])) { return }
    try {
        if (-not [UpdateHelperFocus]::IsWindowVisible($Handle)) {
            [void][UpdateHelperFocus]::ShowWindow($Handle, 1)
            Write-Log "The status window was created hidden; shown explicitly."
        }
    } catch {
        Write-Log "Could not show the status window: $($_.Exception.Message)"
    }
}

# The window as it must always be: rebuilt if it somehow went away, because
# the update has nowhere else to report from.
function Get-StatusWindow {
    $window = $script:StatusWindow
    if ($window -and -not $window.IsDisposed) { return $window }
    Write-Log "The status window was gone; showing it again."
    $script:StatusFocusWatch = $false
    return (Show-UpdateStatus -Message $script:StatusMessage)
}

# Cancel during the download, Close on a failure, nothing the rest of the time.
function Set-StatusButton {
    param([string]$Action = "", [string]$Text = "")
    $script:StatusButtonAction = $Action
    $button = $script:StatusButton
    if (-not $button) { return }
    try {
        if ($Action) {
            if ($Text) { $button.Text = $Text }
            $button.Visible = $true
            $button.Enabled = $true
        } else {
            $button.Visible = $false
        }
    } catch {
        Write-Log "Could not update the status button: $($_.Exception.Message)"
    }
}

# How far the current step has got. Percentages change several times a second,
# so this never touches the title or the focus - only the bar.
function Set-StatusProgress {
    param($Percent)
    $bar = $script:StatusProgress
    if (-not $bar) { return }
    try {
        if ($null -eq $Percent) {
            if ($bar.Style -ne [System.Windows.Forms.ProgressBarStyle]::Marquee) {
                $bar.Style = [System.Windows.Forms.ProgressBarStyle]::Marquee
                $bar.MarqueeAnimationSpeed = 30
            }
            return
        }
        $value = [int][Math]::Max(0, [Math]::Min(100, [double]$Percent))
        if ($bar.Style -ne [System.Windows.Forms.ProgressBarStyle]::Continuous) {
            $bar.Style = [System.Windows.Forms.ProgressBarStyle]::Continuous
        }
        $bar.Value = $value
    } catch {
        Write-Log "Could not update the progress bar: $($_.Exception.Message)"
    }
}

function Update-StatusMessage {
    param($Window, [string]$Message)
    if (-not $Message -or $Message -eq $script:StatusMessage) { return }
    $script:StatusMessage = $Message
    $Window = Get-StatusWindow
    if (-not $Window) { return }
    try {
        if ($script:StatusLabel) { $script:StatusLabel.Text = $Message }
        # The title carries the same text so NVDA+T reports where the update
        # has got to, and so the taskbar button is not just "Updating...".
        $Window.Text = "Accessible IPTV Client - $Message"
        $Window.Refresh()
        [System.Windows.Forms.Application]::DoEvents()
    } catch {
        Write-Log "Status window update failed: $($_.Exception.Message)"
    }
    # A stage change nobody hears about is the "the window disappeared" of
    # issue #30: the app has already closed or UAC has just handed the screen
    # back, and the status window is left behind whatever now has focus.
    # Bring it forward once per stage - unless the user has deliberately moved
    # to another window, in which case the new text waits for them in the
    # title and the taskbar button.
    Focus-StatusWindow -Window $Window -Stage $Message
}

# --- Status window focus (issue #30) ---
# The status window used to be shown once and never brought forward again.
# Two moments then stranded a screen-reader user with nothing focused and
# nothing announced: the app closing (focus fell to the desktop) and the UAC
# prompt handing the screen back (focus returned to the app that had just
# exited). The window was still there - TopMost, title updating - but to NVDA
# it had disappeared. So each stage change re-focuses the window once, which
# makes NVDA read the new title. The exception is a user who has moved to
# another window on purpose: from then on the update must not keep stealing
# focus back, so Watch-StatusWindowFocus latches that and Focus-StatusWindow
# stays away.
#
# Not every other foreground window is the user leaving, though. The silent
# installer owns hidden windows, and the moment it starts one of them takes the
# foreground: focus lands on something invisible and NVDA goes quiet for the
# whole install. That used to latch as "the user left", so the window was never
# brought back, and because this helper was then no longer in the foreground,
# the restarted app could not take focus either and its "Update Complete" box
# went unread. Windows owned by the installer (or its child processes) are
# taken back at once. The UAC prompt - the secure desktop reports no foreground
# window at all, and consent.exe when the prompt is on the normal desktop - and
# the bare desktop or taskbar are neutral: they are not the user choosing
# another app.
if (-not ("UpdateHelperFocus" -as [type])) {
    try {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class UpdateHelperFocus {
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool AllowSetForegroundWindow(uint processId);
    [DllImport("user32.dll")] static extern bool BringWindowToTop(IntPtr hWnd);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
    [DllImport("user32.dll")] static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool attach);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern int GetClassName(IntPtr hWnd, System.Text.StringBuilder name, int size);
    [DllImport("kernel32.dll")] static extern uint GetCurrentThreadId();
    [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
    [DllImport("advapi32.dll")] static extern bool OpenProcessToken(IntPtr process, uint access, out IntPtr token);
    [DllImport("advapi32.dll")]
    static extern bool GetTokenInformation(IntPtr token, int infoClass, out int info, int size, out int returned);

    public static uint WindowProcessId(IntPtr hWnd) {
        uint processId;
        GetWindowThreadProcessId(hWnd, out processId);
        return processId;
    }

    public static string WindowClass(IntPtr hWnd) {
        var name = new System.Text.StringBuilder(256);
        GetClassName(hWnd, name, name.Capacity);
        return name.ToString();
    }

    // A background process may not simply take the foreground. Sharing the
    // input state of the thread that has it lifts that restriction; only ever
    // used against the installer's hidden windows, the desktop, or at a
    // stage change the user is waiting on.
    public static bool ForceForeground(IntPtr hWnd) {
        if (SetForegroundWindow(hWnd)) return true;
        IntPtr current = GetForegroundWindow();
        uint ignored;
        uint thread = current == IntPtr.Zero ? 0 : GetWindowThreadProcessId(current, out ignored);
        uint self = GetCurrentThreadId();
        if (thread == 0 || thread == self) return false;
        if (!AttachThreadInput(self, thread, true)) return false;
        try {
            BringWindowToTop(hWnd);
            return SetForegroundWindow(hWnd);
        } finally {
            AttachThreadInput(self, thread, false);
        }
    }

    // TOKEN_ELEVATION_TYPE: 1 no split token (UAC off, a standard user, or the
    // built-in Administrator), 2 already elevated, 3 an administrator's
    // filtered token, which needs consent. -1 when it cannot be read.
    public static int ElevationType() {
        IntPtr token;
        if (!OpenProcessToken(GetCurrentProcess(), 0x0008, out token)) return -1;
        try {
            int type, returned;
            if (!GetTokenInformation(token, 18, out type, 4, out returned)) return -1;
            return type;
        } finally {
            CloseHandle(token);
        }
    }
}
'@
    } catch {
        Write-Log "Could not load the focus helper: $($_.Exception.Message)"
    }
}

$script:StatusWindow = $null
$script:StatusWindowHandle = [IntPtr]::Zero
# Focus is only watched once the window has really held the foreground. Before
# that, the app's own progress dialog is legitimately in front, and watching
# then would mistake it for the user leaving.
$script:StatusFocusWatch = $false
$script:UserLeftStatusWindow = $false
$script:LastForeground = [IntPtr]::Zero
# Processes this update started whose windows are never the user's choice:
# the installer, and through Get-ForegroundOwnerKind its child processes.
$script:UpdateOwnedPids = @()
$script:ParentPidCache = @{}
$script:TransientSince = $null
$script:TransientGraceMs = 1500

# Thin wrappers, so the rules below can be tested without taking real focus.
function Get-ForegroundHandle {
    try { return [UpdateHelperFocus]::GetForegroundWindow() } catch { return [IntPtr]::Zero }
}

function Invoke-ForceForeground {
    param([IntPtr]$Handle)
    return [UpdateHelperFocus]::ForceForeground($Handle)
}

function Get-ParentProcessId {
    param([int]$ProcessId)
    if ($script:ParentPidCache.ContainsKey($ProcessId)) { return $script:ParentPidCache[$ProcessId] }
    $parent = 0
    try {
        $info = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction Stop
        if ($info) { $parent = [int]$info.ParentProcessId }
    } catch { }
    $script:ParentPidCache[$ProcessId] = $parent
    return $parent
}

# "self", "update" (the installer's windows), "neutral" (no window, the UAC
# prompt, the desktop or taskbar), "transient" (Explorer's invisible window for
# a foreground switch) or "other" (an application the user chose).
function Get-ForegroundOwnerKind {
    param([IntPtr]$Handle)
    if ($Handle -eq [IntPtr]::Zero) { return "neutral" }
    if ($Handle -eq $script:StatusWindowHandle) { return "self" }
    try {
        $windowClass = [UpdateHelperFocus]::WindowClass($Handle)
        if ($windowClass -in @("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd")) { return "neutral" }
        if ($windowClass -eq "ForegroundStaging") { return "transient" }
        $owner = [int][UpdateHelperFocus]::WindowProcessId($Handle)
    } catch {
        return "other"
    }
    if ($owner -eq $PID) { return "self" }
    try {
        if ((Get-Process -Id $owner -ErrorAction Stop).ProcessName -eq "consent") { return "neutral" }
    } catch { }
    # Inno Setup runs as Setup.exe plus the Setup.tmp it starts.
    $current = $owner
    for ($depth = 0; $depth -lt 3 -and $current -gt 0; $depth++) {
        if ($script:UpdateOwnedPids -contains $current) { return "update" }
        $current = Get-ParentProcessId -ProcessId $current
    }
    return "other"
}

# Which window took the foreground, for the log: "is this the user or not?"
# is only answerable afterwards if the log says whose window it was.
function Get-WindowDescription {
    param([IntPtr]$Handle)
    try {
        $owner = [int][UpdateHelperFocus]::WindowProcessId($Handle)
        $name = try { (Get-Process -Id $owner -ErrorAction Stop).ProcessName } catch { "?" }
        return "class $([UpdateHelperFocus]::WindowClass($Handle)), process $name $owner, parent $(Get-ParentProcessId -ProcessId $owner)"
    } catch {
        return "unknown"
    }
}

function Watch-StatusWindowFocus {
    if (-not $script:StatusFocusWatch -or $script:UserLeftStatusWindow) { return }
    if ($script:StatusWindowHandle -eq [IntPtr]::Zero) { return }
    $foreground = Get-ForegroundHandle
    # Only a change of foreground is classified; this runs every 50 ms. A
    # transient shell window that has stayed put is the exception: nothing
    # moves on from it by itself, so it is taken back after a short grace.
    if ($foreground -eq $script:LastForeground) {
        if ($script:TransientSince -and ((Get-Date) - $script:TransientSince).TotalMilliseconds -ge $script:TransientGraceMs) {
            $script:TransientSince = $null
            Write-Log "The foreground stayed on an invisible shell window; bringing the status window back."
            Focus-StatusWindow -Window $script:StatusWindow -Stage "focus left on a shell window"
        }
        return
    }
    $script:LastForeground = $foreground
    $script:TransientSince = $null
    switch (Get-ForegroundOwnerKind -Handle $foreground) {
        "transient" {
            # Windows 11 parks the foreground on Explorer's invisible
            # ForegroundStaging window while it switches between windows - and
            # when the silent installer starts, it stays parked there, so NVDA
            # had nothing to read for the whole install. During a real Alt+Tab
            # it is gone again long before the grace ends.
            $script:TransientSince = Get-Date
        }
        "update" {
            Write-Log "The installer took the foreground; bringing the status window back."
            Focus-StatusWindow -Window $script:StatusWindow -Stage "installer took focus"
        }
        "other" {
            $script:UserLeftStatusWindow = $true
            Write-Log "Focus moved to another window ($(Get-WindowDescription -Handle $foreground)); the update will not take it back."
        }
    }
}

# From here on the update is what the user is waiting for again, so the window
# may take focus once more. Before this, the download runs while the app is
# still usable, and someone who goes back to watching television must not have
# the focus pulled away by a progress message (issue #30's rule) - but that
# must not then silence the install, the failure or the confirmation.
function Reset-StatusFocusLatch {
    param([string]$Stage = "")
    if ($script:UserLeftStatusWindow) {
        Write-Log "The update needs the window again ($Stage); focus may be taken once more."
    }
    $script:UserLeftStatusWindow = $false
    $script:StatusFocusWatch = $false
}

function Focus-StatusWindow {
    param($Window, [string]$Stage = "")
    if (-not $Window) { return }
    if ($script:UserLeftStatusWindow) {
        Write-Log "Not re-focusing the status window ($Stage): the user switched away."
        return
    }
    if (-not ("UpdateHelperFocus" -as [type])) { return }
    try {
        $script:StatusWindow = $Window
        $script:StatusWindowHandle = $Window.Handle
        $granted = Invoke-ForceForeground -Handle $Window.Handle
        $Window.Activate()
        $foreground = Get-ForegroundHandle
        $script:LastForeground = $foreground
        if ($foreground -eq $script:StatusWindowHandle) { $script:StatusFocusWatch = $true }
        Write-Log "Status window focused for '$Stage' (foreground: $granted)."
    } catch {
        Write-Log "Could not focus the status window ($Stage): $($_.Exception.Message)"
    }
}

# Hand the right to take the foreground on to the app about to be started, so
# its window - and the "Update Complete" box it shows - gets focus and is read.
function Grant-ForegroundToNextProcess {
    try { [void][UpdateHelperFocus]::AllowSetForegroundWindow([uint32]::MaxValue) } catch { }
}

# Whether starting the installer elevated will put a UAC prompt on screen. With
# UAC off, or set to elevate administrators without asking, "Windows will now
# ask for permission" announced a prompt that never came. Unsure means yes: an
# unneeded warning is milder than a prompt nobody was told about.
function Test-ElevationPromptExpected {
    param($Policy = $null, $ElevationType = $null, $IsAdmin = $null)
    try {
        if ($null -eq $Policy) {
            $Policy = Get-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" -ErrorAction Stop
        }
        if ($null -eq $ElevationType) { $ElevationType = [UpdateHelperFocus]::ElevationType() }
        if ($null -eq $IsAdmin) {
            $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
            $IsAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
        }
    } catch {
        return $true
    }
    $enableLua = $Policy.EnableLUA
    if ($null -ne $enableLua -and [int]$enableLua -eq 0) {
        # UAC is off: an administrator runs everything elevated already. A
        # standard user gets the old Run As dialog, which does need an answer.
        return (-not $IsAdmin)
    }
    switch ([int]$ElevationType) {
        2 { return $false }
        3 {
            # 0 = elevate without prompting.
            $behavior = $Policy.ConsentPromptBehaviorAdmin
            return (-not ($null -ne $behavior -and [int]$behavior -eq 0))
        }
        1 {
            # The built-in Administrator without Admin Approval Mode holds a
            # full token. For a standard user, 0 = deny without prompting.
            if ($IsAdmin) { return $false }
            $behavior = $Policy.ConsentPromptBehaviorUser
            return (-not ($null -ne $behavior -and [int]$behavior -eq 0))
        }
    }
    return $true
}

# Every failure ends here. The status window has nothing focusable, so an
# error left in it for a few seconds was easy to miss entirely. If the app on
# disk still starts, start it: it reports the failed update itself, in its own
# language, with the log path. Only if it cannot start does this helper show a
# message box, which takes focus and waits for OK.
# What each Inno Setup exit code means, from the Inno Setup documentation.
$InnoExitCodes = @{
    1 = "Setup failed to initialize."
    2 = "Setup was cancelled before the installation started."
    3 = "A fatal error occurred while preparing the installation."
    4 = "A fatal error occurred during the installation."
    5 = "The installation was cancelled or aborted, for example because a file could not be replaced."
    6 = "Setup was terminated by another process."
    7 = "Setup found a problem that stops the installation, for example files in use."
    8 = "Setup needs Windows to restart before it can install."
}

# The lines of the Inno Setup log that say what went wrong: the message box
# Setup answered by itself in silent mode (it defaults to Abort), or failing
# that the last lines that mention an error.
function Get-InstallerError {
    param([string]$Path)
    try {
        if (-not (Test-Path -LiteralPath $Path)) { return "" }
        $lines = @(Get-Content -LiteralPath $Path -ErrorAction Stop)
    } catch {
        return ""
    }
    $picked = @()
    for ($i = $lines.Count - 1; $i -ge 0; $i--) {
        if ($lines[$i] -match 'Defaulting to \w+ for suppressed message box|Message box \(') {
            $picked += $lines[$i]
            for ($j = $i + 1; $j -lt $lines.Count -and $lines[$j] -match '^\s{4,}'; $j++) {
                $picked += $lines[$j]
            }
            break
        }
    }
    if (-not $picked) {
        $picked = @($lines | Where-Object {
            $_ -match '(?i)error|fail|fatal|denied|in use' -and $_ -notmatch '(?i)successfully'
        } | Select-Object -Last 4)
    }
    $text = (($picked | ForEach-Object { ($_ -replace '^\d{4}-\d\d-\d\d [\d:.]+\s+', '').Trim() }) |
        Where-Object { $_ }) -join " "
    if ($text.Length -gt 600) { $text = $text.Substring(0, 600) + "..." }
    return $text
}

# Told to the restarted app so it does not repeat the confirmation this
# window has already given.
function Write-UpdateSuccess {
    param([string]$Version = "")
    try {
        $result = [ordered]@{
            status  = "completed"
            version = $Version
            time    = (Get-Date).ToString("o")
        }
        [System.IO.File]::WriteAllText($resultPath, ($result | ConvertTo-Json -Compress), (New-Object System.Text.UTF8Encoding($false)))
    } catch {
        Write-Log "Could not write the update result: $($_.Exception.Message)"
    }
}

function Write-UpdateResult {
    param([string]$Kind, [string]$Reason, $ExitCode = $null, [string]$InstallerError = "")
    try {
        $result = [ordered]@{
            status          = "failed"
            kind            = $Kind
            reason          = $Reason
            exit_code       = $ExitCode
            installer_error = $InstallerError
            time            = (Get-Date).ToString("o")
        }
        [System.IO.File]::WriteAllText($resultPath, ($result | ConvertTo-Json -Compress), (New-Object System.Text.UTF8Encoding($false)))
    } catch {
        Write-Log "Could not write the update result: $($_.Exception.Message)"
    }
}

# The update worked. This window has been the only one on screen since the
# user confirmed the update, so it is also what says so at the end - the
# restarted app shows no box of its own (it checks for this result first).
function Complete-SuccessfulUpdate {
    param($Window, [bool]$Restarted, [string]$Version = "")
    if (-not $Restarted) {
        # The update is installed, but nothing is running to say so.
        Reset-StatusFocusLatch -Stage "the app could not be started"
        Set-StatusProgress -Percent 100
        Update-StatusMessage -Window $Window -Message $updateMessages.restart
        Wait-ForDismissal -Window $Window -Milliseconds 120000 -ButtonText $updateMessages.close
        Close-StatusWindow -Window $Window
        return
    }
    $text = $updateMessages.complete
    if ($Version) {
        $text = $text.Replace("{version}", "v" + $Version)
    } else {
        $text = $text.Replace(" {version}", "").Replace("{version}", "")
    }
    Set-StatusProgress -Percent 100
    # The app we have just restarted took the foreground, and that latched as
    # "the user switched away", so the last thing this window says - that the
    # update worked - would have been left unfocused and unread. This one
    # message is worth taking the focus back for; afterwards the latch closes
    # again by itself and the window gives the app its focus back when it goes.
    Reset-StatusFocusLatch -Stage "the update is complete"
    Update-StatusMessage -Window $Window -Message $text
    # Then get out of the way. A finished update is finished: this window has
    # no business staying on screen, and a Close button here only gave the
    # user something else to deal with before they could use the application.
    # The pause is just long enough for the message to be spoken.
    Wait-Pumped -Milliseconds $script:CompleteLingerMs -Window $Window
    # The restarted app should be what the user lands in, not whatever Windows
    # picks when this window disappears.
    Grant-ForegroundToNextProcess
    Close-StatusWindow -Window $Window
}

function Complete-FailedUpdate {
    param($Window, [string]$Reason, [int]$Code = 1, [string]$Kind = "other",
          $ExitCode = $null, [string]$InstallerLog = "")
    Write-Log "Update failed: $Reason"
    $installerError = ""
    if ($InstallerLog) {
        $installerError = Get-InstallerError -Path $InstallerLog
        if ($installerError) { Write-Log "Installer error: $installerError" }
    }
    Write-UpdateResult -Kind $Kind -Reason $Reason -ExitCode $ExitCode -InstallerError $installerError
    Reset-StatusFocusLatch -Stage "the update failed"
    Update-StatusMessage -Window $Window -Message $updateMessages.error
    $restarted = $false
    $oldExe = Join-Path $InstallDir $ExeName
    if (Test-Path -LiteralPath $oldExe) {
        Write-Log "Starting the existing app so it can report the failure: $oldExe"
        $restarted = Start-AppAfterUpdate -ExePath $oldExe -WorkDir $InstallDir -Arguments $RestartArgs -Window $Window
    }
    if (-not $restarted) {
        try {
            $text = $updateMessages.error + [Environment]::NewLine + [Environment]::NewLine + $logPath
            if ($Window) {
                [void][System.Windows.Forms.MessageBox]::Show($Window, $text, "Accessible IPTV Client", "OK", "Error")
            } else {
                Add-Type -AssemblyName System.Windows.Forms
                [void][System.Windows.Forms.MessageBox]::Show($text, "Accessible IPTV Client", "OK", "Error")
            }
        } catch {
            Write-Log "Could not show the failure message: $($_.Exception.Message)"
        }
    }
    Close-StatusWindow -Window $Window
    exit $Code
}

# The app writes these files; a half-written one is never read, because every
# write is a rename into place. A file being renamed over can still fail a read
# for an instant, so a failed read simply means "nothing new this time".
function Read-JsonFile {
    param([string]$Path)
    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) { return $null }
    try {
        $text = [System.IO.File]::ReadAllText($Path)
        if (-not $text) { return $null }
        return ($text | ConvertFrom-Json)
    } catch {
        return $null
    }
}

function Get-JsonValue {
    param($Object, [string]$Name)
    if (-not $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if (-not $property) { return $null }
    return $property.Value
}

# --- Attending the app (the window is up before the download starts) -------
# The update used to be two windows in a row: the app's own progress dialog
# while it downloaded, then this one for the install. The app has to exit
# half way, so the hand-over could never be seamless - and a screen-reader
# user experienced it as the update window disappearing. So this window is
# shown first and shows everything: the app reports its download progress into
# status.json, and only says what to install (command.json) once it is ready.
function Invoke-AttendApp {
    param($Window, [string]$StatusPath, [string]$CommandPath, [string]$CancelPath,
          [string]$CancelText = "Cancel")
    $lastWrite = $null
    while (-not (Test-Path -LiteralPath $CommandPath)) {
        try {
            $stamp = (Get-Item -LiteralPath $StatusPath -ErrorAction Stop).LastWriteTimeUtc
        } catch {
            $stamp = $null
        }
        if ($stamp -and $stamp -ne $lastWrite) {
            $lastWrite = $stamp
            $status = Read-JsonFile -Path $StatusPath
            if ($status) {
                $message = Get-JsonValue -Object $status -Name "message"
                if ($message) { Update-StatusMessage -Window $Window -Message ([string]$message) }
                Set-StatusProgress -Percent (Get-JsonValue -Object $status -Name "percent")
                $cancellable = [bool](Get-JsonValue -Object $status -Name "cancellable")
                if ($cancellable -and -not $script:CancelRequested) {
                    if ($script:StatusButtonAction -ne "cancel") {
                        Set-StatusButton -Action "cancel" -Text $CancelText
                    }
                } elseif ($script:StatusButtonAction -eq "cancel") {
                    Set-StatusButton -Action ""
                }
            }
        }
        if ($script:CancelRequested -and $CancelPath -and -not (Test-Path -LiteralPath $CancelPath)) {
            try {
                New-Item -ItemType File -Path $CancelPath -Force | Out-Null
                Write-Log "Told the app to cancel the update."
            } catch {
                Write-Log "Could not write the cancel file: $($_.Exception.Message)"
            }
        }
        if ($ParentPid -gt 0 -and -not (Get-Process -Id $ParentPid -ErrorAction SilentlyContinue)) {
            Write-Log "The app exited before it said what to install; nothing to do."
            return $null
        }
        Wait-Pumped -Milliseconds 150 -Window $Window
    }
    # The app renames the file into place, so it is complete when it appears;
    # a read can still lose a race with the rename itself.
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        $command = Read-JsonFile -Path $CommandPath
        if ($command) { return $command }
        Wait-Pumped -Milliseconds 100 -Window $Window
    }
    Write-Log "The command file could not be read: $CommandPath"
    return $null
}

# Sleep while keeping the status window painting and answering.
function Wait-Pumped {
    param([int]$Milliseconds, $Window)
    $deadline = (Get-Date).AddMilliseconds($Milliseconds)
    while ((Get-Date) -lt $deadline) {
        if ($Window) {
            try { [System.Windows.Forms.Application]::DoEvents() } catch { }
            Watch-StatusWindowFocus
        }
        Start-Sleep -Milliseconds 50
    }
}

# Wait for a process, pumping the status window, up to an optional cap.
function Wait-ForProcessExit {
    param($Process, $Window, [int]$TimeoutSeconds = 0)
    $deadline = if ($TimeoutSeconds -gt 0) { (Get-Date).AddSeconds($TimeoutSeconds) } else { $null }
    while (-not $Process.HasExited) {
        if ($deadline -and (Get-Date) -ge $deadline) { return $false }
        Wait-Pumped -Milliseconds 200 -Window $Window
    }
    return $true
}

function Close-StatusWindow {
    param($Window)
    $script:AllowStatusClose = $true
    if (-not $Window) { $Window = $script:StatusWindow }
    if (-not $Window) { return }
    try { $Window.Close(); $Window.Dispose() } catch { }
    $script:StatusWindow = $null
    $script:StatusLabel = $null
    $script:StatusProgress = $null
    $script:StatusButton = $null
}

# Leave the last word on screen long enough to be read, with a Close button so
# it can be dismissed sooner - or kept, if the user wants to read it twice.
function Wait-ForDismissal {
    param($Window, [int]$Milliseconds, [string]$ButtonText = "Close")
    $script:StatusDismissed = $false
    Set-StatusButton -Action "close" -Text $ButtonText
    $deadline = (Get-Date).AddMilliseconds($Milliseconds)
    while (-not $script:StatusDismissed -and (Get-Date) -lt $deadline) {
        Wait-Pumped -Milliseconds 100 -Window $Window
    }
    Set-StatusButton -Action ""
}

function Start-AppAfterUpdate {
    param(
        [string]$ExePath,
        [string]$WorkDir,
        [string]$Arguments = "",
        $Window = $null
    )

    # A silent restart failure is the worst outcome there is for a screen-reader
    # user: the update succeeded, the app is simply gone, and nothing on screen
    # says why. So every attempt is verified - a process that dies within a few
    # seconds counts as a failure, not a success - and the last resort hands the
    # launch to Explorer, which starts the app from the shell instead of from
    # this helper's own process tree.
    $crashed = $false
    for ($attempt = 1; $attempt -le 2; $attempt++) {
        $app = $null
        Grant-ForegroundToNextProcess
        try {
            $startArgs = @{
                FilePath         = $ExePath
                WorkingDirectory = $WorkDir
                PassThru         = $true
            }
            if ($Arguments) { $startArgs['ArgumentList'] = $Arguments }
            $app = Start-Process @startArgs
        } catch {
            Write-Log "Restart attempt $attempt could not launch the app: $($_.Exception.Message)"
        }
        if ($app) {
            # Long enough to get past DLL loading, where a broken install dies.
            for ($tick = 0; $tick -lt 20 -and -not $app.HasExited; $tick++) {
                Wait-Pumped -Milliseconds 250 -Window $Window
            }
            if (-not $app.HasExited) {
                Write-Log "App restarted (PID $($app.Id))."
                return $true
            }
            # 12 = single_instance.HANDED_OVER_EXIT_CODE: a copy of the app was
            # already running (the user reopened it), and this launch brought
            # that copy to the front instead of starting a second one.
            if ($app.ExitCode -eq 12) {
                Write-Log "The app was already running; the restart brought it to the front."
                return $true
            }
            Write-Log "Restart attempt $attempt exited immediately with code $($app.ExitCode)."
            $crashed = $true
        }
        Wait-Pumped -Milliseconds 2000 -Window $Window
    }

    # The app started and died (v1.147.1 crashed with 0xC0000409): launching it
    # again through Explorer only hides that, and the user heard "Update
    # complete" for an app that never opened. Say it could not start instead.
    if ($crashed) {
        Write-Log "Could not restart the app after the update: it exits as soon as it starts."
        return $false
    }

    try {
        Write-Log "Falling back to Explorer to start the app."
        Start-Process -FilePath "explorer.exe" -ArgumentList "`"$ExePath`""
        return $true
    } catch {
        Write-Log "Explorer fallback failed: $($_.Exception.Message)"
    }
    Write-Log "Could not restart the app after the update."
    return $false
}

$sessionStatusPath = ""
$sessionCommandPath = ""
$sessionCancelPath = ""
$newVersion = ""
$firstMessage = $updateMessages.prepare
if ($SessionDir) {
    $sessionStatusPath = Join-Path $SessionDir "status.json"
    $sessionCommandPath = Join-Path $SessionDir "command.json"
    $sessionCancelPath = Join-Path $SessionDir "cancel"
    # The app writes its first status before starting this helper, so the
    # window opens on the real first step rather than on a generic title.
    $firstStatus = Read-JsonFile -Path $sessionStatusPath
    $firstText = Get-JsonValue -Object $firstStatus -Name "message"
    if ($firstText) { $firstMessage = [string]$firstText }
}

$statusWindow = Show-UpdateStatus -Message $firstMessage

# The app holds its own progress dialog open until this file appears, so the
# two windows overlap and the screen is never empty. Written only once the
# window really is showing - PowerShell plus WinForms takes a second or two to
# start, and that gap is what used to look like the update window vanishing.
if ($ReadyFile) {
    try {
        New-Item -ItemType File -Path $ReadyFile -Force | Out-Null
        Write-Log "Signalled the app that the status window is up: $ReadyFile"
    } catch {
        Write-Log "Could not write the ready file: $($_.Exception.Message)"
    }
}

if ($SessionDir) {
    $command = Invoke-AttendApp -Window $statusWindow -StatusPath $sessionStatusPath `
        -CommandPath $sessionCommandPath -CancelPath $sessionCancelPath `
        -CancelText $updateMessages.cancel
    if (-not $command) {
        # Either the app went away without asking for anything, or it asked in
        # a way this helper could not read. Nothing has been installed and
        # nothing is half-done, so simply take the window away again.
        Close-StatusWindow -Window $statusWindow
        exit 3
    }
    $action = [string](Get-JsonValue -Object $command -Name "action")
    if ($action -ne "install") {
        # The download was cancelled or failed. The app is still running and
        # stays running; this window says why and waits to be dismissed, so
        # the news does not need a second window of its own.
        $reason = [string](Get-JsonValue -Object $command -Name "message")
        if (-not $reason) { $reason = $updateMessages.error }
        Write-Log "The app stopped the update: $reason"
        Set-StatusProgress -Percent 0
        Reset-StatusFocusLatch -Stage "the update was stopped"
        Update-StatusMessage -Window $statusWindow -Message $reason
        Wait-ForDismissal -Window $statusWindow -Milliseconds 120000 -ButtonText $updateMessages.close
        Close-StatusWindow -Window $statusWindow
        exit 4
    }
    Set-StatusButton -Action ""
    Set-StatusProgress -Percent $null
    Reset-StatusFocusLatch -Stage "the install is starting"
    foreach ($pair in @(@("install_dir", "InstallDir"), @("exe_name", "ExeName"),
                        @("installer", "InstallerPath"), @("staging_dir", "StagingDir"),
                        @("backup_dir", "BackupDir"), @("restart_args", "RestartArgs"))) {
        $value = Get-JsonValue -Object $command -Name $pair[0]
        if ($value) { Set-Variable -Name $pair[1] -Value ([string]$value) -Scope Script }
    }
    $commandPid = Get-JsonValue -Object $command -Name "parent_pid"
    if ($commandPid) { $ParentPid = [int]$commandPid }
    $versionValue = Get-JsonValue -Object $command -Name "version"
    if ($versionValue) { $newVersion = [string]$versionValue }
    Write-Log "The app asked for the install: InstallDir=$InstallDir InstallerPath=$InstallerPath StagingDir=$StagingDir version=$newVersion"
    Update-StatusMessage -Window $statusWindow -Message $updateMessages.prepare
}

if (-not $InstallDir -or -not $ExeName) {
    Complete-FailedUpdate -Window $statusWindow -Kind "launch" -Reason "The update helper was not told what to install."
}

Write-Log "Updater started. Waiting for PID $ParentPid."

$deadline = (Get-Date).AddSeconds(30)
while ((Get-Process -Id $ParentPid -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) {
    Wait-Pumped -Milliseconds 500 -Window $statusWindow
}

$parentProcess = Get-Process -Id $ParentPid -ErrorAction SilentlyContinue
if ($parentProcess) {
    Write-Log "Process $ParentPid did not exit within timeout; terminating it."
    Stop-Process -Id $ParentPid -Force -ErrorAction SilentlyContinue
    Wait-Pumped -Milliseconds 1000 -Window $statusWindow
}

# The app's own window is gone now, and Windows hands focus to whatever is
# next in line - usually not this window, which is why the update seemed to
# vanish the moment the app closed (issue #30). Take focus once here, while
# the update is still the task the user is engaged with; after this,
# Watch-StatusWindowFocus respects the user moving elsewhere on purpose.
Focus-StatusWindow -Window $statusWindow -Stage "application closed"

# Kill any processes running from the install directory. The app itself is
# normally the only one, but a recording interrupted while FFmpeg was
# finalising can leave the bundled ffmpeg.exe alive after the app exits. That
# process holds its executable open on Windows, preventing an installer or
# portable directory-swap update from replacing it.
Write-Log "Scanning for processes locking $InstallDir..."
try {
    $targetProcessName = [System.IO.Path]::GetFileNameWithoutExtension($ExeName)
    $installPrefix = $InstallDir.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    # ffmpeg.exe is bundled alongside IPTVClient.exe (main.spec), so constrain
    # cleanup by the image path below; never terminate an unrelated FFmpeg.
    $targetProcessNames = @($targetProcessName, "ffmpeg") | Select-Object -Unique
    $candidateProcesses = Get-Process -Name $targetProcessNames -ErrorAction SilentlyContinue
    $zombies = $candidateProcesses | Where-Object {
        try {
            $_.MainModule.FileName.StartsWith($installPrefix, [System.StringComparison]::OrdinalIgnoreCase)
        } catch {
            $false
        }
    }
    foreach ($proc in $zombies) {
        if ($proc.Id -ne $PID -and $proc.Id -ne $ParentPid) {
            Write-Log "Stopping process locking the install directory: $($proc.Name) (PID $($proc.Id))"
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Wait-Pumped -Milliseconds 500 -Window $statusWindow
} catch {
    Write-Log "Warning: Failed to scan/kill zombie processes: $($_.Exception.Message)"
}

if ($InstallerPath) {
    if (-not (Test-Path -LiteralPath $InstallerPath)) {
        Complete-FailedUpdate -Window $statusWindow -Reason "Installer missing: $InstallerPath"
    }

    $installerLog = Join-Path $env:TEMP "AccessibleIPTVClient_installer.log"
    $installerArgs = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /LOG=`"$installerLog`" /DIR=`"$InstallDir`""
    Write-Log "Launching installer update: $InstallerPath $installerArgs"
    # Only announce a UAC prompt that will really appear. With UAC off, or set
    # to elevate administrators silently, the message promised a prompt that
    # never came.
    $promptExpected = Test-ElevationPromptExpected
    Write-Log "UAC prompt expected: $promptExpected"
    if ($promptExpected) {
        Update-StatusMessage -Window $statusWindow -Message $updateMessages.consent
    }
    $proc = $null
    try {
        # Program Files needs elevation. Start-Process -Verb RunAs gave the
        # consent request no owner window, and a hidden background process
        # asking without one gets a flashing taskbar button instead of the
        # UAC prompt - which a screen reader user never hears, so the update
        # sat there until the user gave up (issue #26). Owning the request
        # with the status window, which the app let us bring to the front,
        # puts the real prompt on screen.
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $InstallerPath
        $psi.Arguments = $installerArgs
        $psi.WorkingDirectory = $env:TEMP
        $psi.UseShellExecute = $true
        $psi.Verb = "runas"
        if ($statusWindow) {
            $psi.ErrorDialog = $true
            $psi.ErrorDialogParentHandle = $statusWindow.Handle
            try { $statusWindow.Activate() } catch { }
        }
        $proc = [System.Diagnostics.Process]::Start($psi)
    } catch {
        $inner = $_.Exception
        while ($inner.InnerException) { $inner = $inner.InnerException }
        if ($inner -is [System.ComponentModel.Win32Exception] -and $inner.NativeErrorCode -eq 1223) {
            Complete-FailedUpdate -Window $statusWindow -Kind "declined" -Reason "Permission to run the installer was declined."
        }
        Complete-FailedUpdate -Window $statusWindow -Kind "launch" -Reason "Failed to launch installer: $($inner.Message)"
    }
    if (-not $proc) {
        Complete-FailedUpdate -Window $statusWindow -Kind "launch" -Reason "The installer did not start."
    }
    Write-Log "Installer running (PID $($proc.Id)); its log is $installerLog"
    $script:UpdateOwnedPids += $proc.Id
    Update-StatusMessage -Window $statusWindow -Message $updateMessages.install

    # Pumped, and capped: a silent installer that never returns must still end
    # in a message rather than a status window that sits there for ever.
    if (-not (Wait-ForProcessExit -Process $proc -Window $statusWindow -TimeoutSeconds 900)) {
        Complete-FailedUpdate -Window $statusWindow -Kind "timeout" -InstallerLog $installerLog -Reason "Installer still running after 15 minutes; see $installerLog"
    }
    # Settle the process object so ExitCode is populated before it is read.
    try { $proc.WaitForExit() } catch { }
    $installerExit = $proc.ExitCode
    if ($installerExit -ne 0) {
        $meaning = if ($null -ne $installerExit -and $InnoExitCodes.ContainsKey([int]$installerExit)) { " " + $InnoExitCodes[[int]$installerExit] } else { "" }
        Complete-FailedUpdate -Window $statusWindow -Code ([int]$installerExit) -Kind "installer" -ExitCode $installerExit -InstallerLog $installerLog -Reason "Installer failed with exit code $installerExit.$meaning See $installerLog"
    }
    Write-Log "Installer finished successfully."

    $exePath = Join-Path $InstallDir $ExeName
    if (-not (Test-Path -LiteralPath $exePath)) {
        Complete-FailedUpdate -Window $statusWindow -Reason "Executable not found after installer update: $exePath"
    }
    Update-StatusMessage -Window $statusWindow -Message $updateMessages.start
    # Before the app starts, not after: it reports the update within
    # milliseconds of showing its window, and the restart below waits five
    # seconds proving the app survived. A result written after that race was
    # lost, and the new version opened its own "updated" box on top of this
    # window - the very box this window exists to replace.
    Write-UpdateSuccess -Version $newVersion
    Write-Log "Restarting app after installer update: $exePath"
    $restarted = Start-AppAfterUpdate -ExePath $exePath -WorkDir $InstallDir -Arguments $RestartArgs -Window $statusWindow
    Write-Log "Installer updater completed."
    Complete-SuccessfulUpdate -Window $statusWindow -Restarted $restarted -Version $newVersion
    if ($restarted) { exit 0 }
    exit 2
}

if (-not (Test-Path -LiteralPath $StagingDir)) {
    Complete-FailedUpdate -Window $statusWindow -Reason "Staging directory missing: $StagingDir"
}

$parentDir = Split-Path -Parent $InstallDir
if ($parentDir -and -not (Test-Path -LiteralPath $parentDir)) {
    New-Item -ItemType Directory -Path $parentDir | Out-Null
}

Update-StatusMessage -Window $statusWindow -Message $updateMessages.install

if (Test-Path -LiteralPath $BackupDir) {
    Remove-Item -LiteralPath $BackupDir -Recurse -Force
}

try {
    if (Test-Path -LiteralPath $InstallDir) {
        Move-Item -LiteralPath $InstallDir -Destination $BackupDir -Force
        Write-Log "Moved current install to backup: $BackupDir"
    }
} catch {
    Complete-FailedUpdate -Window $statusWindow -Reason "Failed to move install to backup: $($_.Exception.Message)"
}

try {
    Move-Item -LiteralPath $StagingDir -Destination $InstallDir -Force
    Write-Log "Installed update to $InstallDir"

    # Portable zip updates replace the app directory; preserve the local config
    # beside the new executable when the previous portable copy had one.
    $oldConfig = Join-Path $BackupDir "iptvclient.conf"
    $newConfig = Join-Path $InstallDir "iptvclient.conf"
    if ((Test-Path -LiteralPath $oldConfig) -and -not (Test-Path -LiteralPath $newConfig)) {
        try {
            Copy-Item -LiteralPath $oldConfig -Destination $newConfig -Force
            Write-Log "Preserved portable configuration in install directory."
        } catch {
            Write-Log "Failed to preserve portable configuration: $($_.Exception.Message)"
        }
    }

    # Preserve pre-portable AppData configs as a fallback for users updating
    # from builds that still stored portable settings in the roaming profile.
    $roamingDir = Join-Path $env:APPDATA "AccessibleIPTVClient"
    $roamingConfig = Join-Path $roamingDir "iptvclient.conf"
    if ((Test-Path -LiteralPath $roamingConfig) -and -not (Test-Path -LiteralPath $newConfig)) {
        try {
            Copy-Item -LiteralPath $roamingConfig -Destination $newConfig -Force
            Write-Log "Migrated roaming configuration to portable install directory."
        } catch {
            Write-Log "Failed to migrate configuration: $($_.Exception.Message)"
        }
    }
} catch {
    Write-Log "Failed to move staging into place: $($_.Exception.Message)"
    if ((Test-Path -LiteralPath $BackupDir) -and -not (Test-Path -LiteralPath $InstallDir)) {
        try {
            Move-Item -LiteralPath $BackupDir -Destination $InstallDir -Force
            Write-Log "Rollback completed."
        } catch {
            Write-Log "Rollback failed: $($_.Exception.Message)"
        }
    }
    Complete-FailedUpdate -Window $statusWindow -Reason "Could not put the update in place."
}

$exePath = Join-Path $InstallDir $ExeName
if (-not (Test-Path -LiteralPath $exePath)) {
    Write-Log "Executable not found after update: $exePath"
    if (Test-Path -LiteralPath $BackupDir) {
        try {
            Remove-Item -LiteralPath $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
            Move-Item -LiteralPath $BackupDir -Destination $InstallDir -Force
            Write-Log "Rolled back to previous version because the new executable was missing."
        } catch {
            Write-Log "Rollback failed: $($_.Exception.Message)"
        }
    }
    Complete-FailedUpdate -Window $statusWindow -Reason "The updated executable was missing."
}

# Clear the backup before restarting, not after. A recursive delete of a
# directory tree right beside the install is heavy disk work, and it used to run
# while the freshly started app was still loading its own DLLs out of that same
# install directory.
if (Test-Path -LiteralPath $BackupDir) {
    try {
        Write-Log "Removing backup directory: $BackupDir"
        Remove-Item -LiteralPath $BackupDir -Recurse -Force -ErrorAction Stop
        Write-Log "Backup directory removed successfully."
    } catch {
        Write-Log "Failed to remove backup directory: $($_.Exception.Message)"
    }
}

Update-StatusMessage -Window $statusWindow -Message $updateMessages.start
# See the installer path: the result must be on disk before the app reads it.
Write-UpdateSuccess -Version $newVersion
Write-Log "Restarting app: $exePath"
$restarted = Start-AppAfterUpdate -ExePath $exePath -WorkDir $InstallDir -Arguments $RestartArgs -Window $statusWindow

Write-Log "Updater completed."
Complete-SuccessfulUpdate -Window $statusWindow -Restarted $restarted -Version $newVersion
if ($restarted) { exit 0 }
exit 2

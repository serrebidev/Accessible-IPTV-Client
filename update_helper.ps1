param(
    [Parameter(Mandatory = $true)]
    [int]$ParentPid,
    [Parameter(Mandatory = $true)]
    [string]$InstallDir,
    [string]$StagingDir = "",
    [string]$BackupDir = "",
    [string]$InstallerPath = "",
    [Parameter(Mandatory = $true)]
    [string]$ExeName,
    [string]$RestartArgs = "",
    [string]$ReadyFile = "",
    [string]$Language = "en"
)

Set-Location $env:TEMP
$logPath = Join-Path $env:TEMP "AccessibleIPTVClient_update.log"

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
    "install": "Installing the update. This can take a minute; please leave this window open.",
    "start": "Starting the updated application...",
    "error": "The update did not finish. Please try again from the Help menu in the application."
  },
  "es": {
    "prepare": "Preparando la actualizaci\u00f3n. La aplicaci\u00f3n se est\u00e1 cerrando; la instalaci\u00f3n comenzar\u00e1 en cuanto se cierre.",
    "install": "Instalando la actualizaci\u00f3n. Esto puede tardar un minuto; deje esta ventana abierta.",
    "start": "Iniciando la versi\u00f3n actualizada de la aplicaci\u00f3n...",
    "error": "La actualizaci\u00f3n no termin\u00f3. Int\u00e9ntelo de nuevo desde el men\u00fa Ayuda de la aplicaci\u00f3n."
  },
  "ar": {
    "prepare": "\u062c\u0627\u0631\u064d \u062a\u062d\u0636\u064a\u0631 \u0627\u0644\u062a\u062d\u062f\u064a\u062b. \u064a\u062a\u0645 \u0625\u063a\u0644\u0627\u0642 \u0627\u0644\u062a\u0637\u0628\u064a\u0642\u061b \u0633\u064a\u0628\u062f\u0623 \u0627\u0644\u062a\u062b\u0628\u064a\u062a \u0628\u0645\u062c\u0631\u062f \u0625\u063a\u0644\u0627\u0642\u0647.",
    "install": "\u062c\u0627\u0631\u064d \u062a\u062b\u0628\u064a\u062a \u0627\u0644\u062a\u062d\u062f\u064a\u062b. \u0642\u062f \u064a\u0633\u062a\u063a\u0631\u0642 \u0630\u0644\u0643 \u062f\u0642\u064a\u0642\u0629\u061b \u064a\u064f\u0631\u062c\u0649 \u062a\u0631\u0643 \u0647\u0630\u0647 \u0627\u0644\u0646\u0627\u0641\u0630\u0629 \u0645\u0641\u062a\u0648\u062d\u0629.",
    "start": "\u062c\u0627\u0631\u064d \u062a\u0634\u063a\u064a\u0644 \u0627\u0644\u0625\u0635\u062f\u0627\u0631 \u0627\u0644\u0645\u062d\u062f\u0651\u062b \u0645\u0646 \u0627\u0644\u062a\u0637\u0628\u064a\u0642...",
    "error": "\u0644\u0645 \u064a\u0643\u062a\u0645\u0644 \u0627\u0644\u062a\u062d\u062f\u064a\u062b. \u064a\u064f\u0631\u062c\u0649 \u0627\u0644\u0645\u062d\u0627\u0648\u0644\u0629 \u0645\u0631\u0629 \u0623\u062e\u0631\u0649 \u0645\u0646 \u0642\u0627\u0626\u0645\u0629 \u0627\u0644\u0645\u0633\u0627\u0639\u062f\u0629 \u0641\u064a \u0627\u0644\u062a\u0637\u0628\u064a\u0642."
  },
  "pt": {
    "prepare": "Preparando a atualiza\u00e7\u00e3o. O aplicativo est\u00e1 sendo fechado; a instala\u00e7\u00e3o come\u00e7ar\u00e1 assim que ele for fechado.",
    "install": "Instalando a atualiza\u00e7\u00e3o. Isso pode levar um minuto; deixe esta janela aberta.",
    "start": "Iniciando o aplicativo atualizado...",
    "error": "A atualiza\u00e7\u00e3o n\u00e3o foi conclu\u00edda. Tente novamente pelo menu Ajuda do aplicativo."
  },
  "fr": {
    "prepare": "Pr\u00e9paration de la mise \u00e0 jour. L\u2019application est en cours de fermeture ; l\u2019installation commencera d\u00e8s qu\u2019elle sera ferm\u00e9e.",
    "install": "Installation de la mise \u00e0 jour. Cela peut prendre une minute ; veuillez laisser cette fen\u00eatre ouverte.",
    "start": "D\u00e9marrage de la version mise \u00e0 jour de l\u2019application...",
    "error": "La mise \u00e0 jour ne s\u2019est pas termin\u00e9e. R\u00e9essayez depuis le menu Aide de l\u2019application."
  },
  "de": {
    "prepare": "Das Update wird vorbereitet. Die Anwendung wird beendet; die Installation beginnt, sobald das Programm geschlossen ist.",
    "install": "Das Update wird installiert. Dies kann eine Minute dauern; bitte lassen Sie dieses Fenster ge\u00f6ffnet.",
    "start": "Die aktualisierte Anwendung wird gestartet...",
    "error": "Das Update wurde nicht abgeschlossen. Bitte versuchen Sie es \u00fcber das Hilfe-Men\u00fc der Anwendung erneut."
  },
  "ru": {
    "prepare": "\u041f\u043e\u0434\u0433\u043e\u0442\u043e\u0432\u043a\u0430 \u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u044f. \u041f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u0435 \u0437\u0430\u043a\u0440\u044b\u0432\u0430\u0435\u0442\u0441\u044f; \u0443\u0441\u0442\u0430\u043d\u043e\u0432\u043a\u0430 \u043d\u0430\u0447\u043d\u0451\u0442\u0441\u044f \u0441\u0440\u0430\u0437\u0443 \u043f\u043e\u0441\u043b\u0435 \u0437\u0430\u043a\u0440\u044b\u0442\u0438\u044f.",
    "install": "\u0423\u0441\u0442\u0430\u043d\u043e\u0432\u043a\u0430 \u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u044f. \u042d\u0442\u043e \u043c\u043e\u0436\u0435\u0442 \u0437\u0430\u043d\u044f\u0442\u044c \u043c\u0438\u043d\u0443\u0442\u0443; \u043e\u0441\u0442\u0430\u0432\u044c\u0442\u0435 \u044d\u0442\u043e \u043e\u043a\u043d\u043e \u043e\u0442\u043a\u0440\u044b\u0442\u044b\u043c.",
    "start": "\u0417\u0430\u043f\u0443\u0441\u043a \u043e\u0431\u043d\u043e\u0432\u043b\u0451\u043d\u043d\u043e\u0439 \u0432\u0435\u0440\u0441\u0438\u0438 \u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u044f...",
    "error": "\u041e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u0435 \u043d\u0435 \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u043e. \u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u0435 \u043f\u043e\u043f\u044b\u0442\u043a\u0443 \u0447\u0435\u0440\u0435\u0437 \u043c\u0435\u043d\u044e \u00ab\u0421\u043f\u0440\u0430\u0432\u043a\u0430\u00bb \u0432 \u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u0438."
  },
  "tr": {
    "prepare": "G\u00fcncelleme haz\u0131rlan\u0131yor. Uygulama kapan\u0131yor; kapand\u0131\u011f\u0131nda kurulum ba\u015flayacak.",
    "install": "G\u00fcncelleme y\u00fckleniyor. Bu i\u015flem bir dakika s\u00fcrebilir; l\u00fctfen bu pencereyi a\u00e7\u0131k b\u0131rak\u0131n.",
    "start": "G\u00fcncellenmi\u015f uygulama ba\u015flat\u0131l\u0131yor...",
    "error": "G\u00fcncelleme tamamlanamad\u0131. L\u00fctfen uygulamadaki Yard\u0131m men\u00fcs\u00fcnden yeniden deneyin."
  },
  "it": {
    "prepare": "Preparazione dell\u2019aggiornamento. L\u2019applicazione si sta chiudendo; l\u2019installazione inizier\u00e0 non appena sar\u00e0 chiusa.",
    "install": "Installazione dell\u2019aggiornamento. Potrebbe richiedere un minuto; lascia aperta questa finestra.",
    "start": "Avvio della versione aggiornata dell\u2019applicazione...",
    "error": "L\u2019aggiornamento non \u00e8 stato completato. Riprova dal menu Aiuto dell\u2019applicazione."
  },
  "pl": {
    "prepare": "Przygotowywanie aktualizacji. Program jest zamykany; instalacja rozpocznie si\u0119 zaraz po jego zamkni\u0119ciu.",
    "install": "Instalowanie aktualizacji. Mo\u017ce to potrwa\u0107 minut\u0119; pozostaw to okno otwarte.",
    "start": "Uruchamianie zaktualizowanej wersji programu...",
    "error": "Aktualizacja nie zosta\u0142a uko\u0144czona. Spr\u00f3buj ponownie z menu Pomoc w aplikacji."
  },
  "hi": {
    "prepare": "\u0905\u092a\u0921\u0947\u091f \u0915\u0940 \u0924\u0948\u092f\u093e\u0930\u0940 \u0939\u094b \u0930\u0939\u0940 \u0939\u0948\u0964 \u0910\u092a\u094d\u0932\u093f\u0915\u0947\u0936\u0928 \u092c\u0902\u0926 \u0939\u094b \u0930\u0939\u093e \u0939\u0948; \u0907\u0938\u0915\u0947 \u092c\u0902\u0926 \u0939\u094b\u0924\u0947 \u0939\u0940 \u0907\u0902\u0938\u094d\u091f\u0949\u0932\u0947\u0936\u0928 \u0936\u0941\u0930\u0942 \u0939\u094b \u091c\u093e\u090f\u0917\u093e\u0964",
    "install": "\u0905\u092a\u0921\u0947\u091f \u0907\u0902\u0938\u094d\u091f\u0949\u0932 \u0939\u094b \u0930\u0939\u093e \u0939\u0948\u0964 \u0907\u0938\u092e\u0947\u0902 \u090f\u0915 \u092e\u093f\u0928\u091f \u0932\u0917 \u0938\u0915\u0924\u093e \u0939\u0948; \u0915\u0943\u092a\u092f\u093e \u0907\u0938 \u0935\u093f\u0902\u0921\u094b \u0915\u094b \u0916\u0941\u0932\u093e \u091b\u094b\u0921\u093c \u0926\u0947\u0902\u0964",
    "start": "\u0905\u092a\u0921\u0947\u091f \u0915\u093f\u092f\u093e \u0917\u092f\u093e \u0910\u092a\u094d\u0932\u093f\u0915\u0947\u0936\u0928 \u0936\u0941\u0930\u0942 \u0939\u094b \u0930\u0939\u093e \u0939\u0948...",
    "error": "\u0905\u092a\u0921\u0947\u091f \u092a\u0942\u0930\u093e \u0928\u0939\u0940\u0902 \u0939\u0941\u0906\u0964 \u0915\u0943\u092a\u092f\u093e \u0910\u092a \u0915\u0947 \u0938\u0939\u093e\u092f\u0924\u093e \u092e\u0947\u0928\u0942 \u0938\u0947 \u092b\u093f\u0930 \u0938\u0947 \u092a\u094d\u0930\u092f\u093e\u0938 \u0915\u0930\u0947\u0902\u0964"
  },
  "zh": {
    "prepare": "\u6b63\u5728\u51c6\u5907\u66f4\u65b0\u3002\u5e94\u7528\u7a0b\u5e8f\u6b63\u5728\u5173\u95ed\uff1b\u5173\u95ed\u540e\u5c06\u7acb\u5373\u5f00\u59cb\u5b89\u88c5\u3002",
    "install": "\u6b63\u5728\u5b89\u88c5\u66f4\u65b0\u3002\u8fd9\u53ef\u80fd\u9700\u8981\u4e00\u5206\u949f\uff1b\u8bf7\u4fdd\u6301\u6b64\u7a97\u53e3\u6253\u5f00\u3002",
    "start": "\u6b63\u5728\u542f\u52a8\u66f4\u65b0\u540e\u7684\u5e94\u7528\u7a0b\u5e8f...",
    "error": "\u66f4\u65b0\u672a\u5b8c\u6210\u3002\u8bf7\u4ece\u5e94\u7528\u7a0b\u5e8f\u7684\u201c\u5e2e\u52a9\u201d\u83dc\u5355\u91cd\u8bd5\u3002"
  },
  "ja": {
    "prepare": "\u66f4\u65b0\u3092\u6e96\u5099\u3057\u3066\u3044\u307e\u3059\u3002\u30a2\u30d7\u30ea\u30b1\u30fc\u30b7\u30e7\u30f3\u3092\u7d42\u4e86\u3057\u3066\u3044\u307e\u3059\u3002\u7d42\u4e86\u5f8c\u3059\u3050\u306b\u30a4\u30f3\u30b9\u30c8\u30fc\u30eb\u3092\u958b\u59cb\u3057\u307e\u3059\u3002",
    "install": "\u66f4\u65b0\u3092\u30a4\u30f3\u30b9\u30c8\u30fc\u30eb\u3057\u3066\u3044\u307e\u3059\u30021 \u5206\u307b\u3069\u304b\u304b\u308b\u5834\u5408\u304c\u3042\u308a\u307e\u3059\u3002\u3053\u306e\u30a6\u30a3\u30f3\u30c9\u30a6\u306f\u958b\u3044\u305f\u307e\u307e\u306b\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
    "start": "\u66f4\u65b0\u3055\u308c\u305f\u30a2\u30d7\u30ea\u30b1\u30fc\u30b7\u30e7\u30f3\u3092\u8d77\u52d5\u3057\u3066\u3044\u307e\u3059...",
    "error": "\u66f4\u65b0\u304c\u5b8c\u4e86\u3057\u307e\u305b\u3093\u3067\u3057\u305f\u3002\u30a2\u30d7\u30ea\u30b1\u30fc\u30b7\u30e7\u30f3\u306e\uff3b\u30d8\u30eb\u30d7\uff3d\u30e1\u30cb\u30e5\u30fc\u304b\u3089\u3082\u3046\u4e00\u5ea6\u304a\u8a66\u3057\u304f\u3060\u3055\u3044\u3002"
  },
  "hu": {
    "prepare": "A friss\u00edt\u00e9s el\u0151k\u00e9sz\u00edt\u00e9se folyamatban van. Az alkalmaz\u00e1s bez\u00e1rul; a telep\u00edt\u00e9s a bez\u00e1r\u00e1s ut\u00e1n azonnal elindul.",
    "install": "A friss\u00edt\u00e9s telep\u00edt\u00e9se folyamatban van. Ez k\u00f6r\u00fclbel\u00fcl egy percig tarthat; hagyja nyitva ezt az ablakot.",
    "start": "A friss\u00edtett alkalmaz\u00e1s ind\u00edt\u00e1sa...",
    "error": "A friss\u00edt\u00e9s nem fejez\u0151d\u00f6tt be. Pr\u00f3b\u00e1lja \u00fajra az alkalmaz\u00e1s S\u00fag\u00f3 men\u00fcj\u00e9b\u0151l."
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
            error = "The update did not finish. Please try again from the Help menu in the application."
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
    $form.ShowInTaskbar = $true
    $form.TopMost = $true

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

    try {
        $form.Show()
        $form.Activate()
        [System.Windows.Forms.Application]::DoEvents()
    } catch { }
    return $form
}

function Update-StatusMessage {
    param($Window, [string]$Message)
    if (-not $Window) { return }
    try {
        $Window.Controls["StatusLabel"].Text = $Message
        # The title carries the same text so NVDA+T reports where the update
        # has got to, and so the taskbar button is not just "Updating...".
        $Window.Text = "Accessible IPTV Client - $Message"
        $Window.Refresh()
        [System.Windows.Forms.Application]::DoEvents()
    } catch {
        Write-Log "Status window update failed: $($_.Exception.Message)"
    }
}

# Sleep while keeping the status window painting and answering.
function Wait-Pumped {
    param([int]$Milliseconds, $Window)
    $deadline = (Get-Date).AddMilliseconds($Milliseconds)
    while ((Get-Date) -lt $deadline) {
        if ($Window) {
            try { [System.Windows.Forms.Application]::DoEvents() } catch { }
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
    if (-not $Window) { return }
    try { $Window.Close(); $Window.Dispose() } catch { }
}

function Write-Log {
    param([string]$Message)
    $stamp = (Get-Date).ToString("o")
    Add-Content -Path $logPath -Value "$stamp $Message"
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
    for ($attempt = 1; $attempt -le 2; $attempt++) {
        $app = $null
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
            Write-Log "Restart attempt $attempt exited immediately with code $($app.ExitCode)."
        }
        Wait-Pumped -Milliseconds 2000 -Window $Window
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

$statusWindow = Show-UpdateStatus -Message $updateMessages.prepare

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

# Kill any processes running from the install directory.
Write-Log "Scanning for processes locking $InstallDir..."
try {
    $targetProcessName = [System.IO.Path]::GetFileNameWithoutExtension($ExeName)
    $installPrefix = $InstallDir.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    $candidateProcesses = Get-Process -Name $targetProcessName -ErrorAction SilentlyContinue
    $zombies = $candidateProcesses | Where-Object {
        try {
            $_.MainModule.FileName.StartsWith($installPrefix, [System.StringComparison]::OrdinalIgnoreCase)
        } catch {
            $false
        }
    }
    foreach ($proc in $zombies) {
        if ($proc.Id -ne $PID -and $proc.Id -ne $ParentPid) {
            Write-Log "Killing zombie process: $($proc.Name) (PID $($proc.Id))"
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Wait-Pumped -Milliseconds 500 -Window $statusWindow
} catch {
    Write-Log "Warning: Failed to scan/kill zombie processes: $($_.Exception.Message)"
}

if ($InstallerPath) {
    if (-not (Test-Path -LiteralPath $InstallerPath)) {
        Write-Log "Installer missing: $InstallerPath"
        Close-StatusWindow -Window $statusWindow
        exit 1
    }

    Write-Log "Launching installer update: $InstallerPath"
    Update-StatusMessage -Window $statusWindow -Message $updateMessages.install
    $installerArgs = @(
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/SP-",
        "/DIR=`"$InstallDir`""
    )
    try {
        # -PassThru without -Wait, then a pumped wait: -Wait blocks this whole
        # thread, and a blocked thread cannot keep the status window alive for
        # the minute or so the installer takes. The message it shows is set
        # before the launch, not after, for the same reason.
        $proc = Start-Process -FilePath $InstallerPath -ArgumentList $installerArgs -Verb RunAs -PassThru
        [void](Wait-ForProcessExit -Process $proc -Window $statusWindow)
        # Settle the process object so ExitCode is populated before it is read.
        try { $proc.WaitForExit() } catch { }
        if ($proc.ExitCode -ne 0) {
            Write-Log "Installer failed with exit code $($proc.ExitCode)."
            Update-StatusMessage -Window $statusWindow -Message $updateMessages.error
            Wait-Pumped -Milliseconds 10000 -Window $statusWindow
            Close-StatusWindow -Window $statusWindow
            exit $proc.ExitCode
        }
    } catch {
        Write-Log "Failed to launch installer: $($_.Exception.Message)"
        Update-StatusMessage -Window $statusWindow -Message $updateMessages.error
        Wait-Pumped -Milliseconds 10000 -Window $statusWindow
        Close-StatusWindow -Window $statusWindow
        exit 1
    }

    $exePath = Join-Path $InstallDir $ExeName
    if (Test-Path -LiteralPath $exePath) {
        Update-StatusMessage -Window $statusWindow -Message $updateMessages.start
        Write-Log "Restarting app after installer update: $exePath"
        $restarted = Start-AppAfterUpdate -ExePath $exePath -WorkDir $InstallDir -Arguments $RestartArgs -Window $statusWindow
        Write-Log "Installer updater completed."
        Close-StatusWindow -Window $statusWindow
        if ($restarted) { exit 0 }
        exit 2
    }

    Update-StatusMessage -Window $statusWindow -Message $updateMessages.error
    Wait-Pumped -Milliseconds 10000 -Window $statusWindow
    Close-StatusWindow -Window $statusWindow
    Write-Log "Executable not found after installer update: $exePath"
    exit 1
}

if (-not (Test-Path -LiteralPath $StagingDir)) {
    Write-Log "Staging directory missing: $StagingDir"
    Close-StatusWindow -Window $statusWindow
    exit 1
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
        Write-Log "Failed to move install to backup: $($_.Exception.Message)"
        Update-StatusMessage -Window $statusWindow -Message $updateMessages.error
        Wait-Pumped -Milliseconds 10000 -Window $statusWindow
        Close-StatusWindow -Window $statusWindow
        exit 1
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
    Update-StatusMessage -Window $statusWindow -Message $updateMessages.error
    Wait-Pumped -Milliseconds 10000 -Window $statusWindow
    Close-StatusWindow -Window $statusWindow
    exit 1
}

$exePath = Join-Path $InstallDir $ExeName
if (-not (Test-Path -LiteralPath $exePath)) {
    Update-StatusMessage -Window $statusWindow -Message $updateMessages.error
    Wait-Pumped -Milliseconds 10000 -Window $statusWindow
    Close-StatusWindow -Window $statusWindow
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
    Close-StatusWindow -Window $statusWindow
    exit 1
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
Write-Log "Restarting app: $exePath"
$restarted = Start-AppAfterUpdate -ExePath $exePath -WorkDir $InstallDir -Arguments $RestartArgs -Window $statusWindow

Write-Log "Updater completed."
Close-StatusWindow -Window $statusWindow
if ($restarted) { exit 0 }
exit 2

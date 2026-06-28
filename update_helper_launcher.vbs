Set WshShell = CreateObject("WScript.Shell")
Set objArgs = WScript.Arguments

Function QuoteArg(value)
    QuoteArg = """" & Replace(value, """", """""") & """"
End Function

' Build PowerShell command with all parameters
psPath = objArgs(0)
params = ""
For i = 1 To objArgs.Count - 1
    params = params & " " & QuoteArg(objArgs(i))
Next

' Launch PowerShell hidden
WshShell.Run "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File " & QuoteArg(psPath) & params, 0, False

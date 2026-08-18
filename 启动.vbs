Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
appDir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = appDir

' Prefer Python 3.11 (deps are installed there; default pythonw may be 3.12)
pythonw = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe")
If fso.FileExists(pythonw) Then
  shell.Run """" & pythonw & """ """ & appDir & "\main.py""", 0, False
Else
  ' Fallback: show console so py launcher errors are visible
  shell.Run "py -3.11 """ & appDir & "\main.py""", 1, False
End If

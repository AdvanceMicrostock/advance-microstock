@echo off
setlocal
cd /d "%~dp0"

set "APPDIR=%~dp0"
set "TARGET="
if exist "Metadata_Embedder.exe" (
    set "TARGET=%~dp0Metadata_Embedder.exe"
) else if exist "Start_App.bat" (
    set "TARGET=%~dp0Start_App.bat"
)

if not defined TARGET (
    echo Neither Metadata_Embedder.exe nor Start_App.bat was found in this folder.
    echo Put this file in the app folder and run it again.
    pause
    exit /b 1
)

set "ICON="
if /i "%TARGET:~-4%"==".exe" (
    set "ICON=%TARGET%"
) else (
    for %%I in (*.ico) do if not defined ICON set "ICON=%%~fI"
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws=New-Object -ComObject WScript.Shell; $dirs=@([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Programs')); foreach($d in $dirs){ $s=$ws.CreateShortcut((Join-Path $d 'Metadata Embedder.lnk')); $s.TargetPath=$env:TARGET; $s.WorkingDirectory=$env:APPDIR; $s.WindowStyle=7; if($env:ICON){ $s.IconLocation=$env:ICON }; $s.Save() }"

if errorlevel 1 (
    echo.
    echo Could not create the shortcuts.
    pause
    exit /b 1
)

echo.
echo Done! "Metadata Embedder" shortcut created on your Desktop and in the Start Menu.
echo Target: %TARGET%
echo.
pause

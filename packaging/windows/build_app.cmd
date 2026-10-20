@echo off
setlocal enableextensions
REM Build natif du setup Windows debriefMeet (appele depuis build_app_windows_vm.sh).
REM Ne pas executer manuellement - necessite BUILD_INFO (rsync du script Mac, docs/32).
REM
REM Deux variables d'environnement, optionnelles, pour GitHub Actions (docs/52) :
REM   BUILD_DIR   racine des sources (defaut : le dossier de la VM Proxmox) ;
REM   PYTHON_EXE  interpreteur Python 3.13 (defaut : le py launcher de la VM ;
REM               sur un runner, actions/setup-python met "python" dans le PATH).
if not defined BUILD_DIR set "BUILD_DIR=C:\Users\sylvaing\build\debrief-meet"
if not defined PYTHON_EXE set "PYTHON_EXE=py -3.13"
cd /d "%BUILD_DIR%"
if errorlevel 1 ( echo ERREUR : impossible de cd vers %BUILD_DIR% & goto :error )
echo [build_app.cmd] Repertoire : %CD%

REM Un seul build depuis docs/45 (plus d'argument edition — les editions complete/lite
REM de docs/44 ont disparu, le mode distant/local est un reglage utilisateur).

echo [1/6] Creation du venv Python 3.13...
if exist .venv-build ( rmdir /s /q .venv-build )
%PYTHON_EXE% -m venv .venv-build
if errorlevel 1 goto :error
call .venv-build\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 goto :error
REM Crochets non quotes : `[` et `]` ne sont pas speciaux pour cmd.exe (ils le
REM seraient en PowerShell/zsh) -- ne pas "corriger" en ajoutant des quotes.
python -m pip install -e .[windows,dev]
if errorlevel 1 goto :error
python -m pip install pyinstaller
if errorlevel 1 goto :error

echo [2/6] Telechargement/verification ffmpeg (lgpl, cache VM)...
call packaging\windows\telecharger_ffmpeg.cmd
if errorlevel 1 goto :error

echo [3/6] Generation de la version (_version.py + version.iss)...
REM Avant pytest [4/6] : le spec et le .iss lisent les fichiers generes ici.
python packaging\windows\generer_version.py --build-info BUILD_INFO
if errorlevel 1 goto :error

echo [4/6] Suite de tests (bloquant - build refuse si rouge, docs/32)...
REM Hors gate produit Windows :
REM - test_benchmark_* / test_spike_backends_* : importent benchmark/ et spike/
REM   (outils internes, non synchronises sur la VM) ;
REM - test_build.py : hygiene du DEPOT (Makefile, setup.sh, README, audio du
REM   benchmark) -- ces fichiers ne font pas partie du produit ni du sync VM.
python -m pytest -m "not integration" --ignore-glob="tests/test_benchmark_*.py" --ignore-glob="tests/test_spike_backends_*.py" --ignore=tests/test_build.py
if errorlevel 1 goto :error

echo [5/6] PyInstaller (onedir)...
pyinstaller packaging\windows\debriefMeet.spec --noconfirm --distpath dist --workpath build\work
if errorlevel 1 goto :error

echo [6/6] Inno Setup...
if not defined ISCC_EXE (
    REM Emplacement selon le mode d'installation : machine (Program Files) ou
    REM utilisateur (AppData\Local\Programs — cas d'un `winget install --scope user`).
    if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
        set "ISCC_EXE=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    ) else if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" (
        set "ISCC_EXE=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
    )
)
if not exist "%ISCC_EXE%" (
    echo ERREUR : ISCC.exe introuvable ^(cherche dans Program Files et %%LOCALAPPDATA%%^)
    echo   Installer Inno Setup 6 ^(winget install JRSoftware.InnoSetup^) ou definir ISCC_EXE.
    goto :error
)
"%ISCC_EXE%" packaging\windows\debriefMeet.iss
if errorlevel 1 goto :error

echo RC=0 > build_app.done
echo.
echo === Build termine avec succes ===
exit /b 0

:error
set ERR=%errorlevel%
echo RC=%ERR% > build_app.done
echo === ECHEC build (RC=%ERR%) ===
exit /b %ERR%

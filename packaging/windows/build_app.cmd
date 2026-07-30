@echo off
setlocal enableextensions
REM Build natif du setup Windows debriefMeet (appele depuis build_app_windows_vm.sh).
REM Ne pas executer manuellement - necessite BUILD_INFO (rsync du script Mac, docs/32).
set VM_DIR=C:\Users\sylvaing\build\debrief-meet
cd /d %VM_DIR%
if errorlevel 1 ( echo ERREUR : impossible de cd vers %VM_DIR% & goto :error )
echo [build_app.cmd] Repertoire : %CD%

REM Argument 1 (optionnel) : edition compilee -- "complete" (defaut) ou "lite".
REM lite = sans transcription locale, extra pip windows-lite (docs/44). Passe en
REM argument et non par variable d'environnement : un `set` dans un `cmd /c` ne
REM survit pas au `cmd /c` suivant a travers ssh, et l'argument apparait dans le log.
REM PIEGE (diagnostique le 2026-07-30) : `%~1` ne retire que des guillemets APPARIES.
REM Via ssh, Windows OpenSSH enveloppe la commande recue dans un SECOND `cmd /c` et son
REM guillemet fermant fuit dans le dernier argument -> %1 vaut `lite"`, et le
REM `if "%EDITION%"==""` suivant devient `if "lite"""==""` : "La syntaxe de la commande
REM n'est pas correcte". D'ou le retrait explicite de tout guillemet.
REM `if defined` plutot que `if "%VAR%"==""` : insensible aux guillemets parasites.
REM La substitution %VAR:"=% n'est PAS expansee sur une variable non definie (cmd laisse
REM le texte litteral, ce qui casse la ligne suivante) -> toujours la garder derriere
REM `if defined`.
set EDITION=%~1
if defined EDITION set EDITION=%EDITION:"=%
if not defined EDITION set EDITION=complete
REM Ifs plats (pas de chaine if/else if/else) : meme style que le reste du fichier,
REM et un seul bloc parenthese, plus robuste a lire comme a parser.
set EXTRA=
if /i "%EDITION%"=="complete" set EXTRA=windows
if /i "%EDITION%"=="lite" set EXTRA=windows-lite
if not defined EXTRA (
    echo ERREUR : edition inconnue "%EDITION%" ^(attendu : complete ou lite^)
    goto :error
)
echo [build_app.cmd] Edition : %EDITION% ^(extra pip : %EXTRA%^)

echo [1/6] Creation du venv Python 3.13...
if exist .venv-build ( rmdir /s /q .venv-build )
py -3.13 -m venv .venv-build
if errorlevel 1 goto :error
call .venv-build\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 goto :error
REM Crochets non quotes : `[` et `]` ne sont pas speciaux pour cmd.exe (ils le
REM seraient en PowerShell/zsh) -- ne pas "corriger" en ajoutant des quotes.
python -m pip install -e .[%EXTRA%,dev]
if errorlevel 1 goto :error
python -m pip install pyinstaller
if errorlevel 1 goto :error

echo [2/6] Telechargement/verification ffmpeg (lgpl, cache VM)...
call packaging\windows\telecharger_ffmpeg.cmd
if errorlevel 1 goto :error

echo [3/6] Generation de la version + edition (_version.py + version.iss)...
REM Doit passer AVANT pytest [4/6] : le spec, le .iss et core/edition.py lisent tous
REM les fichiers generes ici -- la gate de tests tourne donc dans l'edition construite.
python packaging\windows\generer_version.py --build-info BUILD_INFO --edition %EDITION%
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

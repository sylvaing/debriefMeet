@echo off
setlocal enabledelayedexpansion
REM Telecharge/verifie ffmpeg.exe (build BtbN, variante lgpl statique) sur la VM,
REM le met en cache, et le copie dans packaging\windows\ffmpeg\ pour le spec
REM PyInstaller (docs/41). Idempotent et rejouable : appele par build_app.cmd.
REM
REM Le binaire n'est JAMAIS commite dans le depot (~100 Mo) - telecharge ici,
REM au moment du build, et verifie par SHA256.

REM ── URL epinglee sur un tag date (pas releases/latest, SHA instable) ──────────
REM ATTENTION : BtbN PURGE ses autobuilds dates au bout de quelques semaines — le
REM build du 2026-07-12 epingle ici repondait 404 le 2026-10-20 (constate par la CI,
REM docs/52 §9 ; la VM ne s'en apercevait pas, elle a le zip en cache). Le meme zip,
REM renomme %ZIP_NAME%, est donc MIROITE dans la release GitHub `outils-build` du depot
REM debriefMeet : la CI le depose dans le cache avant d'appeler ce script, qui ne
REM retombe sur l'URL BtbN qu'en l'absence du zip. Re-epingler = mettre a jour l'URL,
REM le SHA256 ET l'asset de la release miroir (docs/52 §5).
set FFMPEG_URL=https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-10-20-13-08/ffmpeg-n8.1.3-18-g46d899d7a0-win64-lgpl-8.1.zip
set FFMPEG_SHA256=26634a5e06429c4f51ed08ba518923f928c5e4a49ed0ee62f701e035227b91a7

REM FFMPEG_CACHE_DIR (optionnel) : emplacement du zip en cache — sur GitHub Actions
REM c'est un dossier restaure par actions/cache (docs/52), sur la VM le defaut.
if not defined FFMPEG_CACHE_DIR set "FFMPEG_CACHE_DIR=C:\Users\sylvaing\build\ffmpeg-cache"
set "CACHE_DIR=%FFMPEG_CACHE_DIR%"
set DEST_DIR=%~dp0ffmpeg
set ZIP_NAME=ffmpeg-win64-lgpl.zip

if not exist "%CACHE_DIR%" mkdir "%CACHE_DIR%"
if not exist "%DEST_DIR%" mkdir "%DEST_DIR%"

REM ── 1. Deja en place (marqueur SHA) → sortie rapide ───────────────────────────
if exist "%DEST_DIR%\ffmpeg.exe" (
    if exist "%DEST_DIR%\ffmpeg.sha256" (
        findstr /i /c:"%FFMPEG_SHA256%" "%DEST_DIR%\ffmpeg.sha256" >nul
        if not errorlevel 1 (
            echo [telecharger_ffmpeg] Deja en place ^(%DEST_DIR%\ffmpeg.exe^), SHA256 verifie.
            exit /b 0
        )
    )
)

REM ── 2. Telechargement (cache) ──────────────────────────────────────────────────
set ZIP_PATH=%CACHE_DIR%\%ZIP_NAME%
if not exist "%ZIP_PATH%" (
    echo [telecharger_ffmpeg] Telechargement de %FFMPEG_URL% ...
    curl.exe -L --fail -o "%ZIP_PATH%" "%FFMPEG_URL%"
    if errorlevel 1 (
        echo ERREUR : telechargement ffmpeg echoue.
        del /q "%ZIP_PATH%" 2>nul
        exit /b 1
    )
) else (
    echo [telecharger_ffmpeg] Zip deja en cache : %ZIP_PATH%
)

REM ── 3. Verification SHA256 ─────────────────────────────────────────────────────
set HASH=
set LIGNE_NUM=0
for /f "skip=1 delims=" %%H in ('certutil -hashfile "%ZIP_PATH%" SHA256') do (
    if !LIGNE_NUM! equ 0 (
        set "HASH=%%H"
        set /a LIGNE_NUM=1
    )
)
set "HASH=%HASH: =%"
for %%A in ("%HASH%") do set "HASH=%%~A"

if /i not "%HASH%"=="%FFMPEG_SHA256%" (
    echo ERREUR : SHA256 du zip ffmpeg ne correspond pas.
    echo   attendu  : %FFMPEG_SHA256%
    echo   obtenu   : %HASH%
    del /q "%ZIP_PATH%" 2>nul
    exit /b 1
)
echo [telecharger_ffmpeg] SHA256 verifie : %HASH%

REM ── 4. Extraction (bsdtar natif Windows 10+, lit les .zip) ────────────────────
set EXTRACT_DIR=%CACHE_DIR%\extrait
if exist "%EXTRACT_DIR%" rmdir /s /q "%EXTRACT_DIR%"
mkdir "%EXTRACT_DIR%"
tar -xf "%ZIP_PATH%" -C "%EXTRACT_DIR%"
if errorlevel 1 (
    echo ERREUR : extraction du zip ffmpeg echouee.
    exit /b 1
)

REM ── 5. Copie de bin\ffmpeg.exe + LICENSE.txt (nom de dossier racine variable) ──
set SRC_ROOT=
for /d %%D in ("%EXTRACT_DIR%\*") do set "SRC_ROOT=%%D"
if not defined SRC_ROOT (
    echo ERREUR : dossier racine du zip ffmpeg introuvable apres extraction.
    exit /b 1
)

copy /y "%SRC_ROOT%\bin\ffmpeg.exe" "%DEST_DIR%\ffmpeg.exe" >nul
if errorlevel 1 (
    echo ERREUR : copie de ffmpeg.exe echouee.
    exit /b 1
)
copy /y "%SRC_ROOT%\LICENSE.txt" "%DEST_DIR%\LICENSE.txt" >nul
if errorlevel 1 (
    echo ERREUR : copie de LICENSE.txt echouee.
    exit /b 1
)

REM ── 6. Check fonctionnel bloquant (libopus present dans le build lgpl) ────────
"%DEST_DIR%\ffmpeg.exe" -version >nul
if errorlevel 1 (
    echo ERREUR : "%DEST_DIR%\ffmpeg.exe" -version a echoue.
    exit /b 1
)
"%DEST_DIR%\ffmpeg.exe" -encoders 2>nul | findstr /i libopus >nul
if errorlevel 1 (
    echo ERREUR : libopus absent de ce build ffmpeg - verifier la variante lgpl BtbN.
    exit /b 1
)
echo [telecharger_ffmpeg] Check fonctionnel OK ^(libopus present^).

REM ── 7. Marqueur d'idempotence ──────────────────────────────────────────────────
echo %FFMPEG_SHA256%> "%DEST_DIR%\ffmpeg.sha256"

echo [telecharger_ffmpeg] ffmpeg.exe pret dans %DEST_DIR%
exit /b 0

@echo off
setlocal enableextensions
REM Build natif du spike backends Windows (appele depuis build_spike_backends_vm.sh).
REM Ne pas executer manuellement.
set VM_DIR=C:\Users\sylvaing\spike_backends_build
cd /d %VM_DIR%
if errorlevel 1 ( echo ERREUR : impossible de cd vers %VM_DIR% & goto :error )
echo [spike_build.cmd] Repertoire : %CD%

REM Token HF optionnel (cree par build_spike_backends_vm.sh si HF_TOKEN est defini sur le Mac).
if exist spike_token.cmd (
    call spike_token.cmd
    del spike_token.cmd
    echo  HF_TOKEN charge.
)

echo [0/3] Visual C++ Redistributable (requis par numpy/onnxruntime — installe si absent)...
powershell -Command "Invoke-WebRequest -Uri 'https://aka.ms/vs/17/release/vc_redist.x64.exe' -OutFile 'vc_redist.x64.exe' -UseBasicParsing; Start-Process 'vc_redist.x64.exe' -ArgumentList '/install','/quiet','/norestart' -Wait; Remove-Item 'vc_redist.x64.exe'"
if errorlevel 1 goto :error
echo  VC++ Redistributable OK.

echo [1/3] Creation du venv Python 3.11...
if exist .venv-spike ( rmdir /s /q .venv-spike )
py -3.11 -m venv .venv-spike
if errorlevel 1 goto :error

echo [2/3] Installation des outils de build...
call .venv-spike\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 goto :error
REM huggingface-hub suffit : les modeles DirectML sont pre-convertis (onnx-community),
REM plus besoin de torch + optimum pour la conversion a la volee.
python -m pip install huggingface-hub
if errorlevel 1 goto :error

echo [3/3] Assemblage du bundle spike...
python -m spike.backends_windows.assembler --natif --sortie bundles
if errorlevel 1 goto :error

echo RC=0 > spike_build.done
echo.
echo === Build spike termine avec succes ===
exit /b 0

:error
set ERR=%errorlevel%
echo RC=%ERR% > spike_build.done
echo === ECHEC build spike (RC=%ERR%) ===
exit /b %ERR%

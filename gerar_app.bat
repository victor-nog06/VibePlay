@echo off
title Gerador VibePlay - Vibe Group
echo ====================================================
echo   PREPARANDO GERACAO DO EXECUTAVEL: VIBEPLAY
echo   ESTADO: ARCADE RE-FIX + PREVIEW STABLE
echo ====================================================
echo.

echo 1. Instalando/Atualizando dependencias (OpenCV, Pygame, PyQt6, Google APIs)...
python -m pip install --upgrade pip
python -m pip install pyinstaller opencv-python pygame PyQt6 google-auth-oauthlib google-api-python-client

echo.
echo 2. Gerando o arquivo executavel (EXE)...
echo Este processo pode levar de 1 a 3 minutos. Aguarde...
echo.

:: --noconsole: oculta a janela de comando ao abrir o app
:: --onefile: empacota tudo em um unico arquivo .exe
:: --add-data: embute o ffmpeg.exe diretamente dentro do executavel
:: --name: define o nome do arquivo final como V15
python -m PyInstaller --noconsole --onefile --add-data "ffmpeg.exe;." --name "VibePlay" sports_replay_v4.py

echo.
if exist "dist\VibePlay.exe" (
    echo ====================================================
    echo   SUCESSO! O executavel foi criado na pasta "dist".
    echo ====================================================
    echo.
    echo INFORMACOES DE PORTABILIDADE:
    echo 1. O "ffmpeg.exe" foi embutido dentro do executavel (VibePlay.exe).
    echo 2. Nao e mais obrigatorio copiar "ffmpeg.exe" para a pasta "dist", 
    echo    mas se colocar uma versao personalizada la, ela sera usada como fallback.
    echo.
    echo REGRAS DO BOTAO ARCADE:
    echo - 1 Clique: Replay 30 segundos.
    echo - 2 Cliques: Replay 60 segundos.
    echo - Segurar o botao: Nada acontece (Protecao).
) else (
    echo.
    echo [ERRO] O executavel nao foi gerado. 
    echo Verifique se o arquivo "sports_replay_v4.py" esta nesta pasta.
)

echo.
pause

# VibePlay

Sistema portatil de replays com captura RTSP, FFmpeg e upload para o Google Drive.

## Estrutura

- `replays/`: replays gravados, separados automaticamente por quadra.
- `uploads/`: fila persistente de uploads.
- `uploads/pendentes/`: arquivos locais pendentes de envio.
- `temp/`: buffer temporario da gravacao ao vivo.
- `config/`: configuracao do aplicativo.
- `auth/`: credenciais e token do Google Drive.
- `logs/`: registro de erros.

## Windows

Execute `iniciar.bat`. Ele abre `dist/VibePlay.exe` quando o executavel estiver disponivel e usa o Python como alternativa.
Para instalar as dependencias manualmente, use `python -m pip install -r requirements.txt`.
Rode `gerar_app.bat` sempre que precisar gerar novamente `dist/VibePlay.exe`.

## Raspberry Pi

Use Raspberry Pi OS de 64 bits com ambiente grafico. Depois de clonar o repositorio:

```bash
cd VibePlay
chmod +x instalar_raspberry.sh iniciar.sh atualizar.sh
./instalar_raspberry.sh
```

Edite `config/vibe_config.json` com os dados reais das cameras e inicie:

```bash
./iniciar.sh
```

Para atualizar depois de novos commits:

```bash
./atualizar.sh
```

### Inicializacao automatica

Para instalar e habilitar o servico `systemd` durante a configuracao:

```bash
./instalar_raspberry.sh --enable-service
sudo systemctl start vibeplay
```

Comandos uteis:

```bash
sudo systemctl status vibeplay
journalctl -u vibeplay -f
sudo systemctl restart vibeplay
```

O servico grafico pressupoe uma sessao desktop no display `:0`.

## Google Drive

Para habilitar uploads, coloque `credentials.json` dentro de `auth/`. O token sera criado nessa mesma pasta depois da primeira autenticacao.

Arquivos de credenciais, configuracao local das cameras, replays, temporarios e builds sao ignorados pelo Git.

# VibePlay

Sistema portatil de replays com captura RTSP, FFmpeg e upload seguro para o Supabase.

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

Edite `config/vibe_config.json` com os dados reais das cameras. Cada quadra deve ter
um `court_id` exclusivo e um `button_index` exclusivo (numeração iniciada em zero,
como reportada pelo Pygame). Cada câmera mantém seu próprio buffer, e o botão envia
somente o replay da quadra associada.

```bash
./iniciar.sh
```

Para atualizar depois de novos commits:

```bash
./atualizar.sh
```

O Raspberry executa o mesmo `sports_replay_v4.py` usado no Windows; nao utiliza
o executavel da pasta `dist/`. A atualizacao preserva as configuracoes locais e
valida a sintaxe Python antes de reiniciar o servico. Sem servico instalado,
feche o aplicativo e execute `./iniciar.sh` novamente.

### Cadastro e edicao de quadras e botoes

Preencha nome, URL RTSP e ID da quadra. Clique em **CAPTURAR BOTAO**, solte o
botao fisico se estiver pressionado e aperte o botao da quadra. Confirme em
**CADASTRAR QUADRA**. Para editar, selecione a quadra na lista e use
**SALVAR ALTERACOES**; o botao existente pode ser mantido ou recapturado.

- Um clique gera um replay dos ultimos 30 segundos.
- Dois cliques, com soltura entre eles e intervalo de ate 500 ms, geram um unico
  replay dos ultimos 60 segundos. Aguarde o fechamento dessa janela de deteccao.
- A leitura ocorre a cada 10 ms, com filtro de contato de 30 ms para pressionar
  e soltar. O clique so e contado depois de apertar e soltar; pressoes maiores
  que tres segundos sao descartadas.
- Tres ou mais cliques na mesma sequencia sao descartados como sinal excessivo.
  Depois de um replay ou sinal excessivo, o botao precisa ficar solto por um
  segundo para liberar uma nova sequencia. Os atalhos globais de teclado para
  replay foram removidos; use o botao associado ou os botoes da interface.
- Contatos ja fechados ao conectar a placa ou iniciar a captura precisam ser
  soltos antes de um novo aperto. Sinais repetidos do controlador sao ignorados.
- O gravador precisa ter acumulado pelo menos 30 ou 60 segundos de buffer.

A placa deve ser reconhecida pelo Linux como joystick USB com botoes. O status
mostra o nome e a quantidade de botoes do controlador detectado. Uma placa que
emula teclado precisa de suporte especifico; o LED aceso sozinho nao comprova
o reconhecimento USB. Consulte `logs/vibe_erro_log.txt` e `logs/runtime.log`.

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

## Upload para o Supabase

O backend gera uma autorização temporária e o Raspberry envia o vídeo diretamente ao Supabase Storage. Somente os metadados passam pela Vercel, e nenhuma chave administrativa do Supabase fica no Raspberry.

1. Configure no backend a variavel `REPLAY_UPLOAD_TOKEN` com um segredo aleatorio de pelo menos 40 caracteres.
2. Configure `config/supabase_upload.json` com a URL publica do backend, o mesmo token e o ID da arena.
3. Em `config/vibe_config.json`, informe o `court_id` de cada quadra.

Exemplo:

```json
{
  "backend_url": "https://api.exemplo.com",
  "device_token": "segredo-compartilhado-com-o-backend",
  "arena_id": "uuid-da-arena"
}
```

Arquivos de credenciais, configuracao local das cameras, replays, temporarios e builds sao ignorados pelo Git.

### Diagnostico do upload

O status da interface diferencia falha de rede, chave invalida, quadra sem autorizacao,
rota ausente no backend e recusa do Supabase Storage. O detalhe tecnico permanece em
`logs/vibeplay_errors.log`. Em caso de falha, o video continua na fila local e uma nova
tentativa e feita automaticamente.

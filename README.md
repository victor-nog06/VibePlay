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

### Logos gravadas nos replays

Adicione a logo oficial transparente em `assets/branding/vibe.png`. Ela e
obrigatoria para exportar novos replays e fica fixa no centro inferior.
Essa pasta e versionada: depois do commit e push da imagem, `./atualizar.sh`
baixa a logo junto com o codigo, sem copia manual no Raspberry. Sem configuracao
local, o aplicativo usa esse caminho automaticamente.
A logo oficial esta incluida nessa pasta; se o arquivo for removido, o corte falha
com diagnostico no log, sem publicar um video sem a marca.

Copie `config/branding.example.json` para `config/branding.json` se precisar
configurar outros caminhos ou patrocinadores. Em `sponsors_left` e
`sponsors_right`, informe listas de caminhos de imagens, relativos a `config/`.
Exemplo: `["branding/patrocinador1.png", "branding/patrocinador2.png"]`.
Cada lado alterna sua lista a cada 10 segundos a partir do inicio do replay.
Listas vazias deixam espacos transparentes reservados; nao sao desenhadas caixas.
As imagens preservam proporcao, dentro de 260x120 pixels em Full HD, em tres
colunas separadas na parte inferior. Em 720p, tamanhos e margens sao reduzidos
proporcionalmente. Use PNG com fundo transparente.
Arquivos configurados ausentes ou invalidos impedem o corte para evitar marcas
incompletas. A configuracao e local ao Raspberry da arena; sincronizacao com o
site e sobreposicoes no YouTube ainda nao estao implementadas.

Os novos replays sao exportados em MP4 horizontal 16:9, com resolucao padrao
1280x720 no Raspberry ARM e 1920x1080 nos demais computadores,
H.264/yuv420p e audio AAC quando disponivel. O video preenche a tela sem
deformacao, com recorte central quando a camera usa outra proporcao.
A gravacao continua e a visualizacao da camera mantem o formato original.
Essa exportacao usa o mesmo codigo Python no Raspberry e no Windows e nao
altera os arquivos de replay ja existentes. A resolucao de saida pode aumentar
o tempo de processamento no Raspberry.

Para reduzir esse custo, o recorte e feito antes da ampliacao e cada
logo estatica e decodificada uma unica vez, sendo reutilizada nos quadros.
O tempo total de cada corte e registrado em `logs/vibe_erro_log.txt`.

### Desempenho no Raspberry

O trecho do clique e copiado antes de entrar na fila. Por padrao, apenas um
replay e codificado por vez, com threads automaticas de decodificacao/codificacao
e filtros, evitando que diversos encoders disputem recursos.
No Raspberry, o perfil padrao prioriza velocidade em 1280x720 (16:9).
Para restaurar Full HD, configure `height: 1080`.

Em Linux ARM, `encoder=auto` testa de fato o encoder `h264_v4l2m2m` na resolucao
de saida; so o usa se funcionar. Caso indisponivel, usa libx264 ultrafast.
Se falhar durante um corte, repete o mesmo snapshot por software e desabilita
a tentativa por hardware ate reiniciar. Nao se presume aceleracao em todo
modelo de Raspberry (inclusive equipamentos sem encoder H.264 disponivel).

Para ajustar, copie `config/replay_processing.example.json` para
`config/replay_processing.json`. `height` aceita 1080 ou 720; 720 reduz em
aproximadamente 56% a quantidade de pixels por quadro e redimensiona as marcas
proporcionalmente. `threads` e `filter_threads` aceitam 0..8 (0=automatico),
`parallel` aceita 1..4, e `encoder`
aceita `auto`, `libx264` ou `h264_v4l2m2m`. A configuracao local nao e versionada.
O log separa espera do segmento, copia, fila e codificacao. Esses tempos sao
necessarios para medir o ganho real no equipamento, inclusive limitacoes de
temperatura, alimentacao, armazenamento e quantidade de cameras.

### Reproducao no Safari e outros navegadores no iOS

Novos arquivos usam MP4/H.264 `avc1`, Baseline, 8 bits/yuv420p, nivel 3.1 em
720p ou 4.1 em 1080p, com limite de 30 fps (fontes mais lentas nao sao elevadas
a 30 fps). Audio, quando presente, usa AAC-LC, 48 kHz, stereo. `faststart`
coloca o indice `moov` antes dos dados, e a trilha de video usa timescale 90000.
Os limites de bitrate de video sao 4 Mbit/s em 720p e 8 Mbit/s em Full HD.
Arquivos antigos nao sao convertidos automaticamente.

O upload define `Content-Type: video/mp4`, mas a resposta HTTP do player tambem
precisa fornecer esse tipo e suportar `Range`/`206 Partial Content`. Verifique
o link efetivamente usado pelo player (inclusive proxies, redirecionamentos e
URLs assinadas expiradas). A exportacao local nao garante o funcionamento do
servidor. Para video inline no iPhone, use `playsinline`; reproducao automatica
com audio pode depender de um toque do usuario.

O intervalo e fixado no instante do clique: um replay de 30s corresponde a
`[clique - 30s, clique]` na linha do tempo do video recebido. O FFmpeg publica
um indice CSV com inicio/fim dos segmentos; o corte usa esses tempos e nao
data de modificacao ou o fim da concatenacao. Pode aguardar ate 30s pelo
fechamento do segmento que contem o clique, sem incluir imagens posteriores
ao instante fixado. Se houver falha, descontinuidade ou buffer sobrescrito,
o pedido falha em vez de selecionar outro periodo. A referencia e o video
recebido, sujeita a latencia RTSP e granularidade de quadros/progresso do FFmpeg.

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

Cada quadra usa um botao exclusivo da placa. A lista mostra a associacao de
quadra e botao. Durante a captura de outra quadra, botoes ja associados sao
ignorados; para trocar o botao de uma quadra existente, selecione-a antes.
Todos os botoes da placa sao monitorados com debounce independente. Apertos
simultaneos acionam as respectivas quadras, e um botao mantido pressionado nao
bloqueia os demais. A quadra selecionada na interface nao altera esse roteamento.

- Cada transicao valida de solto para pressionado gera um unico replay de 30s.
  O campo opcional `replay_seconds` de cada quadra aceita 30 ou 60 e e preservado
  ao editar a quadra. O agrupamento antigo por clique duplo foi removido: dois
  apertos completos agora geram dois cortes. Os botoes manuais de 30s/60s continuam.
- A leitura ocorre a cada 10 ms. Pressionar e soltar exigem estabilidade de 50 ms.
  Configure `ARCADE_DEBOUNCE_MS` no ambiente (maior que 0, ate 5000 ms).
- Ao iniciar, reconectar ou entrar em captura, aguarda soltura estavel antes de
  habilitar a entrada. Segurar o botao ou repetir eventos nao gera novos cortes.
- A interface e joystick USB via Pygame (`get_button`), e nao GPIO. O nivel
  logico padrao e 1=pressionado e 0=solto, conforme a semantica de botoes do SDL.
  Isso nao determina a polaridade eletrica nem o tipo de contato da fiacao.
  Confirme os niveis reais com o botao solto/apertado antes de configurar
  `ARCADE_PRESSED_LEVEL=0` para um encoder que reporte o estado invertido.
- A interface fornece estado de soltura, mas a duracao e medida pelo programa,
  sem timestamps do sinal eletrico. Pulsos entre leituras podem nao ser vistos.
  Ruido que imite um aperto estavel por mais que o debounce e indistinguivel de
  um clique humano; a alimentacao e a fiacao precisam estar estaveis.
- Logs registram estados estaveis, cliques, pulsos descartados (agregados no
  maximo uma vez por segundo/botao) e resultado do corte, sem registrar cada leitura.
- O gravador precisa ter acumulado pelo menos 30 ou 60 segundos de buffer.

A placa deve ser reconhecida pelo Linux como joystick USB com botoes. O status
mostra o nome e a quantidade de botoes do controlador detectado. Uma placa que
emula teclado precisa de suporte especifico; o LED aceso sozinho nao comprova
o reconhecimento USB. Consulte `logs/vibe_erro_log.txt` e `logs/runtime.log`.

Para executar os testes sem placa, cameras ou interface grafica:

```bash
python3 -m unittest discover -s tests -v
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

A thumbnail e gerada como um unico JPEG de 640 pixels de largura. Se a busca
no meio do video nao encontrar quadro (por exemplo, video mais curto que a
duracao cadastrada), tenta o primeiro quadro. Imagens em cache sao validadas,
e a gravacao usa arquivo temporario com substituicao atomica para evitar JPEGs
parciais. As tentativas usam limite de 60s e threads reduzidas para o Raspberry;
os detalhes ficam em `logs/vibe_erro_log.txt`. O video original e preservado em
caso de falha.

MP4s com `moov atom not found` estao incompletos ou danificados. Sao marcados
como `invalid_media` na fila e preservados no disco para diagnostico; nao sao
reenviados automaticamente nem bloqueiam os outros videos. Se um arquivo for
reparado externamente, seu item pode voltar a `pending` com o aplicativo parado.
Os novos cortes usam `.partial.mp4` durante a geracao, ignorado pela varredura,
e so recebem o nome final depois de validar a leitura de um quadro do video.
Uma thumbnail nova nao repara um MP4 danificado. Interrupcoes de energia e
armazenamento cheio devem ser investigados no Raspberry quando isso ocorrer.

O status da interface diferencia falha de rede, chave invalida, quadra sem autorizacao,
rota ausente no backend e recusa do Supabase Storage. O detalhe tecnico permanece em
`logs/vibeplay_errors.log`. Em caso de falha, o video continua na fila local e uma nova
tentativa e feita automaticamente.

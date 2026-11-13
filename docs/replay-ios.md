# Exportacao Full HD para iOS

## Diagnostico e correcao

Comparacao dos arquivos reais fornecida pelo usuario (nao reanalisados localmente):

| Parametro | 06/11 22:23:12, funciona | 08/11 21:58:47, MEDIA_ERR_4 | Nova exportacao validada localmente |
| --- | --- | --- | --- |
| Codec/perfil | H.264 Constrained Baseline | H.264 Constrained Baseline | H.264 Constrained Baseline |
| Nivel | 3.0 | 6.2 | 4.1 |
| Resolucao | 704x480 | 1920x1080 | 1920x1080, SAR 1:1, DAR 16:9 |
| FPS | 30 | aproximadamente 30 | 30 constantes |
| SPS time_scale / num_units_in_tick | 60 / 1 | 180000 / 1 | 60 / 1 |
| Indice MP4 | moov antes de mdat | moov antes de mdat | moov antes de mdat |

A entrada RTSP/MPEG-TS tem tipicamente timebase 1/90000. `trim` e
`setpts=PTS-STARTPTS` reposicionam timestamps, mas nao normalizam a timebase.
O framesync dos overlays pode preservar esse relogio ate a entrada do encoder.
A configuracao anterior nao fixava a timebase do encoder; `-fpsmax 30`
limitava a taxa, mas nao definia CFR30 nem o timing H.264.
Para H.264 progressivo, o timing usual e time_scale/(2*num_units_in_tick):
60/2=30 fps, mas 180000/2=90000 fps nominais, incoerentes com os quadros reais.
Esse valor e consistente com uma negociacao incorreta de taxa/timebase na
entrada do encoder. O clock do MP4 nao e o SPS.

Apenas usar entrada de 90 kHz NAO implica SPS incorreto: ao reconstruir o
graph antigo no FFmpeg local 8.1.1, uma fonte saudavel produziu nivel 4.0 e
SPS 60/1, mesmo usando MPEG-TS 90 kHz. Assim, a causa exata daquele arquivo
depende tambem dos metadados originais e/ou da negociacao da versao do FFmpeg
no Raspberry; esse binario e os arquivos originais nao foram executados aqui.
O teste adicional injeta VUI nominal de 90000 fps em quadros espacados a 30 fps
e verifica que o fluxo novo elimina essa dependencia da sinalizacao de origem.

O ultimo filtro, DEPOIS de todas as logos, agora e:

```text
fps=fps=30:start_time=0:round=near,settb=expr=1/30,setpts=N
```

O filtro fps duplica/descarta quadros sobre a linha do tempo ja recortada,
sem acelerar nem desacelerar o trecho. A resolucao temporal de saida e 1/30 s;
limites entre quadros ficam sujeitos a esse arredondamento. O intervalo continua
fixado no clique, antes de esperar segmento, copiar snapshot ou entrar na fila.
O audio conserva o trim do mesmo intervalo e a origem temporal em zero.

O encoder tambem recebe `-r:v 30 -fps_mode:v cfr -enc_time_base:v 1:30`.
libx264 usa `force-cfr=1` para sinalizar taxa fixa no VUI. Nao se reescreve o
nivel/SPS de um fluxo incorreto por bitstream filter.

Nao e apenas uma troca da etiqueta de nivel: Full HD progressivo tem
120x68=8160 macroblocos por quadro (padding interno ate 1088 linhas),
244800 macroblocos/s a 30 fps, dentro dos limites 8192 e 245760 do nivel 4.1.
O software usa uma referencia, sem B-frames/CABAC no Baseline, maxrate 8 Mbit/s
e VBV 16 Mbit. Hardware recebe os mesmos limites e e rejeitado se o SPS real
nao cumprir perfil, nivel, dimensoes e timing. O fallback usa os mesmos
snapshots, filtros e parametros comuns, sem mudar o instante do replay.

## Comandos resultantes

Exemplo representativo de um replay de 30 s com uma logo em cada posicao.
`S` e o deslocamento calculado no concat, nao uma nova captura apos o clique.
As listas de patrocinadores continuam sendo construidas por `build_branding`,
com alternancia a cada 10 s. Caminhos e deslocamento sao argumentos calculados
pelo programa; os comandos abaixo nao devem ser executados com esses placeholders.

```bash
ffmpeg -hide_banner -loglevel error -nostdin -y \
  -threads 0 -filter_complex_threads 0 \
  -f concat -safe 0 -i SNAPSHOT/segments.txt \
  -i VIBE.png -i PATROCINADOR_ESQUERDO.png -i PATROCINADOR_DIREITO.png \
  -t 30 -filter_complex "$GRAPH" -map '[replay_cfr]' -map '0:a?' \
  -af 'atrim=start=S:duration=30,asetpts=PTS-STARTPTS' \
  -c:v libx264 -preset ultrafast -crf 23 -x264-params force-cfr=1 -threads 0 \
  -pix_fmt yuv420p -profile:v baseline -level:v 41 -tag:v avc1 \
  -r:v 30 -fps_mode:v cfr -enc_time_base:v 1:30 \
  -maxrate 8000k -bufsize 16000k -metadata:s:v:0 rotate=0 \
  -c:a aac -profile:a aac_low -b:a 128k -ar 48000 -ac 2 \
  -movflags +faststart -video_track_timescale 90000 REPLAY.mp4.partial.mp4
```

Graph correspondente (enable dos patrocinadores varia conforme configuracao):

```text
[0:v:0]trim=start=S:duration=30,setpts=PTS-STARTPTS,crop=w='min(iw,ih*16/9)':h='min(ih,iw*9/16)',scale=1920:1080:flags=fast_bilinear,setsar=1,setpts=PTS-STARTPTS[base0];
[1:v]scale=260:120:force_original_aspect_ratio=decrease,format=rgba,setsar=1[logo1];
[base0][logo1]overlay=x=(W-w)/2:y=H-180+(120-h)/2:eof_action=repeat[base1];
[2:v]scale=260:120:force_original_aspect_ratio=decrease,format=rgba,setsar=1[logo2];
[base1][logo2]overlay=x=(W/3-w)/2:y=H-180+(120-h)/2:eof_action=repeat:enable='eq(mod(floor(t/10),1),0)'[base2];
[3:v]scale=260:120:force_original_aspect_ratio=decrease,format=rgba,setsar=1[logo3];
[base2][logo3]overlay=x=2*W/3+(W/3-w)/2:y=H-180+(120-h)/2:eof_action=repeat:enable='eq(mod(floor(t/10),1),0)'[base3];
[base3]fps=fps=30:start_time=0:round=near,settb=expr=1/30,setpts=N[replay_cfr]
```

Hardware substitui SOMENTE `-c:v libx264 ... -threads 0` por:

```text
-c:v h264_v4l2m2m -b:v 6000k
```

Todos os argumentos a partir de `-pix_fmt`, o graph, o audio e a duracao
continuam iguais. A saida e validada e publicada por rename atomico apenas
depois da finalizacao do MP4. Videos publicados nao sao modificados.

## Validacao e limites

```bash
python -m unittest discover -s tests -q
ffmpeg -hide_banner -i NOVO_REPLAY.mp4 -map 0:v:0 -c:v copy -bsf:v trace_headers -frames:v 1 -f null -
ffmpeg -v error -xerror -i NOVO_REPLAY.mp4 -f null -
ffprobe -v error -show_streams -show_format NOVO_REPLAY.mp4
```

O teste `tests/test_ios_export.py` chama o metodo REAL `extract_replay` de
producao sobre segmentos MPEG-TS com fontes 25, 30 e 60 fps e outra fonte
com timebase explicita 1/90000. Um quinto caso fornece SPS/VUI inconsistente
com time_scale=180000 e num_units_in_tick=1. Carrega o branding e dois patrocinadores.
Confere trace_headers, resolucao, SAR, formato, SPS 60/1 e nivel 41, 90 quadros
em 3 s, timestamps de video crescentes em passos 1/30, audio de 3 s,
conteudo visual do intervalo [1.5, 4.5], logo, moov antes de mdat, decodificacao
integral sem erros e thumbnail. O relogio da trilha MP4 continua 1/90000,
comprovando que esse valor nao precisa ser trocado para corrigir o SPS.
Os testes existentes tambem verificam intervalos reais de 30 e 60 segundos,
cliques, fila, fallback e arquivos invalidos.

Validacao local com libx264/FFmpeg no Windows. Sem dispositivo V4L2 Raspberry
nem iPhone neste ambiente: hardware real e reproducao Safari/Chrome no aparelho
permanecem pendentes. Testes de fallback simulam erro de driver e SPS incorreto.
Decodificar no FFmpeg nao comprova reproducao no iPhone.

## Atualizar o gravador no Raspberry

Apos disponibilizar esta versao no Git, execute na pasta do projeto:

```bash
./atualizar.sh
```

O script atualiza o codigo/dependencias e reinicia `vibeplay.service` se ele
estiver habilitado. Sem esse servico, feche a janela antiga e execute:

```bash
./iniciar.sh
```

Para reinicio manual de um servico ja instalado:

```bash
sudo systemctl restart vibeplay.service
sudo systemctl status vibeplay.service --no-pager
```

Nao deixe duas instancias gravando. Reiniciar encerra a sessao continua antiga
e recomeca o buffer; espere acumular os 30/60 s necessarios antes de testar.
O codigo novo nao e carregado por um processo Python que ja estava aberto.
Uma configuracao local antiga de 720p passa a gerar 1080p automaticamente,
sem alterar o arquivo local nem os MP4 existentes. Avalie um NOVO replay no
iPhone e confira o log `logs/vibe_erro_log.txt` para encoder/fallback e tempos.

Referencias oficiais: [filtro fps](https://ffmpeg.org/ffmpeg-filters.html#fps),
[timebase do encoder](https://ffmpeg.org/ffmpeg.html),
[SPS/VUI e h264_metadata](https://ffmpeg.org/ffmpeg-bitstream-filters.html#h264_005fmetadata).

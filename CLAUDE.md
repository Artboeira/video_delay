# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Sobre o projeto

Sistema de playback com delay configurável: captura HDMI via placa de captura, grava
segmentos `.ts` curtos e os reproduz em fullscreen com N segundos de atraso. Usado
em instalações do Estúdio AB ("espelho atrasado").

Inclui painel de configuração web embutido (atalho `P` no terminal) com fidelidade
ao design system AB — fontes locais, hairline rules, gradiente assinado, tipografia
Neue Haas Grotesk Thin + Calling Code. Pode ser empacotado como executável standalone
para Mac e Win via `python build.py` (PyInstaller — única dep, build-time only).

## Plataforma e dependências

- **Produção: Windows.** DirectShow (`dshow`) como entrada do FFmpeg. Em macOS/Linux
  só roda em modo de teste (`testsrc2` sintético). Outros pontos cross-platform:
  - Teclado não-bloqueante: `msvcrt` no Windows, `termios + select` em POSIX (exige
    TTY). Sem TTY o controle é feito todo pelo painel web.
  - IPC do MPV: named pipe no Windows, socket UNIX em macOS/Linux
    ([modules/player.py](modules/player.py#L18)).
  - Enumeração de monitores: `ctypes` no Windows, `system_profiler` no macOS,
    `xrandr` no Linux ([modules/monitors.py](modules/monitors.py)).
- **Stdlib apenas em runtime.** Não há `requirements.txt`. PyInstaller é a única dep
  PyPI permitida, e **só em build time** (rodada via `python build.py`, fora do
  runtime). Nunca adicione deps PyPI ao código que roda.
- **Binários externos no PATH:** `ffmpeg` e `mpv`. Ausência é detectada em runtime
  (`shutil.which` em `main.py` mostra aviso; `FileNotFoundError` no `capture.py`
  recupera no loop).

## Comandos

```
python list_devices.py                       # descobre o nome exato da placa (dshow)
python main.py                               # executa o sistema (precisa de placa)
python main.py --test                        # MODO DE TESTE: fonte sintética (lavfi)

python -m unittest discover -s tests -v      # roda toda a suite
python -m unittest tests.test_player -v      # roda só um arquivo de teste
python -m unittest tests.test_player.GetReadySegmentsTests.test_only_returns_segments_older_than_delay
```

Atalhos Windows: `list_devices.bat`, `start.bat`, `test_mode.bat`, `run_tests.bat`.
Não há lint nem CI configurado.

### Modo de teste

`--test` (ou `"test_mode": true` no `config.json`) substitui a entrada `dshow` por
`lavfi testsrc2` — fonte sintética com clock visível, sem precisar de placa de
captura nem cabo HDMI. Funciona em qualquer plataforma com FFmpeg + MPV instalados
e é a forma recomendada de validar mudanças. Em macOS/Linux o MPV abre normalmente
(socket UNIX); em Windows continua usando named pipe.

### Suite de testes

- **Unit tests** ([tests/test_player.py](tests/test_player.py), [test_cleaner.py](tests/test_cleaner.py),
  [test_capture.py](tests/test_capture.py), [test_main.py](tests/test_main.py)) — cobrem
  parsing de timestamps, filtragem por delay, progresso de buffer, clamping do delay,
  limpeza por idade, montagem do comando FFmpeg (produção e teste) e validação de config.
  Não tocam o filesystem real além de `tempfile`.
- **Integração** ([tests/test_integration.py](tests/test_integration.py)) — sobe o
  `CaptureManager` em modo de teste, deixa o FFmpeg rodar ~8s, valida que segmentos
  `.ts` foram gerados com timestamps corretos. Skip automático se `ffmpeg` não estiver
  no PATH (`shutil.which("ffmpeg") is None`).
- Helper compartilhado [tests/_helpers.py](tests/_helpers.py) tem `TempSegments` para
  fabricar arquivos `.ts` com timestamps arbitrários — use isso para qualquer teste
  novo que precise simular o passado da captura.

Durante a execução: `P` abre o painel web, `+`/`-` ajusta delay em passos de 30s
(mínimo 10s), `r` recarrega `config.json` sem reiniciar threads, `q` encerra. Em
macOS/Linux as teclas exigem TTY (`sys.stdin.isatty()`); sem TTY o controle é todo
pelo painel.

### Build do executável

```
python build.py            # PyInstaller --onefile --windowed para o SO atual
python build.py --clean    # apaga build/, dist/, .spec antes
python build.py --console  # mantém terminal visível (debug)
```

Pacote inclui `webui/` inteira (HTML/CSS/JS/fontes/assets) via `--add-data`.
Não embute `ffmpeg`/`mpv` — runtime detecta no PATH.

## Arquitetura

Quatro threads daemon coordenadas pelo `main.py`. **Dois canais de comunicação**, sem
chamadas diretas entre managers:
- **Sistema de arquivos (`segments/`)** entre captura e player.
- **`config` dict compartilhado por referência** entre painel web e managers
  (mutado in-place; nunca substituído).

```
CaptureManager  →  segments/YYYYMMDD_HHMMSS.ts  →  PlayerManager
                            ↑
                      CleanerManager  (remove segmentos > max_segment_age_seconds)

ConfigServer (HTTP local)  ↔  config dict  →  managers
                                ↓
                            config.json   (persistido em mutação)
```

- [modules/capture.py](modules/capture.py) — invoca FFmpeg uma vez e deixa rodando.
  FFmpeg faz a segmentação nativamente (`-f segment -strftime 1`), gerando arquivos
  nomeados pelo timestamp de gravação. Reinicia automaticamente em caso de erro (loop
  de 3s). O nome do arquivo **é** o relógio do sistema — é a única fonte de verdade
  do "quando isso foi gravado".

- [modules/player.py](modules/player.py) — lança um MPV em fullscreen e o alimenta via
  IPC JSON sobre named pipe (`\\.\pipe\mpv-delay-system`, ver `_send_mpv`). O delay é
  implementado em [`_get_ready_segments`](modules/player.py#L65) por **comparação de
  timestamps no nome do arquivo** contra `now - delay` — não há fila/buffer em memória.
  Mudar `delay_seconds` em runtime ajusta a janela de leitura na próxima iteração;
  segmentos já enfileirados no MPV continuam tocando.

- [modules/cleaner.py](modules/cleaner.py) — varre a pasta a cada 30s e apaga `.ts`
  com `mtime` (na verdade, timestamp do nome) anterior a `max_segment_age_seconds`.
  Esse valor **precisa ser maior que `delay_seconds`** ou o player ficará sem arquivos
  prontos.

- [modules/config_server.py](modules/config_server.py) — HTTP server stdlib
  (`http.server.ThreadingHTTPServer`) ligado a `127.0.0.1:8765` (com fallback de
  porta 8766…8774) que serve a pasta [webui/](webui/) (estáticos do painel) e
  expõe `/api/config`, `/api/status`, `/api/monitors`, `/api/shutdown`. Mutações
  no POST passam pelo `ServerState`, que valida (delay mín 10s, max_age > delay,
  CRF 0–51), persiste atomicamente (`.tmp` + `os.replace`) e propaga via
  `player.set_delay()` ou `capture.request_restart()`. Empacotado: resolve
  `webui/` via `sys._MEIPASS`. **Whitelist de campos** em `_ALLOWED_FIELDS` —
  campo fora dela é silenciosamente descartado.

- [modules/monitors.py](modules/monitors.py) — enumeração cross-platform de
  monitores para a UI escolher tela: ctypes/EnumDisplayMonitors no Windows,
  `system_profiler SPDisplaysDataType -json` no macOS, `xrandr` no Linux.
  Falha cai em fallback `[Monitor 0, Monitor 1]` — UI sempre tem o que mostrar.

- [main.py](main.py) — orquestra: bootstrap de config (cria default em primeira
  execução via `ensure_config_exists()`), sobe `ConfigServer` antes das threads,
  faz polling do teclado (cross-platform: `msvcrt` no Win, `termios + select` no
  POSIX, no-op sem TTY), renderiza a linha de status. A tecla `P` abre o painel
  via `webbrowser.open()`. `q` ou POST `/api/shutdown` sinalizam `shutdown_event`.

### Invariantes não-óbvias

- **Nomes de arquivo são contratos.** O formato `%Y%m%d_%H%M%S.ts` é compartilhado por
  capture, player e cleaner via `strptime`. Mudar o padrão exige editar os três.
- **`segment_duration` afeta o GOP.** Em [capture.py:46-48](modules/capture.py#L46-L48)
  o GOP e os keyframes forçados são derivados de `segment_time` para garantir que cada
  segmento comece em keyframe. Não mexa em um sem o outro.
- **`config` é compartilhado por referência.** `main.py` passa o mesmo `dict` para
  os managers **e** para o `ServerState`. Mutações (painel, `r`, `+`/`-`) fazem
  `config.update(...)`, não reatribuição. Substituir o dict quebra a propagação.
- **`delay_seconds` mínimo é 10s** (clamp em [`PlayerManager.set_delay`](modules/player.py#L48))
  e validado também no `ServerState.apply_config()` antes de persistir.
- **Mudanças em campos do FFmpeg exigem restart da captura.** `ServerState`
  detecta diffs em `capture_device`, `test_mode`, `segment_duration` e
  `video_quality` e chama `capture.request_restart()`. Mudar só delay/monitor
  não interrompe a captura.

## Convenções

- Comentários e strings de usuário em português; nomes de identificadores em inglês.
- README e mensagens de erro mantêm o tom do Estúdio AB (sóbrio, sem emoji nos arquivos
  de código — exceto os ícones de status já presentes em `main.py`).

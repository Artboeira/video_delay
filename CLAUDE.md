# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Sobre o projeto

Sistema de playback com delay configurável: captura HDMI (placa via DirectShow no Win,
AVFoundation no Mac) ou câmera, grava segmentos `.ts` curtos e os reproduz em
fullscreen com N segundos de atraso. **Distribuído como pasta de código-fonte
Python** — não há executável, instalador, .app, nem pipeline de build. Cliente
instala Python 3.11+ (uma vez por máquina) e roda `install.command`/`install.bat`
para baixar FFmpeg + MPV em `vendor/`. Depois é duplo-clique em
`run.command`/`run.bat`.

Primeira execução abre um **wizard guiado de 4 telas** no navegador
(placa de captura → monitor → delay → iniciar).

Inclui painel web embutido com fidelidade ao design system Estúdio AB (Neue Haas
Grotesk Display Thin + Calling Code, hairlines, gradiente assinado, sem rounded
corners). Painel e wizard são views da mesma SPA HTML/JS.

## Plataforma e dependências

- **Runtime:** Python 3.11+ e stdlib only. NUNCA adicione dep PyPI ao código
  que roda em produção.
- **Setup:** `scripts/fetch_binaries.py` (stdlib + opcionalmente `py7zr` no
  Windows quando a CLI 7z não está disponível). Roda uma vez no `install`.
- **Binários:** `ffmpeg` e `mpv` ficam em `vendor/<plat>/`, baixados pelo
  `fetch_binaries.py`. `bundled_binary()` resolve primeiro `vendor/`, depois
  cai em `shutil.which` (PATH do sistema).
- **Plataformas suportadas:**
  - macOS 11+ arm64: AVFoundation, `mpv.app` bundle inteiro
  - Windows 10/11 x64: DirectShow, `mpv.exe` standalone
  - Linux: apenas modo `--test` (lavfi)

## Comandos

```
# Setup inicial (uma vez por maquina)
python scripts/fetch_binaries.py             # baixa ffmpeg + mpv para vendor/

# Rodar do source
python main.py                               # producao
python main.py --test                        # MODO DE TESTE: fonte sintetica (lavfi)

# Testes
python -m unittest discover -s tests -v      # roda toda a suite (79 testes)
```

Não há lint configurado. Não há build, PyInstaller, GitHub Actions ou pipeline
de release — o projeto é distribuído copiando a pasta inteira para a máquina
do cliente (AirDrop, pen-drive, SSH, git clone) e rodando o `install` local.

### Wrappers de duplo-clique

Os arquivos `install.command`, `run.command`, `run-test.command` (macOS) e
`install.bat`, `run.bat`, `run-test.bat` (Windows) são apenas wrappers do
fluxo `python ...`. São destinados ao cliente final que não vai usar
terminal manualmente. Em ambiente de dev, prefira chamar `python main.py`
diretamente.

### Modo de teste

`--test` (ou `"test_mode": true` no config) usa `lavfi testsrc2` — fonte
sintética com clock visível, sem placa. Funciona em qualquer plataforma com
FFmpeg + MPV em `vendor/` (ou no PATH via `brew install ffmpeg mpv` no Mac
para validações rápidas em ambiente de dev).

### Suite de testes (79 testes)

- **Unit tests** ([test_player.py](tests/test_player.py), [test_cleaner.py](tests/test_cleaner.py),
  [test_capture.py](tests/test_capture.py), [test_main.py](tests/test_main.py),
  [test_paths.py](tests/test_paths.py), [test_capture_devices.py](tests/test_capture_devices.py),
  [test_monitors.py](tests/test_monitors.py), [test_config_server.py](tests/test_config_server.py))
  cobrem: parsing de timestamps, filtragem por delay, progresso de buffer,
  clamping do delay, limpeza por idade, montagem FFmpeg (dshow/avfoundation/lavfi),
  validação de config, resolução de paths cross-platform, parser de
  dispositivos (Win + Mac), enumeração de monitores, endpoints HTTP
  (incluindo wizard: setup-status, capture-devices, setup-complete).
  Não tocam o filesystem real além de `tempfile`.
- **Integração** ([tests/test_integration.py](tests/test_integration.py)) — sobe o
  `CaptureManager` em modo de teste, deixa o FFmpeg rodar ~8s, valida que
  segmentos `.ts` foram gerados com timestamps corretos. Skip automático se
  `ffmpeg` não estiver no PATH.
- Helper [tests/_helpers.py](tests/_helpers.py) tem `TempSegments` para
  fabricar arquivos `.ts` com timestamps arbitrários.

Durante a execução: `P` abre o painel web, `+`/`-` ajusta delay em passos
de 30s (mínimo 10s), `r` recarrega `config.json` sem reiniciar threads,
`q` encerra. Sem TTY (situação rara — exige ambiente sem terminal) o
teclado fica inativo e o controle é todo pelo painel.

## Arquitetura

Quatro threads daemon coordenadas pelo `main.py`. **Dois canais de comunicação**:
- **Sistema de arquivos (`segments/`)** entre captura e player.
- **`config` dict compartilhado por referência** entre painel/wizard e managers
  (mutado in-place; nunca substituído).

```
CaptureManager  →  segments/YYYYMMDD_HHMMSS.ts  →  PlayerManager
                            ↑
                      CleanerManager  (remove > max_segment_age_seconds)

ConfigServer (HTTP local)  ↔  config dict  →  managers
                                ↓
                          config.json   (persistido em mutação atômica)
```

- [modules/capture.py](modules/capture.py) — invoca FFmpeg uma vez e deixa
  rodando. Três modos em `_build_input_args`: `test_mode` (lavfi),
  `darwin` (avfoundation com `-an` para não pedir microfone),
  outros (dshow). Reinicia automaticamente em caso de erro (loop de 3s)
  ou em `request_restart()` (chamado quando config muda).

- [modules/player.py](modules/player.py) — lança um MPV em fullscreen e o
  alimenta via IPC JSON sobre named pipe (Win) ou socket UNIX (Mac/Linux).
  Delay implementado por comparação de timestamps no nome do arquivo
  contra `now - delay` — sem fila em memória. Mudar `delay_seconds` em
  runtime ajusta a janela na próxima iteração.

- [modules/cleaner.py](modules/cleaner.py) — varre a pasta a cada 30s e
  apaga `.ts` com timestamp do nome anterior a `max_segment_age_seconds`.
  Esse valor **precisa ser maior que `delay_seconds`** ou o player fica seco.

- [modules/config_server.py](modules/config_server.py) — HTTP server stdlib
  (`http.server.ThreadingHTTPServer`) ligado a `127.0.0.1:8765` (fallback até
  8774). Serve [webui/](webui/) (estáticos) e expõe:
  - `GET /api/config`, `POST /api/config` (mutação com validação cruzada e
    persistência atômica via `.tmp` + `os.replace`)
  - `GET /api/status` (snapshot de captura/player/buffer)
  - `GET /api/monitors`, `GET /api/capture-devices` (enumerados pelo SO)
  - `GET /api/setup-status`, `POST /api/setup-complete` (wizard)
  - `POST /api/shutdown`
  Mutações que afetam FFmpeg disparam `capture.request_restart()`.

- [modules/monitors.py](modules/monitors.py) — enumeração cross-platform:
  ctypes/EnumDisplayMonitors no Win, `system_profiler` no Mac, `xrandr` no
  Linux. Fallback `[Monitor 0, Monitor 1]` em falha.

- [modules/capture_devices.py](modules/capture_devices.py) — enumeração de
  placas: dshow no Win, avfoundation no Mac. Parser de stderr do ffmpeg.
  Usado pelo wizard para popular o dropdown.

- [modules/paths.py](modules/paths.py) — resolução cross-platform de paths
  para config/segments/logs e dos binários em `vendor/`. `bundled_binary()`
  resolve `ffmpeg`/`mpv` olhando `vendor/<plat>/`, e cai em `shutil.which`
  como último recurso. Caso especial Mac: `mpv` vem como `.app` bundle
  inteiro, então `_resolve_mac_mpv` aponta pra `mpv.app/Contents/MacOS/mpv`.
  Contém lógica defensiva de `is_frozen()` e `_bundle_bin_dir()` que nunca
  é executada no fluxo atual (era usada quando o projeto era empacotado
  via PyInstaller). Mantida como inofensiva.

- [modules/logging_setup.py](modules/logging_setup.py) — `RotatingFileHandler`
  em `log_path()` (5MB × 3 backups). Adiciona console handler quando há TTY.

- [main.py](main.py) — orquestra: faz **single-instance check via port-probe**
  (`detect_running_instance()`) antes de qualquer coisa; se já existe app
  rodando, abre o browser para ele e sai. Senão: bootstrap de config + log,
  sobe `ConfigServer`, threads dos managers, polling de teclado
  (cross-platform: `msvcrt` Win, `termios + select` Posix, no-op sem TTY).

### Frontend (webui/)

- [index.html](webui/index.html) — duas seções: `#wizard` (4 steps, hidden
  por default) e `#dashboard`. JS decide qual mostrar consultando
  `/api/setup-status` no boot.
- [app.js](webui/app.js) — state machine do wizard (`WIZARD.step` 1..4),
  chamada a `/api/capture-devices` e `/api/monitors` para popular as telas,
  POST `/api/setup-complete` no final. Dashboard mantém o polling existente.
- [style.css](webui/style.css) — tokens AB locais + estilos do wizard
  (`.wizard__step`, `.wizard__steps-rail`, fade transition entre steps).

### Setup & distribuição

- [install.command](install.command) / [install.bat](install.bat) — bootstrap
  para cliente final. Valida Python 3 e chama `python scripts/fetch_binaries.py`.
  Idempotente.
- [run.command](run.command) / [run.bat](run.bat) — duplo-clique para iniciar
  o sistema. Valida presença de `vendor/` e chama `python main.py`. Em erro
  mantém a janela aberta para inspeção.
- [run-test.command](run-test.command) / [run-test.bat](run-test.bat) — atalho
  para `python main.py --test`.
- [scripts/fetch_binaries.py](scripts/fetch_binaries.py) — baixa ffmpeg e
  mpv estáticos de fontes canônicas (evermeet, gyan, eko5624/mpv-mac,
  shinchiro). Idempotente. Suporta mode `binary` (extrai um arquivo) e
  `app_bundle` (extrai árvore inteira para mpv.app no Mac). Validação por
  tamanho mínimo; SHA-256 opcional via `--pin` para builds reproduzíveis.
  No Windows prefere a CLI `7z` (winget install 7zip.7zip) e cai em
  `py7zr` (instalado sob demanda) quando a CLI não está disponível.
- Distribuição = copiar a pasta inteira para a máquina do cliente.
  Atualização = substituir a pasta (config persiste em `user_data_dir`,
  fora do projeto).

### Invariantes não-óbvias

- **Nomes de arquivo são contratos.** O formato `%Y%m%d_%H%M%S.ts` é
  compartilhado por capture, player e cleaner via `strptime`. Mudar o
  padrão exige editar os três.
- **`segment_duration` afeta o GOP.** Em [capture.py:46-48](modules/capture.py#L46-L48)
  o GOP e os keyframes forçados são derivados de `segment_time` para
  garantir que cada segmento comece em keyframe. Não mexa em um sem o outro.
- **`config` é compartilhado por referência.** `main.py` passa o mesmo
  `dict` para os managers **e** para o `ServerState`. Mutações fazem
  `config.update(...)`, não reatribuição. Substituir o dict quebra a propagação.
- **`config["segment_folder"]` é sobrescrito em `main.py`** pelo
  `segments_dir()` antes de criar os managers, apontando para o repo em
  dev. Resultado: o JSON pode ter o valor antigo "segments" e ainda funcionar.
- **`delay_seconds` mínimo é 10s** (clamp em
  [`PlayerManager.set_delay`](modules/player.py#L48)) e validado também
  no `ServerState.apply_config()` antes de persistir.
- **Mudanças em campos do FFmpeg exigem restart da captura.** `ServerState`
  detecta diffs em `capture_device`, `test_mode`, `segment_duration` e
  `video_quality` e chama `capture.request_restart()`. Mudar só
  delay/monitor não interrompe a captura.
- **Whitelist de campos no POST `/api/config`.** `_ALLOWED_FIELDS` em
  config_server.py define o que pode mutar via API. Campo fora dela é
  silenciosamente descartado.
- **Single-instance via port-probe** roda **antes** de `setup_logging()`
  para não abrir o arquivo de log enquanto a primeira instância o mantém
  aberto (problemático em Windows).
- **mpv no Mac é um `.app` bundle, não um binário standalone.** Tem
  dylibs em `Contents/MacOS/lib/` e `Contents/Frameworks/` com
  `@executable_path` relativos. Por isso `fetch_binaries.py` usa
  `mode="app_bundle"` no Mac, e `paths.bundled_binary("mpv")` no Mac
  resolve para `mpv.app/Contents/MacOS/mpv` em vez de procurar `bin/mpv`.
- **Setup completo = flag exists + (test_mode OR not placeholder).** Em
  test_mode o `capture_device` continua sendo o placeholder mas o setup
  é considerado completo — wizard não aparece mais.

## Convenções

- Comentários e strings de usuário em português; nomes de identificadores
  em inglês.
- README, INSTALL.md e mensagens de erro mantêm o tom do Estúdio AB
  (sóbrio, sem emoji, frases longas e declarativas — ver design system).
- Logs sempre via `log` (do `logging_setup`) — nunca `print()` direto no
  código de produção. Em main.py há `tty()` para escrita decorativa em
  terminal que vira no-op sem TTY.

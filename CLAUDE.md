# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Sobre o projeto

Sistema de playback com delay configurável: captura HDMI (placa via DirectShow no Win,
AVFoundation no Mac) ou câmera, grava segmentos `.ts` curtos e os reproduz em
fullscreen com N segundos de atraso. Distribuído como `.zip` auto-contido para
**Mac (arm64) e Win (x64)** — cliente leigo extrai e clica duplo, sem instalar
FFmpeg/MPV separadamente. Primeira execução abre um **wizard guiado de 4 telas**
no navegador (placa de captura → monitor → delay → iniciar).

Inclui painel web embutido com fidelidade ao design system Estúdio AB (Neue Haas
Grotesk Display Thin + Calling Code, hairlines, gradiente assinado, sem rounded
corners). Painel e wizard são views da mesma SPA HTML/JS.

## Plataforma e dependências

- **Runtime:** stdlib only. NUNCA adicione dep PyPI ao código que roda.
- **Build time:** PyInstaller + Pillow + cairosvg, instalados apenas pelo
  `build.py` / GitHub Actions. Não viram dep de runtime.
- **Binários:** `ffmpeg` e `mpv` são **embarcados** no `.zip` distribuído.
  Em modo dev, `bundled_binary()` resolve em `vendor/<plat>/` (populado
  pelo `scripts/fetch_binaries.py`) ou cai em `shutil.which`.
- **Plataformas suportadas:**
  - Mac arm64 (production): AVFoundation, `mpv.app` bundle inteiro
  - Win x64 (production): DirectShow, `mpv.exe` standalone
  - Linux: apenas modo `--test` (lavfi)

## Comandos

```
# Dev — roda do source
python main.py --test                        # MODO DE TESTE: fonte sintética (lavfi)
python -m unittest discover -s tests -v      # roda toda a suite

# Build do .zip distribuível
python scripts/fetch_binaries.py             # baixa ffmpeg + mpv para vendor/
python scripts/generate_icons.py             # gera .icns/.ico do symbol.svg
python build.py                              # PyInstaller + zip
python build.py --clean --console            # debug build

# Cross-platform via GitHub Actions
git tag v1.0.0 && git push --tags            # dispara matriz {mac, win} + release
```

Não há lint configurado. PyInstaller e Pillow/cairosvg são build-time only.

### Modo de teste

`--test` (ou `"test_mode": true` no config) usa `lavfi testsrc2` — fonte
sintética com clock visível, sem placa. Funciona em qualquer plataforma com
FFmpeg + MPV instalados. Para `python main.py --test` rodar do source, instale
`brew install ffmpeg mpv` (Mac) ou rode `python scripts/fetch_binaries.py`
para popular `vendor/` (mesmo binário usado no `.app`).

### Suite de testes (79 testes)

- **Unit tests** ([test_player.py](tests/test_player.py), [test_cleaner.py](tests/test_cleaner.py),
  [test_capture.py](tests/test_capture.py), [test_main.py](tests/test_main.py),
  [test_paths.py](tests/test_paths.py), [test_capture_devices.py](tests/test_capture_devices.py),
  [test_monitors.py](tests/test_monitors.py), [test_config_server.py](tests/test_config_server.py))
  cobrem: parsing de timestamps, filtragem por delay, progresso de buffer,
  clamping do delay, limpeza por idade, montagem FFmpeg (dshow/avfoundation/lavfi),
  validação de config, resolução de paths cross-platform (dev vs frozen),
  parser de dispositivos (Win + Mac), enumeração de monitores, endpoints HTTP
  (incluindo wizard: setup-status, capture-devices, setup-complete).
  Não tocam o filesystem real além de `tempfile`.
- **Integração** ([tests/test_integration.py](tests/test_integration.py)) — sobe o
  `CaptureManager` em modo de teste, deixa o FFmpeg rodar ~8s, valida que
  segmentos `.ts` foram gerados com timestamps corretos. Skip automático se
  `ffmpeg` não estiver no PATH.
- Helper [tests/_helpers.py](tests/_helpers.py) tem `TempSegments` para
  fabricar arquivos `.ts` com timestamps arbitrários.

Durante a execução em dev TTY: `P` abre o painel web, `+`/`-` ajusta delay
em passos de 30s (mínimo 10s), `r` recarrega `config.json` sem reiniciar
threads, `q` encerra. Em modo `.app` empacotado (sem TTY) o controle é
todo pelo painel; o teclado fica inativo automaticamente.

### Build do executável

```
python build.py            # PyInstaller --onedir --windowed para o SO atual
python build.py --clean    # apaga build/, dist/, .spec antes
python build.py --console  # mantém terminal visível (debug)
python build.py --skip-fetch  # assume vendor/ pronto
```

Pacote inclui `webui/` inteira (HTML/CSS/JS/fontes/assets) via `--add-data`,
`ffmpeg` via `--add-binary`, `mpv.app/` inteiro via `--add-data` (preserva
@executable_path do mpv para suas dylibs). No Mac, `patch_info_plist()`
injeta `NSCameraUsageDescription` no Info.plist gerado.

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
  Empacotado: resolve `webui/` via `sys._MEIPASS`.

- [modules/monitors.py](modules/monitors.py) — enumeração cross-platform:
  ctypes/EnumDisplayMonitors no Win, `system_profiler` no Mac, `xrandr` no
  Linux. Fallback `[Monitor 0, Monitor 1]` em falha.

- [modules/capture_devices.py](modules/capture_devices.py) — enumeração de
  placas: dshow no Win, avfoundation no Mac. Parser de stderr do ffmpeg.
  Usado pelo wizard para popular o dropdown.

- [modules/paths.py](modules/paths.py) — resolução cross-platform de paths
  para config/segments/logs e do diretório `bin/` dos binários embarcados.
  Em dev usa o repo; em frozen vai pro local canônico do SO. `bundled_binary()`
  resolve ffmpeg/mpv olhando primeiro `sys._MEIPASS/bin`, depois
  `<exe>.parent/bin` e `Contents/Resources/bin` (Mac), com fallback para
  `shutil.which`. Caso especial Mac: `mpv` vem como `.app` bundle inteiro,
  então `_resolve_mac_mpv` aponta pra `mpv.app/Contents/MacOS/mpv`.

- [modules/logging_setup.py](modules/logging_setup.py) — `RotatingFileHandler`
  em `log_path()` (5MB × 3 backups). Adiciona console handler só se há TTY
  e não estamos frozen. Neutraliza `sys.stdout = None` que o PyInstaller
  `--windowed` cria no Mac, evitando AttributeError em prints residuais.

- [main.py](main.py) — orquestra: faz **single-instance check via port-probe**
  (`detect_running_instance()`) antes de qualquer coisa; se já existe app
  rodando, abre o browser para ele e sai. Senão: bootstrap de config + log,
  sobe `ConfigServer`, threads dos managers, polling de teclado
  (cross-platform: `msvcrt` Win, `termios + select` Posix, no-op sem TTY).
  Em modo frozen, abre o browser automaticamente.

### Frontend (webui/)

- [index.html](webui/index.html) — duas seções: `#wizard` (4 steps, hidden
  por default) e `#dashboard`. JS decide qual mostrar consultando
  `/api/setup-status` no boot.
- [app.js](webui/app.js) — state machine do wizard (`WIZARD.step` 1..4),
  chamada a `/api/capture-devices` e `/api/monitors` para popular as telas,
  POST `/api/setup-complete` no final. Dashboard mantém o polling existente.
- [style.css](webui/style.css) — tokens AB locais + estilos do wizard
  (`.wizard__step`, `.wizard__steps-rail`, fade transition entre steps).

### Build & distribuição

- [build.py](build.py) — invoca `fetch_binaries.py` se vendor faltar,
  `generate_icons.py` se faltarem ícones, depois PyInstaller `--onedir
  --windowed` com `--add-binary` (ffmpeg) e `--add-data` (mpv.app/, webui/).
  Pós-processo: `patch_info_plist()` injeta `NSCameraUsageDescription`.
  Zipa o output com `INSTALL.txt`.

- [scripts/fetch_binaries.py](scripts/fetch_binaries.py) — baixa ffmpeg e
  mpv estáticos de fontes canônicas (evermeet, gyan, eko5624/mpv-mac,
  shinchiro). Idempotente. Suporta mode `binary` (extrai um arquivo) e
  `app_bundle` (extrai árvore inteira para mpv.app no Mac). Validação por
  tamanho mínimo; SHA-256 opcional via `--pin` para builds reproduzíveis.

- [scripts/generate_icons.py](scripts/generate_icons.py) — usa Pillow +
  cairosvg para rasterizar `symbol.svg` em 10 tamanhos, depois `iconutil`
  (Mac) para gerar `.icns` e Pillow direto para `.ico`. Idempotente.

- [.github/workflows/build.yml](.github/workflows/build.yml) — matriz
  `{macos-14, windows-2022}`. Cada job: setup Python 3.11, instala
  PyInstaller+Pillow+cairosvg (Win adiciona py7zr para extrair .7z),
  roda fetch_binaries + testes + build.py, sobe artifact. Push de tag
  `v*.*.*` cria release com os dois .zip anexados.

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
  `segments_dir()` antes de criar os managers. Em frozen isso aponta pro
  user data dir; em dev aponta pro repo. Resultado: o JSON pode ter o
  valor antigo "segments" e ainda funcionar.
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
- README, INSTALL.txt e mensagens de erro mantêm o tom do Estúdio AB
  (sóbrio, sem emoji, frases longas e declarativas — ver design system).
- Logs sempre via `log` (do `logging_setup`) — nunca `print()` direto no
  código de produção. Em main.py há `tty()` para escrita decorativa em
  terminal que vira no-op em frozen.

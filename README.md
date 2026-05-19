# Video Delay System
### Estúdio AB — Sistema de playback com delay configurável

Captura sinal de vídeo (placa HDMI no Win/Mac ou câmera AVFoundation no Mac) e
exibe em fullscreen com N segundos de atraso. Roda diretamente do código-fonte
Python; FFmpeg e MPV são baixados na pasta do projeto durante o setup inicial
e usados localmente, sem alterar o sistema operacional.

---

## Instalação

Veja **[INSTALL.md](INSTALL.md)** para o passo a passo completo, requisitos
do sistema e solução de problemas. Em resumo:

| Plataforma | Setup (uma vez) | Iniciar |
|---|---|---|
| macOS 11+ | duplo-clique em `install.command` | duplo-clique em `run.command` |
| Windows 10/11 | duplo-clique em `install.bat` | duplo-clique em `run.bat` |

Pré-requisito único: **Python 3.11+** instalado pelo cliente
(python.org). FFmpeg e MPV são baixados automaticamente pelo `install`.

Na primeira execução o navegador abre com um wizard de 4 telas
(placa → monitor → delay → iniciar). Toda configuração fica salva em
`~/Library/Application Support/VideoDelay/` (Mac) ou `%APPDATA%\VideoDelay\`
(Win) — atualizar o projeto preserva a configuração.

---

## Para o desenvolvedor

### Como funciona

```
[Câmera / Placa HDMI]
        │
        ▼ FFmpeg (dshow Win, avfoundation Mac, lavfi em teste)
[segments/YYYYMMDD_HHMMSS.ts]
        │
        ▼ MPV fullscreen com delay
[Monitor escolhido]

                                      ConfigServer (HTTP localhost:8765)
                                              │
                                              ▼
                                      [Painel/Wizard no navegador]
```

Quatro threads daemon coordenadas pelo `main.py`:
- `CaptureManager` — FFmpeg gravando segmentos de 5s
- `PlayerManager` — MPV lendo segmentos com `N segundos` de atraso
- `CleanerManager` — apaga segmentos mais velhos que `max_segment_age_seconds`
- `ConfigServer` — HTTP server servindo o painel/wizard e mutando o config compartilhado

### Dependências

**Runtime:** apenas Python 3.11+ e a biblioteca padrão. Nenhuma dependência
PyPI no código que roda em produção. FFmpeg e MPV são baixados pelo
`scripts/fetch_binaries.py` para a pasta `vendor/` na raiz do projeto e
resolvidos por `modules.paths.bundled_binary()`.

**Setup:** o `install.command`/`install.bat` apenas invoca
`python scripts/fetch_binaries.py`. Idempotente — pode rodar várias vezes.

### Comandos

```bash
# Setup inicial (baixa ~150 MB de binarios para vendor/)
python scripts/fetch_binaries.py

# Rodar o sistema
python main.py                              # producao (precisa de placa configurada)
python main.py --test                       # modo sintetico (lavfi testsrc2)

# Suite de testes (79 testes)
python -m unittest discover -s tests -v
```

Em modo dev, `config.json` e `segments/` ficam na pasta do repo. O painel
sobe em `http://127.0.0.1:8765/` (tecla `P` abre no navegador). Para
descobrir placas sem o wizard:

```bash
python -c "from modules.capture_devices import list_capture_devices; print(list_capture_devices())"
```

### Controles no terminal

| Tecla | Ação |
|-------|------|
| `P`   | Abre o painel no navegador |
| `+/-` | Ajusta delay em 30s (mínimo 10s) |
| `r`   | Recarrega config.json do disco |
| `q`   | Encerra o sistema |

Sem TTY (raro — exige ambiente sem terminal), o teclado fica inativo e o
controle é todo pelo painel web.

### Suite de testes

```bash
python -m unittest discover -s tests -v
```

79 testes cobrindo paths, logging, montagem de comando FFmpeg
(dshow/avfoundation/lavfi), filtragem por delay, validação cruzada, endpoints
HTTP (incluindo wizard), parser de dispositivos de captura, enumeração de
monitores. Integração com FFmpeg real é pulada automaticamente se o binário
não estiver disponível.

### Estrutura do projeto

```
video-delay/
├── main.py                  ← orquestra threads + servidor + single-instance lock
├── config.json              ← config inicial
├── install.command          ← bootstrap macOS (Python + fetch_binaries)
├── install.bat              ← bootstrap Windows
├── run.command              ← launcher macOS (duplo-clique)
├── run.bat                  ← launcher Windows
├── run-test.command         ← launcher modo teste macOS
├── run-test.bat             ← launcher modo teste Windows
├── modules/
│   ├── capture.py               ← FFmpeg cross-platform (dshow/avfoundation/lavfi)
│   ├── player.py                ← MPV fullscreen via IPC
│   ├── cleaner.py               ← apaga segmentos velhos
│   ├── monitors.py              ← enumera monitores (ctypes/system_profiler/xrandr)
│   ├── capture_devices.py       ← enumera placas de captura
│   ├── config_server.py         ← HTTP server: painel + wizard + API
│   ├── paths.py                 ← resolução de paths cross-platform
│   └── logging_setup.py         ← rotating file log
├── scripts/
│   └── fetch_binaries.py        ← baixa ffmpeg/mpv estáticos para vendor/
├── webui/                       ← painel + wizard (HTML/CSS/JS, design system AB)
│   ├── index.html
│   ├── app.js
│   ├── style.css
│   ├── logo.js
│   ├── fonts/                   ← Neue Haas Grotesk + Calling Code
│   └── assets/                  ← symbol.svg (SVG do design system)
├── vendor/                      ← FFmpeg + MPV baixados (gitignored)
└── tests/                       ← suite unittest (79 testes)
```

### Onde ficam os dados em produção

| Plataforma | Caminho |
|---|---|
| macOS  | `~/Library/Application Support/VideoDelay/` |
| Windows | `%APPDATA%\VideoDelay\` |
| Linux (modo teste) | `~/.config/VideoDelay/` |

Cada um contém: `config.json`, `segments/`, `logs/videodelay.log`,
`.setup_complete` (flag do wizard).

---

## Decisões arquiteturais relevantes

**Stdlib only em runtime.** Servidor HTTP é `http.server` da stdlib;
enumeração de monitores usa ctypes (Win) e `system_profiler` (Mac);
parsing de dispositivos usa subprocess no FFmpeg. Nenhuma dep PyPI em
runtime — o cliente só precisa do Python instalado.

**FFmpeg + MPV vivem em `vendor/`.** O setup inicial baixa builds estáticos
validados (evermeet, gyan, eko5624/mpv-mac, shinchiro) para
`vendor/<plataforma>/` na raiz do projeto. `paths.bundled_binary()`
resolve primeiro `vendor/`, depois cai em `shutil.which` (PATH do sistema).
Isso garante que o cliente nunca tem conflito com versões antigas de
FFmpeg/MPV instaladas no SO, e que cada projeto carrega os seus binários.

**Distribuição via cópia da pasta.** Não há build, instalador, .app nem
.zip. Para distribuir, copie a pasta do projeto para a máquina do cliente
(qualquer método: AirDrop, pen-drive, SSH, git clone) e rode o `install`
local. Atualizar significa substituir a pasta — a config persiste em
`~/Library/Application Support/VideoDelay/` (fora do projeto).

**First-run wizard como view única.** O wizard e o dashboard são duas
seções do mesmo `index.html`. Boot do JS verifica `/api/setup-status`; se
incompleto, mostra wizard. Após `/api/setup-complete`, troca para
dashboard sem reload — zero duplicação de assets/fonts/CSS.

**Single-instance via port-probe.** No boot, `main.py` faz GET
`/api/status` em 8765–8774. Se algum responder com a assinatura do nosso
app, abre o browser para a instância existente e sai. Evita ter dois
FFmpegs escrevendo na mesma pasta `segments/`. Solução barata, sem
`fcntl`.

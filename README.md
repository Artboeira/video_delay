# Video Delay System
### Estúdio AB — Sistema de playback com delay configurável

Captura sinal de vídeo (placa HDMI no Win/Mac ou câmera AVFoundation no Mac) e
exibe em fullscreen com N segundos de atraso. Distribuído como `.zip`
auto-contido para Mac e Windows — o cliente extrai, clica duplo e segue um
wizard guiado de 4 telas. Sem terminal, sem instalar FFmpeg/MPV separadamente.

---

## Para o cliente final

Baixe o `.zip` da plataforma, extraia, e siga o `INSTALL.txt` que vem dentro:

| Plataforma | Arquivo | Tamanho |
|---|---|---|
| macOS 11+ (Apple Silicon) | `VideoDelay-mac.zip` | ~180MB |
| Windows 10/11 (x64) | `VideoDelay-win.zip` | ~180MB |

Na primeira execução o navegador abre automaticamente com um assistente que
detecta as placas de captura e os monitores conectados. Toda configuração
fica salva em `~/Library/Application Support/VideoDelay/` (Mac) ou
`%APPDATA%\VideoDelay\` (Win) — atualizar o app (drag-and-drop nova versão)
preserva a config.

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

**Runtime:** Python 3.11+ apenas em modo dev. No `.zip` distribuído tudo
(Python, stdlib, ffmpeg, mpv) já vai embarcado.

**Build-time (no CI ou local):**
```bash
pip install pyinstaller pillow cairosvg
```
PyInstaller para empacotar; Pillow + cairosvg para gerar ícones a partir do
SVG do design system. Nenhuma destas dependências roda em produção.

### Rodando do source

```bash
# Modo de teste (sem placa de captura — fonte sintética testsrc2)
python main.py --test
```

Em modo dev, `config.json` e `segments/` ficam na pasta do repo. O painel sobe
em `http://127.0.0.1:8765/` (tecla `P` abre no navegador). Para descobrir
placas:

```bash
python -c "from modules.capture_devices import list_capture_devices; print(list_capture_devices())"
```

### Controles no terminal (modo dev / TTY)

| Tecla | Ação |
|-------|------|
| `P`   | Abre o painel no navegador |
| `+/-` | Ajusta delay em 30s (mínimo 10s) |
| `r`   | Recarrega config.json do disco |
| `q`   | Encerra o sistema |

Em modo `.app` empacotado, o navegador abre automaticamente e o teclado não
está disponível — controle é todo pelo painel.

### Suite de testes

```bash
python -m unittest discover -s tests -v
```

79 testes cobrindo paths, logging, montagem de comando FFmpeg (dshow/avfoundation/lavfi),
filtragem por delay, validação cruzada, endpoints HTTP (incluindo wizard), parser de
dispositivos de captura, enumeração de monitores. Integração com FFmpeg real é
pulada automaticamente se o binário não estiver disponível.

### Build do .zip

```bash
# Local (gera só pra plataforma corrente)
python build.py             # baixa vendor/ se faltar, builda, zipa
python build.py --clean     # apaga build/, dist/, .spec antes
python build.py --console   # mantém terminal visível (debug)

# Cross-platform (Mac + Win em paralelo) — via GitHub Actions
# Push de tag v*.*.* dispara build matricial e cria release com os zips:
git tag v1.0.0
git push --tags
```

A primeira execução baixa ~140MB de binários (ffmpeg + mpv) para `vendor/`.
PyInstaller embarca tudo. O `INSTALL.txt` é gerado automaticamente e incluído
no `.zip`.

### Estrutura do projeto

```
video-delay/
├── main.py              ← orquestra threads + servidor + single-instance lock
├── build.py             ← empacota com PyInstaller, gera .zip
├── config.json          ← config inicial (em frozen, vai pra user data dir)
├── entitlements.plist   ← permissão de Câmera no Mac (AVFoundation)
├── modules/
│   ├── capture.py           ← FFmpeg cross-platform (dshow/avfoundation/lavfi)
│   ├── player.py            ← MPV fullscreen via IPC
│   ├── cleaner.py           ← apaga segmentos velhos
│   ├── monitors.py          ← enumera monitores (ctypes/system_profiler/xrandr)
│   ├── capture_devices.py   ← enumera placas de captura
│   ├── config_server.py     ← HTTP server: painel + wizard + API
│   ├── paths.py             ← resolução de paths cross-platform
│   └── logging_setup.py     ← rotating file log + null-safe stdout
├── scripts/
│   ├── fetch_binaries.py    ← baixa ffmpeg/mpv estáticos para vendor/
│   └── generate_icons.py    ← gera symbol.icns/symbol.ico do SVG
├── webui/                   ← painel + wizard (HTML/CSS/JS, design system AB)
│   ├── index.html
│   ├── app.js               ← state machine do wizard + dashboard
│   ├── style.css            ← tokens AB (cores, tipografia, gradiente)
│   ├── logo.js
│   ├── fonts/               ← Neue Haas Grotesk + Calling Code (locais)
│   └── assets/              ← symbol.svg, symbol.icns, symbol.ico
├── tests/                   ← suite unittest (79 testes)
└── .github/workflows/
    └── build.yml            ← CI matriz {mac-arm64, win-x64} → .zip + release
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

**Stdlib only em runtime.** A única exceção é build time (PyInstaller, Pillow,
cairosvg). Servidor HTTP é `http.server` da stdlib; enumeração de monitores
usa ctypes (Win) e `system_profiler` (Mac). Nenhuma dep PyPI no `.app`.

**ffmpeg + mpv embarcados.** O `.zip` distribuído tem ~180MB, mas o cliente
não precisa instalar nada além de extrair. `scripts/fetch_binaries.py` baixa
builds estáticos validados (evermeet, gyan, eko5624/mpv-mac, shinchiro) e
valida tamanho mínimo. Para builds reproduzíveis, pinar SHA-256 no
`vendor/lockfile.json` via `--pin`.

**Paths cross-platform.** Em modo dev tudo fica no repo (conveniente para
iterar). Em modo frozen `paths.user_data_dir()` retorna o local canônico do SO,
e `bundled_binary()` resolve ffmpeg/mpv embarcados dentro do bundle (ou cai em
`shutil.which` em dev). Substituir o `.app` por uma versão nova preserva config.

**First-run wizard como view única.** O wizard e o dashboard são duas seções
do mesmo `index.html`. Boot do JS verifica `/api/setup-status`; se incompleto,
mostra wizard. Após `/api/setup-complete`, troca para dashboard sem reload —
zero duplicação de assets/fonts/CSS.

**Single-instance via port-probe.** No boot, `main.py` faz GET
`/api/status` em 8765–8774. Se algum responder com a assinatura do nosso app,
abre o browser para a instância existente e sai. Evita ter dois FFmpegs
escrevendo na mesma pasta `segments/`. Solução barata, sem `fcntl`.

**No code signing por enquanto.** O cliente vê o aviso "desenvolvedor não
identificado" na primeira execução e usa o procedimento de duplo-clique do
INSTALL.txt. Para distribuição em escala maior, instalar Apple Developer ID
($99/ano) + EV Code Signing Win (~$300/ano) e plugar no CI.

---

## Solução de problemas

**"App não pode ser aberto" (macOS):** botão direito → Abrir → Abrir novamente.
Funciona pra sempre depois.

**"SmartScreen avisou que é desconhecido" (Win):** "Mais informações" →
"Executar mesmo assim".

**Painel não abre automaticamente:** abra manualmente `http://127.0.0.1:8765/`
(porta pode ir até 8774 se a anterior estiver ocupada).

**Wizard aparece toda vez:** apague `~/Library/Application Support/VideoDelay/.setup_complete`
para refazer setup do zero.

**Tela preta no playback:** verifique no painel se o monitor selecionado é
o correto e se a placa está conectada antes do app iniciar.

**Permissão de câmera bloqueada (Mac):** Configurações do Sistema → Privacidade
e Segurança → Câmera → ativar VideoDelay.

**Alto uso de CPU:** painel → seção Captura → preset `ultrafast`, crf 23.

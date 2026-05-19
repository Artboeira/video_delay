# Video Delay System — Instalação

Sistema de captura HDMI com playback em delay. Esta página é o passo a passo
de instalação e os procedimentos para resolver problemas comuns. Para a
visão geral do projeto e arquitetura, ver [README.md](README.md).

---

## Requisitos

| Item | Versão | Como obter |
|---|---|---|
| Python 3 | 3.11 ou superior | macOS: [python.org/downloads/macos](https://www.python.org/downloads/macos/) · Windows: [python.org/downloads/windows](https://www.python.org/downloads/windows/) |
| Conexão à internet | Apenas no primeiro setup | Cerca de 150 MB de FFmpeg + MPV são baixados uma única vez |
| Espaço em disco | 500 MB livres | Inclui binários, segmentos temporários e logs |
| Placa de captura HDMI | Qualquer modelo USB | Reconhecida pelo SO como câmera (Windows: DirectShow; macOS: AVFoundation) |

Nenhuma outra dependência é necessária. O sistema usa apenas a biblioteca
padrão do Python — FFmpeg e MPV são baixados na pasta `vendor/` do projeto
e não interferem com instalações existentes no sistema.

---

## Instalação no macOS

**1. Verifique se o Python 3 está instalado.** Abra o Terminal
(Aplicativos → Utilitários → Terminal) e rode:

```
python3 --version
```

Se aparecer `Python 3.11.x` ou superior, está pronto. Se não, baixe o
instalador em [python.org/downloads/macos](https://www.python.org/downloads/macos/)
e siga o assistente até o fim.

**2. Coloque a pasta do projeto onde quiser.** Recomendado: `~/Aplicativos/`
ou `~/Documents/`. Evite Desktop ou caminhos com acentos ou espaços.

**3. Rode a instalação.** No Finder, abra a pasta do projeto e dê
**duplo-clique em `install.command`**. Uma janela do Terminal vai abrir,
validar o Python e baixar FFmpeg + MPV. Demora 1 a 3 minutos dependendo
da sua conexão.

> Se aparecer um aviso "não pode ser aberto porque é de um desenvolvedor
> não identificado": clique com o **botão direito** em `install.command` →
> **Abrir** → **Abrir** no diálogo. Só precisa fazer isso uma vez por arquivo.

**4. Permita o acesso à câmera quando solicitado.** Na primeira execução
o macOS pergunta se o sistema pode acessar a câmera (necessário para placas
de captura via AVFoundation). Aceite. Se negar por engano, ative em
Configurações do Sistema → Privacidade e Segurança → Câmera.

---

## Instalação no Windows

**1. Verifique se o Python 3 está instalado.** Abra o PowerShell ou Prompt
de Comando e rode:

```
py --version
```

Se aparecer `Python 3.11.x` ou superior, está pronto. Se não, baixe o
instalador em [python.org/downloads/windows](https://www.python.org/downloads/windows/).

> **CRÍTICO:** na primeira tela do instalador do Python, marque a opção
> **"Add Python to PATH"** antes de clicar em Install. Sem isso o sistema
> não vai conseguir encontrar o Python e a instalação falha.

**2. Coloque a pasta do projeto onde quiser.** Recomendado: `C:\VideoDelay\`.
Evite caminhos com acentos, espaços ou dentro de OneDrive (que move arquivos
em segundo plano).

**3. Rode a instalação.** No Explorador, abra a pasta do projeto e dê
**duplo-clique em `install.bat`**. Uma janela preta vai abrir, validar o
Python e baixar FFmpeg + MPV. Demora 1 a 3 minutos.

> Se o SmartScreen mostrar "Windows protegeu seu computador": clique em
> **Mais informações** → **Executar mesmo assim**.

---

## Como iniciar o sistema

Após a instalação, basta **duplo-clique em `run.command`** (macOS) ou
**`run.bat`** (Windows). O navegador padrão abre automaticamente em
`http://127.0.0.1:8765/` com o painel de configuração.

Na primeira execução o painel mostra um **wizard de 4 telas**:

1. **Placa de captura** — escolha a entrada HDMI (auto-detectada)
2. **Monitor de saída** — escolha o display de fullscreen
3. **Delay inicial** — segundos de atraso (mínimo 10)
4. **Iniciar** — confirma e inicia a captura

Configurações são salvas em:

| Sistema | Caminho |
|---|---|
| macOS | `~/Library/Application Support/VideoDelay/` |
| Windows | `%APPDATA%\VideoDelay\` |

A janela do Terminal/Prompt fica aberta mostrando logs. Para encerrar,
pressione `q` na janela, feche-a, ou clique no botão "Encerrar" no painel.

### Modo de teste

Para validar a instalação sem placa de captura conectada, use
`run-test.command` (macOS) ou `run-test.bat` (Windows). Em vez de capturar
HDMI, o sistema gera uma fonte sintética com clock visível — útil para
confirmar que FFmpeg, MPV e o playback estão funcionando.

### Trocar entre modo teste e modo real

Depois de testar em modo sintético, para passar a usar a placa de captura
real:

1. **Conecte a placa HDMI** antes de iniciar — ela precisa estar plugada
   no momento em que o sistema enumera dispositivos.
2. Feche a janela do `run-test` (tecla `q` ou fechar a janela).
3. (Opcional, recomendado) Apague o arquivo `.setup_complete` para forçar
   o wizard a reaparecer:

   | Sistema | Caminho a apagar |
   |---|---|
   | macOS | `~/Library/Application Support/VideoDelay/.setup_complete` |
   | Windows | `%APPDATA%\VideoDelay\.setup_complete` |

4. Duplo-clique em `run.command` / `run.bat` (sem `-test`).
5. Wizard reaparece: escolha placa → monitor → delay → Iniciar.

> **Sem apagar a flag**: o painel ainda permite trocar a placa em
> **Configurações → Captura → Dispositivo**. A captura reinicia automaticamente
> quando você salva. Use essa rota se quiser preservar histórico de log e
> configurações de delay/qualidade.

---

## Iniciar com o sistema (auto-start)

Para que o Video Delay suba sozinho no boot da máquina — útil em instalações
permanentes — há dois caminhos. Escolha conforme o cenário.

### Windows — pasta Startup (mais simples)

Funciona sem privilégio admin, dispara após o login do usuário.

1. **Botão direito** em `run.bat` → **Criar atalho**. Um arquivo
   `run.bat - Atalho` aparece na mesma pasta.
2. **`Win+R`** → digite `shell:startup` → Enter. Abre a pasta de auto-start
   do usuário atual (`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`).
3. **Mova o atalho** para essa pasta.
4. (Opcional) Botão direito no atalho → **Propriedades** → aba **Atalho** →
   campo **Executar**: troque **"Janela normal"** por **"Minimizada"** para
   o terminal não atrapalhar visualmente.

Reiniciar a máquina e fazer login dispara o `run.bat`. O navegador padrão
abre com o painel automaticamente, o MPV vai pro monitor configurado e a
captura começa após o tempo de buffer (delay configurado).

### Windows — Task Scheduler (mais robusto)

Preferível em instalação dedicada (kiosk, sinalização digital), porque
permite: reiniciar automaticamente em caso de crash, atraso após boot
(deixa a placa USB inicializar), execução mesmo com sessão bloqueada.

1. `Win+R` → `taskschd.msc` → Enter
2. Painel direito → **Criar Tarefa Básica** (não "Criar Tarefa" — esse é
   o avançado)
3. Nome: `Video Delay System` → Avançar
4. Disparador: **"Quando eu fizer logon"** → Avançar
5. Ação: **"Iniciar um programa"** → Avançar
6. Programa/script: cole o caminho completo do `run.bat`, exemplo
   `C:\VideoDelay\run.bat`
7. "Iniciar em": cole apenas a pasta, exemplo `C:\VideoDelay\`
8. Avançar → Concluir
9. Volte na tarefa criada → botão direito → **Propriedades**:
   - Aba **Geral** → marque **"Executar somente quando o usuário estiver
     conectado"** (precisa da sessão pra acessar display)
   - Aba **Configurações** → marque **"Se a tarefa falhar, reiniciá-la a
     cada 1 minuto"**, limite de **3 reinícios**
   - Aba **Disparadores** → editar o disparador → marque **"Atrasar tarefa
     por: 30 segundos"** (dá tempo da placa USB inicializar)

### macOS — Login Items

1. **Configurações do Sistema** → **Geral** → **Itens de Início de Sessão**
2. Clique em **+** abaixo da lista "Abrir no login"
3. Navegue até a pasta do projeto e selecione `run.command`
4. Reiniciar → fazer login dispara o run.command

Para janela do Terminal não aparecer, marque a opção "Ocultar" na linha
do item. Os logs continuam sendo gravados no arquivo `videodelay.log`.

### Encerrar uma instância em auto-start

Independentemente do método de start, para encerrar:
- **Pelo painel**: abrir `http://127.0.0.1:8765/` → botão **Encerrar**
- **Pelo Terminal/Prompt** (se a janela estiver visível): tecla `q`
- **Forçado**: encerre o processo `python` no Gerenciador de Tarefas
  (Win) ou Activity Monitor (Mac). O lock de single-instance é apenas
  port-probe, então qualquer encerramento desbloqueia a próxima execução.

---

## Solução de problemas

### "Python não encontrado" no install.command/install.bat

- **macOS**: verifique se você baixou do site oficial python.org (não da
  Mac App Store). Após instalar, **feche e reabra o Finder** antes de tentar
  o `install.command` novamente — o PATH é recarregado.
- **Windows**: reinstale o Python marcando "Add Python to PATH" na
  primeira tela. Se já tinha instalado, há um botão "Modify" no instalador
  para adicionar ao PATH sem reinstalar tudo.

### Download dos binários falhou (install)

O script `scripts/fetch_binaries.py` baixa de fontes públicas:
evermeet.cx (FFmpeg Mac), gyan.dev (FFmpeg Win), eko5624/mpv-mac (MPV Mac),
shinchiro (MPV Win). Falhas comuns:

- **Firewall ou antivírus bloqueando**: temporariamente desative, rode o
  install, reative. Adicione `vendor\` à lista de exclusões do antivírus
  (especialmente Windows Defender, que escaneia binários a cada execução).
- **Sem internet**: confirme acesso a `https://evermeet.cx` e
  `https://www.gyan.dev` no navegador.
- **Proxy corporativo**: defina as variáveis `HTTP_PROXY` e `HTTPS_PROXY`
  no terminal antes de rodar `install`.
- **Windows: arquivo .7z não extrai**: o `fetch_binaries.py` precisa de
  uma CLI 7-Zip real porque o MPV usa o filtro BCJ2 (que extratores
  Python-puro como `py7zr` não suportam). Ordem de busca, automática:
  1. `7z` / `7za` / `7zr` no PATH
  2. Instalação padrão em `C:\Program Files\7-Zip\`
  3. Auto-download de `7zr.exe` standalone de 7-zip.org para
     `vendor\_tools\7zr.exe` (~1 MB, sem precisar de admin ou pacote)

  Se o auto-download falhar (rede bloqueada, antivírus corporativo
  segurando `.exe` baixados), saídas alternativas:
  - Instalar 7-Zip normalmente: `winget install 7zip.7zip` ou baixar de
    [7-zip.org](https://www.7-zip.org/).
  - Baixar manualmente https://7-zip.org/a/7zr.exe e salvar como
    `vendor\_tools\7zr.exe` na pasta do projeto, depois rodar `install.bat`
    de novo.

Se nada disso resolveu, baixe os binários manualmente e coloque na pasta
correta:

```
vendor/mac-arm64/ffmpeg            (executável)
vendor/mac-arm64/mpv.app/          (bundle inteiro)
vendor/win-x64/ffmpeg.exe
vendor/win-x64/mpv.exe
```

Fontes recomendadas: [evermeet.cx/ffmpeg](https://evermeet.cx/ffmpeg/),
[gyan.dev/ffmpeg/builds](https://www.gyan.dev/ffmpeg/builds/),
[mpv.io/installation](https://mpv.io/installation/).

### Painel não abre no navegador

- Abra manualmente: `http://127.0.0.1:8765/`. Se a porta 8765 estiver
  ocupada, o sistema tenta as próximas até 8774.
- Verifique se algum antivírus está bloqueando processos Python
  comunicarem com `127.0.0.1`. Adicione exceção para o `python.exe` (Win)
  ou `python3` (Mac).

### Wizard aparece toda vez (não memoriza setup)

O setup é considerado completo quando o arquivo `.setup_complete` é
criado no diretório de dados. Se ele não persiste, há um problema de
permissão de escrita. Apague manualmente e refaça o setup:

```
# macOS
rm ~/Library/Application\ Support/VideoDelay/.setup_complete

# Windows (PowerShell)
Remove-Item "$env:APPDATA\VideoDelay\.setup_complete"
```

### Tela preta no playback

1. Confirme no painel que o **monitor selecionado** é o correto (em monitor
   único, deve ser "Monitor 0").
2. Confirme que a **placa está conectada e ativa** antes de iniciar o app.
3. Aguarde o tempo do delay configurado (mínimo 10s). Antes disso, o
   buffer ainda está enchendo e a tela fica preta intencionalmente.
4. Verifique o log:

   ```
   # macOS
   tail -f ~/Library/Application\ Support/VideoDelay/logs/videodelay.log

   # Windows (PowerShell)
   Get-Content "$env:APPDATA\VideoDelay\logs\videodelay.log" -Wait
   ```

### Placa de captura não aparece no wizard

- **macOS**: Configurações do Sistema → Privacidade e Segurança → Câmera
  → habilite o app que está rodando o Python (Terminal ou Python).
- **Windows**: abra Gerenciador de Dispositivos → Dispositivos de imagem.
  A placa deve aparecer ali. Se não aparecer, reinstale o driver do
  fabricante.

### Alto uso de CPU ou travamentos

No painel, seção **Captura**, ajuste:
- **preset**: `ultrafast` (padrão) reduz CPU em troca de tamanho de
  arquivo. `veryfast` é meio termo. Evite `slow` ou superior.
- **CRF**: 23 dá menos qualidade e menos CPU. 18 é o padrão (visualmente
  lossless).

### Atualizar para uma versão nova

Substitua a pasta inteira do projeto. As configurações (delay, placa,
monitor, wizard concluído) ficam em `~/Library/Application Support/VideoDelay/`
(Mac) ou `%APPDATA%\VideoDelay\` (Win) — fora da pasta do projeto, então
sobrevivem ao update.

Após substituir, rode `install.command`/`install.bat` novamente para
revalidar Python e baixar FFmpeg/MPV se necessário (idempotente — não
baixa de novo se já estiver tudo lá).

### Suporte remoto

Logs ficam em:

| Sistema | Caminho |
|---|---|
| macOS | `~/Library/Application Support/VideoDelay/logs/videodelay.log` |
| Windows | `%APPDATA%\VideoDelay\logs\videodelay.log` |

Arquivo limitado a 5 MB com rotação automática (mantém 3 backups). Para
suporte, envie o `videodelay.log` mais recente.

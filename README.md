# Tarrafa

[![License: PolyForm Noncommercial](https://img.shields.io/badge/License-PolyForm%20Noncommercial-blue.svg)](LICENSE)
[![Status: Experimental](https://img.shields.io/badge/status-experimental-orange.svg)](SECURITY.md)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![CI](https://github.com/Mosimann-adv/tarrafa_scraper/actions/workflows/ci.yml/badge.svg)](https://github.com/Mosimann-adv/tarrafa_scraper/actions/workflows/ci.yml)
[![CodeQL](https://github.com/Mosimann-adv/tarrafa_scraper/actions/workflows/codeql.yml/badge.svg)](https://github.com/Mosimann-adv/tarrafa_scraper/actions/workflows/codeql.yml)
[![Release](https://img.shields.io/github/v/release/Mosimann-adv/tarrafa_scraper?include_prereleases)](https://github.com/Mosimann-adv/tarrafa_scraper/releases)

![Joga a rede. Puxa a prova.](assets/hero.jpg)

> **Projeto experimental** — não é um produto acabado.  
> Sem SLA, sem suporte comercial, sem garantia de estabilidade ou de conformidade com qualquer caso concreto.  
> APIs e sites mudam; ferramentas quebram; **valide tudo** antes de usar em peça ou prova.  
> Detalhes de segurança e o que **não** publicar em issues: [SECURITY.md](SECURITY.md).

CLI multi-fonte **source-available** para **uso jurídico experimental**: inventário de material aberto e prova documental (páginas, feeds, prints, vídeo, Instagram, CNPJ, diário oficial/DJEN, Datajud e PDFs).
Serve para prototipar e apoiar coleta/organização de material em contexto legal — **não** é SaaS, **não** é serviço advocatício e **não** substitui análise humana.  
Independente de IDE, vault ou assistente de IA.

| | |
|--|--|
| CLI | `tarrafa` |
| Versão | 0.4.0 (experimental) |
| Python | ≥ 3.10 |
| Status | Pesquisa / protótipo — **não é produto** |
| Distribuição | Código-fonte público sob licença não comercial |
| Licença | [PolyForm Noncommercial 1.0.0](LICENSE) — créditos obrigatórios · **sem uso comercial** |

---

## Em 30 segundos

```bash
tarrafa page --url https://example.com --out ./out/page.json
```

```text
page: · ok · count=1 · -> out/page.json · text_len=112
```

O resultado é um envelope JSON com fonte, horário de coleta, método, conteúdo,
erros e notas. Capturas e vídeos também registram SHA-256. Veja um
[artefato de exemplo](examples/page_capture.example.json).

---

## Como usar

Fluxo típico de um caso:

1. **Instalar** (uma vez) — veja [Instalação](#instalação) abaixo.
2. **Checar o ambiente:** `tarrafa doctor`  
3. **(Opcional) criar pasta do caso:**
   ```bash
   tarrafa init ./meu-caso --name "Meu caso"
   ```
   Isso cria `tarrafa.toml` e as pastas `raw/`, `shots/`, `html/`, `logs/`, `meta/runs/`.  
   O workspace é **opcional**: você pode gravar em qualquer `--out` / `--out-dir`.  
4. **Capturar** com a tool certa (sempre diga **onde** salvar):

| Quero… | Comando base |
|--------|----------------|
| Texto + facts de uma URL | `tarrafa page --url URL --out ./raw/page.json` |
| Várias URLs de uma vez | `tarrafa page --urls-file urls.txt --out ./raw/pages/` |
| Print de tela (prova visual) | `tarrafa shot --url URL --out-dir ./shots --id DOC01` |
| Comentários de post no Instagram | `tarrafa ig --url POST_URL --out ./raw/ig.json --storage-state ./storage_state.json --headed` |
| CNPJ | `tarrafa cnpj --cnpj 00.000.000/0001-91 --out ./raw/cnpj.json` |
| Diário (advogado) | `tarrafa djen --oab 12345 --uf SP --out ./raw/djen.json` |
| Diário (parte / nome no teor) | `tarrafa djen --papel parte --texto "Nome Completo" --out ./raw/djen.json` |
| Processo por CNJ | `tarrafa datajud --cnj … --out ./raw/datajud.json` |
| Inteiro teor STJ (SCON) | `tarrafa stj --warmup --headed --save-storage ./stj.json` depois download com `--storage-state` |
| Texto de PDFs de autos | `tarrafa pdf-extract --dir ./pdfs --recursive --out ./raw/pdf.json` |
| Álbum / ficha para impressão | `tarrafa album …` / `tarrafa dossier …` |

5. **Ajuda de cada tool:** `tarrafa <tool> --help` · lista: `tarrafa list`  
6. **Flags globais** (antes do nome da tool):

```bash
tarrafa --workspace ./meu-caso -v page --url https://example.com --out raw/page.json
tarrafa --no-clobber page --url … --out raw/page.json   # recusa sobrescrever
tarrafa --force page --url … --out raw/page.json          # permite com no_clobber
```

Com workspace ativo, cada execução grava histórico em `meta/runs/<run_id>.json` (args sanitizados, artefatos + sha256, exit code).

Config em camadas: flags → env (`TARRAFA_TIMEOUT`, …) → `./tarrafa.toml` → `~/.tarrafa/config.toml`.

### O que cada um precisa configurar

| Recurso | Quem fornece |
|---------|----------------|
| Python 3.10+, deps, Chromium | Máquina de quem usa (`pip` + `playwright install`) |
| Sessão Instagram (`storage_state.json`) | **Login nativo de cada usuário** (nunca compartilhe o arquivo) |
| `DATAJUD_API_KEY` | Opcional (cota); se usar, no `.env` local |
| Token Playwright MCP | Opcional (Chrome real / extensão) |

**Não** digite senha no CLI. **Não** automatize Facebook OIDC. Saídas vão só para o path que você passar.

---

## Tools

| Comando | Função |
|---------|--------|
| `tarrafa init` | Cria workspace opcional (`tarrafa.toml` + pastas) |
| `tarrafa ig` | Comentários Instagram → JSON com permalink `/c/{id}/` |
| `tarrafa page` | Uma URL pública → texto + facts (meta / JSON-LD) |
| `tarrafa site` | Crawl concorrente same-host (max pages / depth) |
| `tarrafa feed` | RSS/Atom → envelope de entradas |
| `tarrafa shot` | Screenshot de alta qualidade (PNG + JSON) |
| `tarrafa video` | Meta de vídeo + frames (+ download opcional via yt-dlp) |
| `tarrafa album` | Compila shots/frames em HTML pronto para impressão |
| `tarrafa dossier` | Ficha HTML: avatar + achados + fontes + prints seletivos |
| `tarrafa cnpj` | Consulta CNPJ via API open CNPJá (sem API key) |
| `tarrafa djen` | Comunicações DJEN — advogado (`--oab`) ou parte (`--papel parte --texto`) |
| `tarrafa datajud` | Capa/movimentos Datajud por CNJ |
| `tarrafa stj` | Inteiro teor STJ/SCON (PDF; sessão headed/CDP se Cloudflare) |
| `tarrafa pdf-extract` | Texto + identity hints de PDFs |
| `tarrafa doctor` | Checa deps, Chromium, ffmpeg, yt-dlp, session e env |
| `tarrafa list` / `version` | Lista tools / versão |

---

## Instalação

### Uso

Instalação a partir do código:

```bash
git clone https://github.com/Mosimann-adv/tarrafa_scraper.git
cd tarrafa_scraper
python -m venv .venv

# Windows
.\.venv\Scripts\Activate.ps1

# macOS / Linux
# source .venv/bin/activate

python -m pip install .
python -m playwright install chromium
tarrafa doctor
```

Instalação direta da release:

```bash
python -m pip install \
  https://github.com/Mosimann-adv/tarrafa_scraper/releases/download/v0.4.0/tarrafa_scraper-0.4.0-py3-none-any.whl
python -m playwright install chromium
tarrafa doctor
```

Extras opcionais:

```bash
python -m pip install ".[av]"     # yt-dlp (download de vídeo)
python -m pip install ".[site]"   # scrapy opcional; site usa httpx assíncrono por padrão
# ffmpeg no PATH → frames a partir do arquivo baixado
```

### Desenvolvimento

```bash
python -m pip install -e ".[dev]"
python -m playwright install chromium
ruff check src tests
pytest -q -m "not integration"
pytest -q -m integration  # rede e Chromium
```

---

## Exemplos

### Página

```bash
tarrafa page --url https://example.com --out ./out/page.json

# batch (um URL por linha; # comentários ok)
tarrafa page --urls-file ./urls.txt --out ./out/pages/ --mode http
```

Além do corpo do artigo, colhe **meta/OG**, **JSON-LD** e contadores embutidos (`structured_facts`, `text_main` = corpo puro).
No modo padrão `auto`, tenta HTTP primeiro e abre o navegador no máximo uma vez
quando detecta página dinâmica ou captura insuficiente. Se o navegador produzir
um resultado pior, a captura HTTP é preservada.

### Screenshot + álbum

```bash
# recorte do conteúdo principal
tarrafa shot --url https://example.com --out-dir ./out/shots --id EX01 --clip main --dpr 2

# batch
tarrafa shot --urls-file ./urls.txt --out-dir ./out/shots --clip main --dpr 1

# página inteira
tarrafa shot --url https://example.com --out-dir ./out/shots --id EX01b --clip page --full-page

# seletor CSS
tarrafa shot --url https://example.com --out-dir ./out/shots --id EX01c --selector "article"

tarrafa album --dir ./out/shots --out ./out/shots/album.html \
  --title "Álbum de capturas" \
  --kicker "Inventário visual" \
  --meta "Assunto: …" \
  --meta "Data: …"
```

HTML no estilo inventário (folha A4, botão Imprimir/PDF).  
**Embed por padrão** (base64) → um único `.html` portátil. Relativo: `--no-embed`.

### Ficha / dossiê

Renderiza overview a partir de fatos e arquivos **já capturados** (não busca na web).

```bash
tarrafa dossier \
  --title "Nome Completo" \
  --subtitle "Âncora · cidade" \
  --out ./perfil/ficha.html \
  --avatar ./perfil/foto.png \
  --meta "Nome: …" --meta "Cidade: …" \
  --fact "Achado factual (fonte citada)" \
  --source "Fonte | https://… | nota" \
  --timeline "2022 | Vínculo em …" \
  --shot "print1=./shots/print.png::Legenda" \
  --gap "O que não foi validado" \
  --chip "âncora curta"
```

- **`--fact` / `--source` / `--timeline`**: conteúdo e inventário de fontes; prints são opcionais e seletivos.
- **`--manifest dossier.json`**: seções ricas (`sections[]`, cards, tabelas).

### CNPJ / DJEN / Datajud / PDF

```bash
tarrafa cnpj --cnpj 00.000.000/0001-91 --out ./out/cnpj.json

# Advogado: diário por OAB + UF
tarrafa djen --oab 12345 --uf SP --max-items 100 --out ./out/djen.json

# Parte: busca no teor (nome e/ou handle)
tarrafa djen --papel parte --texto "Nome Completo" --max-items 50 --out ./out/djen_parte.json

# Parte + Datajud em cadeia (CNJs encontrados)
tarrafa djen --papel parte --texto "Nome Completo" --follow-datajud \
  --datajud-out ./out/datajud.json --max-cnj 15 --out ./out/djen.json

tarrafa datajud --cnj 0000000-00.0000.0.00.0000 --out ./out/datajud.json
# opcional: --tribunal trf4 | env DATAJUD_API_KEY

# STJ inteiro teor (SCON) — 1) aquecer sessão  2) baixar
tarrafa stj --warmup --headed --save-storage ./stj_storage.json
tarrafa stj --num-registro 201600461292 --dt-publicacao 23/08/2019 \
  --storage-state ./stj_storage.json --out-dir ./out/stj_pdfs --out ./out/stj.json --extract
# lote: linhas "num|dd/mm/aaaa" ou URL GetInteiroTeor
tarrafa stj --urls-file ./seeds_stj.txt --storage-state ./stj_storage.json \
  --out-dir ./out/stj_pdfs --out ./out/stj.json

tarrafa pdf-extract --dir ./out/pdfs --recursive --out ./out/pdf_extract.json
```

- **cnpj:** open CNPJá sem API key; não busca por nome de sócio.
- **djen advogado:** amostra + pós-filtro OAB.
- **djen parte:** `--texto` no teor; `identity_hints` no summary; não fundir homônimos só por nome curto.
- **datajud:** índice típico **sem** partes — use CNJs já conhecidos.
- **stj:** SCON costuma exigir desafio Cloudflare; não contorna captcha — use `--warmup --headed` ou `--cdp`. Exit **5** = challenge.
- **pdf-extract:** texto embutido (pypdf); PDF só-imagem precisa OCR externo.
- **Perfil de pessoa (orquestração):** `docs/PROFILE_PIPELINE.md` — djen parte, autos, IG shots, homônimo/CPF, V1 HTML vs anexo judicial.

### Vídeo

```bash
tarrafa video --url https://example.com/video --out-dir ./out/vid --id VID01 --frames 5
tarrafa video --url "URL" --out-dir ./out/vid --id VID01 --download --frames 5
tarrafa album --dir ./out/vid --out ./out/vid/album.html --title "Frames de vídeo"
```

### Site / feed / Instagram

```bash
tarrafa site --url https://example.com --out ./out/site.json --max-pages 15 --max-depth 2
tarrafa feed --url https://example.com/feed.xml --out ./out/feed.json --max-entries 20

# IG: login nativo uma vez (nunca Facebook OIDC / senha automatizada)
tarrafa ig --url https://www.instagram.com/accounts/login/ --headed --max-comments 0 \
  --save-storage ./storage_state.json --out ./_login_dummy.json
tarrafa ig --url https://www.instagram.com/p/SHORTCODE/ --out ./comments.json \
  --storage-state ./storage_state.json --expand-replies --headed
```

O crawl reutiliza uma sessão HTTP assíncrona com concorrência conservadora,
retries transitórios e processamento em ordem BFS.

---

## Envelope comum

Campos: `tool`, `version`, `collected_at`, `source`, `meta`, `count`, `items[]`, `errors[]`, `notes[]`.

Shot/video gravam mídia em `--out-dir` e JSON com `sha256`.

---

## Agentes de IA

Contrato em **`AGENTS.md`**: preferir o CLI; não digitar senha; saída no diretório que o usuário indicar; material-only (captura, sem classificar).

---

## Estrutura

```
tarrafa_scraper/
  src/tarrafa/
    cli.py
    core/           # envelope, writers, http, extract, crawl, media, doctor
    templates/      # HTML album / dossier
    tools/          # ig, page, site, feed, shot, video, album, …
  tests/
  docs/
```

---

## Config e segurança

- `storage_state.json` e `.env` estão no `.gitignore` — não commitar.
- Env carregado no startup (sem sobrescrever variáveis já no processo):
  1. `~/.tarrafa/.env` (user-global)
  2. `<repo>/.env` (projeto)
- Token opcional da extensão Playwright MCP:

```env
PLAYWRIGHT_MCP_EXTENSION_TOKEN=seu_token_aqui
```

Template: `.env.example`. Conferir com `tarrafa doctor` (presença mascarada).

Uso lícito e prova apenas; respeitar ToS e lei local. O Tarrafa **não** presta serviço advocatício nem substitui análise jurídica humana.

Ver também **[SECURITY.md](SECURITY.md)** (o que não vazar em issues; tokens; relatório de vulnerabilidade).

---

## Licença

Distribuído sob **[PolyForm Noncommercial License 1.0.0](LICENSE)**.

Como a licença restringe uso comercial, o Tarrafa é **source-available**, não
open source no sentido OSI. A expressão SPDX do pacote é
`PolyForm-Noncommercial-1.0.0`.

Em resumo (não substitui o texto integral):

| | |
|--|--|
| **Pode** | Usar, estudar, modificar e redistribuir para fins **não comerciais**, com os avisos de licença |
| **Deve** | Manter os **créditos** / `Required Notice` e a licença junto com as cópias |
| **Não pode** | Uso **comercial** (incluindo exploração paga do software sem autorização à parte) |
| **Garantia** | Nenhuma — software “as is”, experimental |

Uso em atividade econômica / escritório como produto ou serviço costuma ser **comercial** sob esta licença. Para licença comercial ou autorização específica, fale com o mantenedor.

Isto **não** transforma o Tarrafa em produto suportado: mesmo com permissão, o código permanece experimental.

> Required Notice: Copyright Mosimann Advocacia / Tarrafa contributors  
> Project: Tarrafa — https://github.com/Mosimann-adv/tarrafa_scraper

---

## Apoie o projeto

Se o Tarrafa for útil no seu fluxo (estudo, pesquisa, prototipagem não comercial), uma doação voluntária via **Pix** ajuda a manter o projeto.

| | |
|--|--|
| Chave Pix | `mosimannadv@gmail.com` |
| Tipo | E-mail |

![QR Code Pix — mosimannadv@gmail.com](assets/pix-qr.png)

Doação voluntária; **sem** contraprestação de serviço advocatício.

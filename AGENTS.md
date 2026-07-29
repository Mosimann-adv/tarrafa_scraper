# Agent instructions — Tarrafa

Standalone multi-tool CLI. No dependency on any specific AI product, IDE, or case vault.

**License:** PolyForm Noncommercial 1.0.0 (`LICENSE`) — attribution required; no commercial use without separate permission.

## Idioma do projeto

- Adote **português do Brasil (pt-BR)** em comunicação, documentação, mensagens da CLI,
  changelog, issues, pull requests e mensagens de commit.
- Preserve em inglês identificadores de código, nomes de APIs, flags, formatos e termos
  técnicos consolidados quando a tradução prejudicar compatibilidade ou clareza.
- Não traduza retroativamente grandes trechos sem relação com a tarefa; aplique a regra
  a conteúdo novo ou alterado.

## Platform (v0.4+)

| Pedido | Comando / regra |
|--------|-----------------|
| Novo caso / pasta | `tarrafa init DIR --name "…"` → `tarrafa.toml` + raw/shots/html/logs/meta |
| Flags globais | antes da tool: `-v` `--quiet` `--force` `--no-clobber` `--timeout` `--out-dir` `--workspace` `--json-logs` |
| Workspace | **opcional**; tools aceitam `--out` solto. Com workspace, runs em `meta/runs/*.json` |
| Batch URLs | `page` / `shot` com `--urls-file` |
| Config | flags → env `TARRAFA_*` → `./tarrafa.toml` → `~/.tarrafa/config.toml` |

## When to use

| Pedido | Comando |
|--------|---------|
| Comentários IG + permalink `/c/` | `tarrafa ig` |
| Descobrir URLs candidatas na web | `tarrafa search` |
| Uma página pública (texto/links/facts) | `tarrafa page` |
| Crawl shallow de site | `tarrafa site` |
| RSS/Atom | `tarrafa feed` |
| Print de tela de alta qualidade | `tarrafa shot` |
| Vídeo: meta + frames (+ download) | `tarrafa video` |
| HTML impressão a partir de shots/frames | `tarrafa album` |
| Ficha HTML perfil (avatar + achados + fontes + prints seletivos) | `tarrafa dossier` |
| CNPJ (API open CNPJá) — todo perfil | `tarrafa cnpj` |
| DJEN comunicações — advogado (`--oab`) ou parte (priorize `--cpf`) | `tarrafa djen` |
| Datajud capa/movimentos (CNJ) — após DJEN / CNJs conhecidos | `tarrafa datajud` |
| Inteiro teor STJ (SCON PDF; Cloudflare) | `tarrafa stj` |
| Texto + identity hints de PDFs (autos) | `tarrafa pdf-extract` |
| Triagem chargeback pedido e-commerce (JSON + HTML embutido) | `tarrafa order-risk` |
| Checar ambiente | `tarrafa doctor` |
| Ensinar a Tarrafa a outra IA (fora deste repo) | `tarrafa skills install` |

## Paths

Prefer the installed console script after `pip install -e .`:

```text
tarrafa                  # on PATH (venv ativado)
~/.tarrafa/.env          # user-global env (preferido)
<repo>/.env              # projeto (gitignored)
.env.example             # template commitável
```

Windows (venv local), se o script ainda não estiver no PATH:

```text
.\.venv\Scripts\tarrafa.exe
```

## Commands

```bash
tarrafa list
tarrafa doctor

tarrafa search --query '"Nome Completo" cidade' --max-results 30 \
  --urls-out "OUT_DIR/urls.txt" --out "OUT_DIR/search.json"
tarrafa page --url "URL" --out "OUT.json"
tarrafa shot --url "URL" --out-dir "OUT_DIR" --id SHOT01 --full-page --dpr 2
tarrafa album --dir "OUT_DIR" --out "OUT_DIR/album.html" --title "…" --kicker "Inventário visual"

# STJ inteiro teor (SCON) — Cloudflare/CSID: aquecer sessão com headed
tarrafa stj --warmup --headed --save-storage ./stj_storage.json
tarrafa stj --num-registro 201600461292 --dt-publicacao 23/08/2019 \
  --storage-state ./stj_storage.json --out-dir ./stj_pdfs --out ./stj.json --extract
# ou Chrome real: chrome --remote-debugging-port=9222
tarrafa stj --cdp http://127.0.0.1:9222 --urls-file seeds.txt --out-dir ./stj_pdfs --out stj.json

tarrafa dossier \
  --title "Nome" --out "OUT_DIR/perfil.html" \
  --avatar "OUT_DIR/foto.png" \
  --meta "Campo: valor" \
  --fact "Achado com fonte citada" \
  --source "Fonte | https://… | nota" \
  --shot "print1=OUT_DIR/print.png::Legenda" \
  --gap "Lacuna honestamente registrada"

tarrafa cnpj --cnpj "00.000.000/0001-91" --out "OUT_DIR/cnpj.json"
tarrafa djen --oab 12345 --uf SP --max-items 100 --out "OUT_DIR/djen.json"
tarrafa djen --papel parte --cpf "<CPF>" --max-items 50 --out "OUT_DIR/djen_cpf.json"
tarrafa djen --papel parte --nome "Nome Completo" --max-items 50 --out "OUT_DIR/djen_parte.json"
tarrafa djen --papel parte --texto "handle" --follow-datajud \
  --datajud-out "OUT_DIR/datajud.json" --out "OUT_DIR/djen.json"
tarrafa datajud --cnj "0000000-00.0000.0.00.0000" --out "OUT_DIR/datajud.json"
tarrafa pdf-extract --dir "OUT_DIR/pdfs" --recursive --out "OUT_DIR/pdf_extract.json"

# Triagem chargeback (comprador + loja) — HTML com imagens em data URI
tarrafa order-risk \
  --store-url "https://loja.example" \
  --name "Nome Comprador" --cpf "000.000.000-00" \
  --cep "00000-000" --city "Cidade" --state UF \
  --street "Rua Exemplo" --number "100" \
  --phone "(00) 90000-0000" --email "user@example.com" \
  --out-dir "OUT_DIR" --html --shot-maps

tarrafa video --url "URL" --out-dir "OUT_DIR" --id VID01 --frames 5
# optional download: --download  (yt-dlp)

tarrafa ig --url "POST_URL" --out "OUT.json" \
  --storage-state "./storage_state.json" --expand-replies --headed
```

## Browser / sessão (canônico = CLI)

A ferramenta canônica é o **CLI `tarrafa`** (Playwright embutido). Não usar Playwright MCP para coletas de rotina.

| Prioridade | Como | Quando |
|------------|------|--------|
| **1 · CLI** | `tarrafa ig|shot|page|stj …` + `storage_state.json` | Padrão (IG, prints, STJ, etc.) |
| **2 · CLI headed / CDP** | `--headed`, `stj --cdp`, login nativo + `--save-storage` | Login, Cloudflare, storage expirado |
| **3 · MCP extension** | `@playwright/mcp --extension` (opcional) | Só se a extensão **já estiver conectada**; inspeção pontual. **Não** scrape em massa |

- Smoke IG rápido: `tarrafa ig --url URL --out OUT.json --storage-state ./storage_state.json --max-comments 15`
- Coleta profunda: `--expand-replies` (pode demorar; sempre `--max-comments` se for teste)
- Gravar sempre no path do caso (`--out` / `--out-dir`). Pasta `casos/` é gitignored.

## Local env

```text
~/.tarrafa/.env     # preferido (user-global)
<repo>/.env         # projeto (gitignored)
.env.example        # template
```

- `PLAYWRIGHT_MCP_EXTENSION_TOKEN` — opcional; só para MCP extension no host (ex.: Grok). O CLI **não depende** dele para coletar.
- `BRAVE_SEARCH_API_KEY` — provedor oficial opcional para `tarrafa search`.
- `SEARXNG_URL` — alternativa opcional; a instância precisa habilitar saída JSON.
- O CLI chama `load_tarrafa_env()` no startup; **não sobrescreve** env já definido no processo.
- `tarrafa doctor` mostra token (mascarado) e `storage_state.json` se presentes.
- **Nunca** commitar `.env`, token em README, ou hardcode em código.
- Sessão IG logada no CLI: `storage_state.json` (login nativo headed + `--save-storage`).

## Hard rules

1. Prefer **CLI** over Playwright MCP, browser eval, ou scrapers reinventados. MCP extension **não** substitui `tarrafa ig` / `shot` / `stj`.
2. Never type passwords; never automate Facebook OIDC / password-reset.
3. Write outputs into the **output path** the user names.
4. Do not commit `storage_state.json` or `.env`.
5. Report counts, paths, errors, exit codes.
6. Classification / case PDF generation stay **out of this repo**, except print-ready HTML from `album` / `dossier`.
7. Material-only: capture evidence, do not classify ofensas.
8. `dossier` only **renders** provided avatar/meta/facts/sources/shots — no web search, no biography invention. Prefer multi-source overview e prints seletivos; nunca embutir login wall.
9. `cnpj` is for **any profile** (needs CNPJ number).
10. `djen`: **advogado** → `--oab`+`--uf` (pós-filtro); **parte** → havendo CPF,
    `--papel parte --cpf` tem prioridade e conferência exata local. Sem CPF, usar
    `--nome`/`--texto` (`identity_hints` no summary). Optional `--follow-datajud`.
    Do **not** fuse processes by short name alone (homônimo).
11. `datajud`: only with known CNJs (from DJEN or other sources); index typically has **no** party names.
12. `pdf-extract`: material-only identity/contact/CNJ hints from court PDFs; validate before citing.
13. **Perfil / influencer:** ver `docs/PROFILE_PIPELINE.md` (IG shots, homônimo/CPF, djen parte, V1 HTML vs V2 anexo).
14. **IG prints e comentários:** `tarrafa shot` / `tarrafa ig` no path do caso. Não depender de MCP para gravar PNG/JSON. Never embed login-wall shots in `dossier`.
15. **CPF vs CNPJ mask:** CNPJá `***ABCDEF**` ≈ CPF digits 4–9. Do **not** attach a company QSA to the person if the mask does not match the CPF from court PDFs.
16. Judicial annex PDF (Times, no internal paths) is **orchestration**, not a CLI tool — keep case narrative out of this repo.
17. `search` só descobre candidatos; não confirma identidade. IA pode sugerir consultas e
    prioridades, inclusive por `--queries-file`, mas execução, deduplicação, proveniência
    e captura devem permanecer no CLI. Consultas com CPF/e-mail/telefone são bloqueadas
    sem `--allow-sensitive-query`.
## Exit codes (common)

| Code | Meaning |
|------|---------|
| 0 | OK |
| 1 | Execução parcial: artefatos gravados, mas uma ou mais coletas falharam |
| 2 | Bad args / missing dep / unknown tool |
| 3–5 | IG-specific (nav / auth / login wall) |
| 6 | Zero items |

## Skill para outros hosts de IA

Dentro deste repo, este `AGENTS.md` é o contrato. Fora dele, use `tarrafa skills install`:
o template vive em `src/tarrafa/skills/tarrafa.md.tmpl` (versionado junto com o código) e é
renderizado na instalação com o caminho real do executável, porque cada máquina tem um venv
diferente. Ao mudar flags ou exit codes de uma tool, **atualize o template no mesmo commit** —
ele é a única cópia dessas regras que roda fora daqui.

## Adding a tool

See `docs/ADDING_TOOLS.md`.

## Profile pipeline (learned)

See **`docs/PROFILE_PIPELINE.md`**: order of collection, Instagram capture pitfalls, party DJEN, pdf-extract, dual V1/V2 deliverables, homonym discipline.

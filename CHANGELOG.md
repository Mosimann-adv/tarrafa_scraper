# Changelog

## Unreleased

### Added
- **`tarrafa order-risk`** — triagem de risco de chargeback em pedido e-commerce:
  CPF/CEP/telefone, DJEN+Datajud por CPF, loja (page + CNPJ + RDAP), opcional Maps/IG;
  envelope JSON + HTML print-ready com **imagens embutidas (data URI)**.
- **`tarrafa stj`** — download de inteiro teor do STJ/SCON (PDF) com sessão browser:
  `--warmup --headed --save-storage`, `--storage-state`, `--cdp`, lote via `--urls-file`,
  opcional `--extract` (pdf-extract). Exit **5** em desafio Cloudflare/CSID.
- **`tarrafa.core.challenge`** — heurística compartilhada para páginas WAF/challenge.
- `browser_util.chromium_page` — suporte a `accept_downloads`, `cdp_url` e yield do `context`.

### Changed
- `site` agora reutiliza um cliente HTTP assíncrono com pool, concorrência conservadora,
  retries transitórios e ordem BFS determinística.
- `page --mode auto` registra o motivo do fallback para Playwright, limita a uma tentativa
  por URL e preserva a captura HTTP quando o navegador não melhora o resultado.
- `page` marca `meta.challenge` e registra erro quando a resposta parece Cloudflare/CSID.

## 0.4.0 — 2026-07-25

Platform foundation (agnostic of any single use case).

### Added
- **`tarrafa init`** — optional workspace with `tarrafa.toml` + `raw/`, `shots/`, `html/`, `logs/`, `meta/runs/`
- **Config layers** — flags → env (`TARRAFA_*`) → `./tarrafa.toml` → `~/.tarrafa/config.toml`
- **Global CLI flags** — `-v` / `--quiet`, `--force`, `--no-clobber`, `--timeout`, `--out-dir`, `--workspace`, `--json-logs`
- **Run manifest** — when a workspace is active, each tool invocation writes `meta/runs/<run_id>.json` (argv sanitized, artifacts + sha256, exit code, duration)
- **`page` / `shot --urls-file`** — batch capture from a text file (one URL per line)
- **Doctor** — actionable fix hints per failed check; TOML + workspace probes
- **CI** — testes determinísticos + Ruff no push/PR; integrações com rede/Chromium em workflow próprio
- **Publicação** — wheel/sdist verificados, metadata PEP 639, URLs de projeto e versão única
- **Qualidade** — Ruff, CodeQL, Dependabot e matriz Windows/Linux (Python 3.10/3.14)
- **Comunidade** — CONTRIBUTING, Code of Conduct e formulários sem dados sensíveis

### Changed
- Tools still accept free `--out` / `--out-dir` (workspace is convenience, not required)
- Stdout summaries slightly normalized via shared helper
- Testes determinísticos rodam no CI principal; rede/Chromium ficaram em workflow próprio
- Saída do CLI tolera consoles Windows legados e o `doctor` distingue opcionais ausentes
- `doctor` procura `storage_state.json` no diretório atual também quando instalado por wheel

### Security
- Manifests agora mascaram `--api-key`, credenciais, sessões e opções equivalentes
- Histórico público estabelecido a partir de uma baseline sanitizada

### Notes
- `no_clobber` is opt-in (`--no-clobber` or `defaults.no_clobber` in TOML)
- Python 3.10 needs `tomli` for `tarrafa.toml` (declared dependency marker)

## 0.3.2

Prior multi-tool release (ig, page, site, feed, shot, video, album, dossier, cnpj, djen, datajud, pdf-extract, doctor).

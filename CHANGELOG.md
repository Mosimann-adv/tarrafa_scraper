# Changelog

## 0.4.0 — 2026-07-25

Platform foundation (agnostic of any single use case).

### Added
- **`tarrafa init`** — optional workspace with `tarrafa.toml` + `raw/`, `shots/`, `html/`, `logs/`, `meta/runs/`
- **Config layers** — flags → env (`TARRAFA_*`) → `./tarrafa.toml` → `~/.tarrafa/config.toml`
- **Global CLI flags** — `-v` / `--quiet`, `--force`, `--no-clobber`, `--timeout`, `--out-dir`, `--workspace`, `--json-logs`
- **Run manifest** — when a workspace is active, each tool invocation writes `meta/runs/<run_id>.json` (argv sanitized, artifacts + sha256, exit code, duration)
- **`page` / `shot --urls-file`** — batch capture from a text file (one URL per line)
- **Doctor** — actionable fix hints per failed check; TOML + workspace probes
- **CI** — GitHub Actions (pytest + Chromium) on push/PR to `main`

### Changed
- Tools still accept free `--out` / `--out-dir` (workspace is convenience, not required)
- Stdout summaries slightly normalized via shared helper

### Notes
- `no_clobber` is opt-in (`--no-clobber` or `defaults.no_clobber` in TOML)
- Python 3.10 needs `tomli` for `tarrafa.toml` (declared dependency marker)

## 0.3.2

Prior multi-tool release (ig, page, site, feed, shot, video, album, dossier, cnpj, djen, datajud, pdf-extract, doctor).

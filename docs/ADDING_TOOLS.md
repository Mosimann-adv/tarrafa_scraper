# Adding a new scraper tool

1. Create `src/tarrafa/tools/<name>/` with `scraper.py` exposing `main(argv: list[str] | None) -> int`.
2. Prefer shared core:
   - `tarrafa.core.envelope.build_envelope`
   - `tarrafa.core.writers.write_json` / `utc_now_iso`
   - `tarrafa.core.http.fetch_url` / `tarrafa.core.extract.extract_article`
   - `tarrafa.core.crawl.crawl` for multi-page
   - `tarrafa.core.browser_util` / `tarrafa.core.media` for screenshots & video
   - `tarrafa.templates.album_html` for print HTML
3. Register in `src/tarrafa/cli.py` (`TOOLS` + dispatch map).
3.1. Gravou arquivo **sem** passar por `write_json` (HTML, PDF, PNG, texto)? Chame
   `tarrafa.core.run.register_artifact(path, kind=...)` logo depois. O manifesto de
   execução é o que `tarrafa verify` confere depois; artefato não registrado fica fora
   da conferência de integridade.
4. Document flags in `README.md` and `AGENTS.md`.
5. Add a smoke test under `tests/`.
6. Keep case-specific classifiers **out** of this repo. Print-ready HTML via `album` / `dossier` / `order-risk` is OK (render only; no OSINT narrative; sem dados de caso real embutidos no código).
7. HTML com prints: **sempre embutir** imagens via `file_to_data_uri` (data URI), não depender de path relativo.

## Optional extras

- `pip install -e ".[site]"` → Scrapy (site engine is still BFS httpx by default)
- `pip install -e ".[av]"` → yt-dlp for `tarrafa video --download`
- `ffmpeg` on PATH → frames from downloaded media

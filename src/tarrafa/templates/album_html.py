# -*- coding: utf-8 -*-
"""Print-ready album HTML (estilo inventário factual — folha A4)."""
from __future__ import annotations

import html
from typing import Any


def _e(s: Any) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def render_album(
    *,
    title: str,
    kicker: str,
    meta_lines: list[str],
    items: list[dict[str, Any]],
    footer: str | None = None,
) -> str:
    """
    items: each may have:
      id, caption, url, collected_at, image (relative path or data), kind (shot|frame|other),
      notes (list[str])
    """
    toc = []
    sections = []
    for i, it in enumerate(items, 1):
        iid = it.get("id") or f"item_{i:02d}"
        sid = f"s{i}"
        toc.append(f'          <li><a href="#{sid}">{_e(iid)} — {_e((it.get("caption") or "")[:60])}</a></li>')
        # Prefer pre-built data URI (embedded); else relative/path src
        img_src = it.get("image_src") or it.get("image") or it.get("path") or ""
        notes = it.get("notes") or []
        notes_html = ""
        if notes:
            notes_html = "<ul class=\"clean\">" + "".join(f"<li>{_e(n)}</li>" for n in notes) + "</ul>"
        cap = it.get("caption") or it.get("title") or ""
        url = it.get("url") or ""
        collected = it.get("collected_at") or ""
        kind = it.get("kind") or "shot"
        img_block = ""
        if img_src:
            # data: URIs must not be entity-escaped (breaks base64); paths are escaped
            if str(img_src).startswith("data:"):
                src_attr = img_src
            else:
                src_attr = _e(img_src)
            img_block = f'<div class="fig"><img src="{src_attr}" alt="{_e(iid)}" /></div>'
        url_line = f'<div class="plat">URL: <a href="{_e(url)}">{_e(url)}</a></div>' if url else ""
        col_line = f'<div class="plat">Coleta: {_e(collected)} · tipo: {_e(kind)}</div>' if collected or kind else ""
        sections.append(
            f"""
      <section id="{sid}">
        <h2>{i}. <span class="id-label">{_e(iid)}</span></h2>
        <p>{_e(cap)}</p>
        {img_block}
        <div class="quote">
          <div class="who">{_e(iid)} · {_e(kind)}</div>
          <div class="txt">{_e(cap)}</div>
          {url_line}
          {col_line}
        </div>
        {notes_html}
      </section>"""
        )

    meta_parts: list[str] = []
    for m in meta_lines:
        if ":" in m:
            k, v = m.split(":", 1)
            meta_parts.append(f"<strong>{_e(k.strip())}:</strong> {_e(v.strip())}")
        else:
            meta_parts.append(_e(m))
    meta_html = "<br />\n          ".join(meta_parts)

    footer = footer or "Inventário visual de capturas · material factual. Não constitui peça jurídica."

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_e(title)}</title>
  <style>
    :root {{
      --ink: #111;
      --muted: #444;
      --line: #ccc;
      --line-strong: #999;
      --paper: #fff;
    }}
    * {{ box-sizing: border-box; }}
    html {{
      font-size: 11.5pt;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    body {{
      margin: 0;
      color: var(--ink);
      background: #ececec;
      font-family: "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif;
      line-height: 1.5;
    }}
    .screen-bar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      padding: 10px 18mm;
      background: #1a1a1a;
      color: #eee;
      font-size: 0.85rem;
    }}
    .screen-bar button {{
      border: 1px solid #888;
      background: transparent;
      color: #fff;
      padding: 0.4rem 0.85rem;
      font: inherit;
      cursor: pointer;
    }}
    .sheet {{
      max-width: 210mm;
      margin: 20px auto;
      background: var(--paper);
      border: 1px solid #ddd;
      box-shadow: 0 8px 28px rgba(0,0,0,.08);
    }}
    .inner {{ padding: 20mm 18mm 18mm; }}
    header.doc {{
      border-bottom: 2px solid #111;
      padding-bottom: 1rem;
      margin-bottom: 1.25rem;
    }}
    .kicker {{
      font-size: 0.72rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
      margin: 0 0 0.5rem;
    }}
    h1 {{
      font-size: 1.35rem;
      font-weight: 700;
      line-height: 1.25;
      margin: 0 0 0.75rem;
      letter-spacing: -0.01em;
    }}
    .meta {{
      font-size: 0.88rem;
      color: var(--muted);
      margin: 0;
    }}
    h2 {{
      font-size: 1.05rem;
      font-weight: 700;
      margin: 1.5rem 0 0.65rem;
      padding-bottom: 0.3rem;
      border-bottom: 1px solid var(--line-strong);
      page-break-after: avoid;
    }}
    p {{
      margin: 0 0 0.65rem;
      max-width: 68ch;
      text-align: justify;
      hyphens: auto;
    }}
    .id-label {{
      font-family: ui-monospace, Consolas, "Courier New", monospace;
      font-size: 0.85rem;
      font-weight: 650;
    }}
    .fig {{
      margin: 0.75rem 0 1rem;
      text-align: center;
      page-break-inside: avoid;
    }}
    .fig img {{
      max-width: 100%;
      height: auto;
      border: 1px solid var(--line);
      box-shadow: 0 1px 4px rgba(0,0,0,.06);
    }}
    .quote {{
      border-left: 3px solid #333;
      padding: 0.55rem 0.75rem;
      margin: 0 0 0.55rem;
      background: #f7f7f7;
      page-break-inside: avoid;
    }}
    .quote .who {{
      font-size: 0.8rem;
      color: var(--muted);
      margin-bottom: 0.25rem;
    }}
    .quote .txt {{ font-weight: 500; }}
    .quote .plat {{
      font-size: 0.75rem;
      color: #666;
      margin-top: 0.3rem;
      word-break: break-all;
    }}
    .quote .plat a {{ color: #333; }}
    ul.clean {{
      margin: 0.35rem 0 0.85rem;
      padding-left: 1.2rem;
      max-width: 68ch;
      font-size: 0.88rem;
    }}
    footer.doc {{
      margin-top: 1.5rem;
      padding-top: 0.6rem;
      border-top: 1px solid var(--line);
      font-size: 0.75rem;
      color: var(--muted);
    }}
    nav.toc {{
      background: #f5f5f5;
      border: 1px solid var(--line);
      padding: 0.75rem 1rem;
      margin-bottom: 1.25rem;
      page-break-inside: avoid;
    }}
    nav.toc .t {{
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin: 0 0 0.4rem;
      font-weight: 650;
    }}
    nav.toc ol {{
      margin: 0;
      padding-left: 1.2rem;
      columns: 2;
      font-size: 0.85rem;
    }}
    nav.toc a {{ color: #111; text-decoration: none; }}
    @page {{ size: A4; margin: 14mm 12mm 16mm; }}
    @media print {{
      body {{ background: #fff; }}
      .screen-bar {{ display: none !important; }}
      .sheet {{ margin: 0; border: 0; box-shadow: none; max-width: none; }}
      .inner {{ padding: 0; }}
      a {{ color: inherit; text-decoration: none; }}
      h2 {{ break-after: avoid; }}
      .fig, .quote {{ break-inside: avoid; }}
    }}
    @media screen and (max-width: 720px) {{
      .sheet {{ margin: 0; border: 0; box-shadow: none; }}
      .inner {{ padding: 1.2rem 1rem 2rem; }}
      nav.toc ol {{ columns: 1; }}
      p {{ text-align: left; }}
    }}
  </style>
</head>
<body>
  <div class="screen-bar">
    <span>{_e(kicker)}</span>
    <button type="button" onclick="window.print()">Imprimir / PDF</button>
  </div>

  <article class="sheet">
    <div class="inner">
      <header class="doc">
        <p class="kicker">{_e(kicker)}</p>
        <h1>{_e(title)}</h1>
        <p class="meta">
          {meta_html}
        </p>
      </header>

      <nav class="toc" aria-label="Sumário">
        <p class="t">Sumário</p>
        <ol>
{chr(10).join(toc)}
        </ol>
      </nav>

{chr(10).join(sections)}

      <footer class="doc">
        {_e(footer)}
      </footer>
    </div>
  </article>
</body>
</html>
"""

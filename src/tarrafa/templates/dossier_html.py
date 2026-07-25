# -*- coding: utf-8 -*-
"""
Ficha / dossiê de pessoa — HTML estilo perfil (referência Custódio).

Overview da pessoa: identificação, achados, fontes, seções temáticas,
prints só quando relevantes. Material factual — sem biografia inventada.
"""
from __future__ import annotations

import html
import re
from typing import Any


def _e(s: Any) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def _linkify_cell(value: str) -> str:
    """Escape text; turn bare http(s) URLs into anchors (whole-cell or inline)."""
    v = (value or "").strip()
    if not v:
        return ""
    if re.fullmatch(r"https?://\S+", v):
        return f'<a href="{_e(v)}" target="_blank" rel="noopener">{_e(v)}</a>'
    # mailto
    if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", v):
        return f'<a href="mailto:{_e(v)}">{_e(v)}</a>'
    # inline URLs
    parts: list[str] = []
    last = 0
    for m in re.finditer(r"https?://[^\s<>\"']+", v):
        parts.append(_e(v[last : m.start()]))
        url = m.group(0)
        parts.append(f'<a href="{_e(url)}" target="_blank" rel="noopener">{_e(url)}</a>')
        last = m.end()
    parts.append(_e(v[last:]))
    return "".join(parts)


def _render_table(rows: list[tuple[str, str]] | list[list[str]]) -> str:
    if not rows:
        return ""
    trs = []
    for row in rows:
        if isinstance(row, (list, tuple)) and len(row) >= 2:
            k, v = row[0], row[1]
        else:
            continue
        trs.append(f"<tr><th>{_e(k)}</th><td>{_linkify_cell(str(v))}</td></tr>")
    if not trs:
        return ""
    return f"<table>\n{''.join(trs)}\n</table>"


def _render_list(items: list[str]) -> str:
    if not items:
        return ""
    lis = "".join(f"<li>{_linkify_cell(str(it))}</li>" for it in items if it)
    return f'<ul>{lis}</ul>'


def _render_section_block(sec: dict[str, Any]) -> str:
    """
    Flexible thematic section (manifest).
    keys: id, title, prose, quote, items, rows, cards[{title, items, prose, badge}]
    """
    sid = sec.get("id") or "sec"
    title = sec.get("title") or sid
    parts: list[str] = [f'<section id="{_e(sid)}">', f"<h2>{_e(title)}</h2>"]

    if sec.get("prose"):
        parts.append(f"<p>{_linkify_cell(str(sec['prose']))}</p>")

    if sec.get("rows"):
        rows = []
        for r in sec["rows"]:
            if isinstance(r, dict):
                rows.append((r.get("k") or r.get("label") or "", r.get("v") or r.get("value") or ""))
            elif isinstance(r, (list, tuple)) and len(r) >= 2:
                rows.append((r[0], r[1]))
        parts.append(_render_table(rows))

    if sec.get("items"):
        parts.append(_render_list(list(sec["items"])))

    cards = sec.get("cards") or []
    if cards:
        card_html = []
        for c in cards:
            badge = c.get("badge") or ""
            badge_html = (
                f' <span class="badge{" warn" if c.get("warn") else ""}">{_e(badge)}</span>'
                if badge
                else ""
            )
            inner = [f'<h3>{_e(c.get("title") or "")}{badge_html}</h3>']
            if c.get("prose"):
                inner.append(f"<p>{_linkify_cell(str(c['prose']))}</p>")
            if c.get("items"):
                inner.append(_render_list(list(c["items"])))
            if c.get("muted"):
                inner.append(f'<p class="muted">{_linkify_cell(str(c["muted"]))}</p>')
            card_html.append(f'<div class="card">{"".join(inner)}</div>')
        parts.append(f'<div class="grid-2">{"".join(card_html)}</div>')

    if sec.get("quote"):
        parts.append(f'<div class="quote">{_linkify_cell(str(sec["quote"]))}</div>')

    # optional shot ids referenced later; inline image if provided
    if sec.get("image_src"):
        img = sec["image_src"]
        img_attr = img if str(img).startswith("data:") else _e(img)
        cap = _e(sec.get("image_caption") or "")
        contain = " contain" if sec.get("image_contain") else ""
        parts.append(
            f'<figure><div class="shot{contain}">'
            f'<img src="{img_attr}" alt="{_e(sec.get("image_alt") or title)}" />'
            f"</div>"
            f'{f"<figcaption>{cap}</figcaption>" if cap else ""}'
            f"</figure>"
        )

    parts.append("</section>")
    return "\n".join(parts)


def render_dossier(
    *,
    title: str,
    subtitle: str = "",
    kicker: str = "Dossiê · material público",
    avatar_src: str | None = None,
    chips: list[str] | None = None,
    meta_rows: list[tuple[str, str]] | None = None,
    facts: list[str] | None = None,
    stats: list[dict[str, str]] | None = None,
    sources: list[dict[str, str]] | None = None,
    sections: list[dict[str, Any]] | None = None,
    shots: list[dict[str, Any]] | None = None,
    timeline: list[dict[str, str]] | None = None,
    gaps: list[str] | None = None,
    notes: list[str] | None = None,
    quote: str = "",
    intro: str = "",
    footer: str | None = None,
    collected_at: str = "",
    method: str = "",
    screen_bar_label: str | None = None,
) -> str:
    """
    shots[]: id, caption, url, image_src, collected_at, kind, contain (bool)
    sources[]: label, url, note
    timeline[]: when, text
    sections[]: flexible thematic blocks (see _render_section_block)
    facts[]: bullets de **síntese** (poucos, com fonte)
    stats[]: {label, value} — faixa de KPIs no topo
    meta_rows: (label, value) identificação (enxuta)
    """
    chips = chips or []
    meta_rows = meta_rows or []
    facts = facts or []
    stats = stats or []
    sources = sources or []
    sections = sections or []
    shots = shots or []
    timeline = timeline or []
    gaps = gaps or []
    notes = notes or []

    # --- hero chips ---
    chips_html = ""
    if chips:
        chips_html = (
            '<div class="chips">'
            + "".join(f'<span class="chip">{_e(c)}</span>' for c in chips if c)
            + "</div>"
        )

    # --- TOC (jump links — sticky below hero) ---
    toc_links: list[tuple[str, str]] = []
    if facts or stats:
        toc_links.append(("#sintese", "Síntese"))
    if meta_rows or quote:
        toc_links.append(("#id", "Identificação"))
    for sec in sections:
        sid = sec.get("id") or "sec"
        st = sec.get("title") or sid
        # short labels for nav
        short = st.split("(")[0].split("—")[0].strip()
        if len(short) > 28:
            short = short[:26] + "…"
        toc_links.append((f"#{sid}", short))
    if timeline:
        toc_links.append(("#timeline", "Linha do tempo"))
    if sources:
        toc_links.append(("#fontes", "Fontes"))
    if shots:
        toc_links.append(("#capturas", "Capturas"))
    if gaps:
        toc_links.append(("#lacunas", "Limites"))

    toc_html = ""
    if toc_links:
        toc_html = (
            '<nav class="toc jump" aria-label="Ir para seção">'
            + "".join(
                f'<a class="toc-pill" href="{_e(href)}">{_e(label)}</a>'
                for href, label in toc_links
            )
            + "</nav>"
        )

    # --- stats strip ---
    stats_html = ""
    if stats:
        cells = []
        for st in stats:
            lab = st.get("label") or st.get("k") or ""
            val = st.get("value") or st.get("v") or ""
            if not lab and not val:
                continue
            cells.append(
                f'<div class="stat"><div class="stat-v">{_e(val)}</div>'
                f'<div class="stat-l">{_e(lab)}</div></div>'
            )
        if cells:
            stats_html = f'<div class="stats" role="group" aria-label="Indicadores">{"".join(cells)}</div>'

    # --- avatar ---
    avatar_block = ""
    if avatar_src:
        src_attr = avatar_src if str(avatar_src).startswith("data:") else _e(avatar_src)
        avatar_block = f"""
  <div class="avatar-wrap">
    <img src="{src_attr}" alt="Foto de identificação — {_e(title)}" />
  </div>"""
    else:
        avatar_block = '<div class="avatar-wrap avatar-empty" aria-hidden="true"></div>'

    # --- meta bar ---
    meta_bits = []
    if collected_at:
        meta_bits.append(f"<span><strong>Coletado em:</strong> {_e(collected_at)}</span>")
    if method:
        meta_bits.append(f"<span><strong>Método:</strong> {_e(method)}</span>")
    meta_bits.append("<span><strong>Regra:</strong> material-only · fontes públicas</span>")
    meta_bar = f'<div class="meta-bar">{"".join(meta_bits)}</div>'

    intro_html = f'<p class="muted">{_linkify_cell(intro)}</p>' if intro else (
        '<p class="muted">Perfil consolidado a partir de fontes abertas. '
        "Imagens embutidas (base64) quando disponíveis. "
        "Não inventa biografia nem classifica risco.</p>"
    )
    notes_html = ""
    if notes:
        notes_html = _render_list(notes)

    # --- identification (after síntese for scan path) ---
    id_section = ""
    if meta_rows:
        id_section = f"""
<section id="id">
  <h2>Identificação</h2>
  {_render_table(meta_rows)}
  {f'<div class="quote">{_linkify_cell(quote)}</div>' if quote else ''}
</section>"""
    elif quote:
        id_section = f"""
<section id="id">
  <h2>Identificação</h2>
  <div class="quote">{_linkify_cell(quote)}</div>
</section>"""

    # --- síntese (facts = short bullets, sweet spot) ---
    facts_section = ""
    if facts or stats_html:
        lead = (
            '<p class="muted lead">O essencial, com fonte. Detalhe nas seções abaixo; '
            "coleta bruta em raw/ do caso.</p>"
            if facts
            else ""
        )
        facts_section = f"""
<section id="sintese" class="sec-sintese">
  <h2>Síntese</h2>
  {stats_html}
  {lead}
  {_render_list(facts) if facts else ""}
</section>"""

    # --- custom sections ---
    sections_html = "\n".join(_render_section_block(s) for s in sections)

    # --- sources inventory ---
    sources_section = ""
    if sources:
        trs = []
        for s in sources:
            label = s.get("label") or s.get("name") or "Fonte"
            url = (s.get("url") or "").strip()
            note = (s.get("note") or "").strip()
            if url:
                cell = f'<a href="{_e(url)}" target="_blank" rel="noopener">{_e(url)}</a>'
            else:
                cell = "—"
            if note:
                cell += f'<br><span class="muted">{_e(note)}</span>'
            trs.append(f"<tr><th>{_e(label)}</th><td>{cell}</td></tr>")
        sources_section = f"""
<section id="fontes">
  <h2>Fontes abertas</h2>
  <p class="muted">Inventário compacto — URLs para conferência.</p>
  <table class="compact">
{"".join(trs)}
  </table>
</section>"""

    # --- shots (selective) ---
    shots_section = ""
    if shots:
        blocks = []
        for i, sh in enumerate(shots, 1):
            sid = sh.get("id") or f"S{i:02d}"
            cap = sh.get("caption") or sid
            url = (sh.get("url") or "").strip()
            col = (sh.get("collected_at") or "").strip()
            img = sh.get("image_src") or sh.get("image") or ""
            img_attr = img if (img and str(img).startswith("data:")) else (_e(img) if img else "")
            contain = " contain" if sh.get("contain") else ""
            img_block = (
                f'<div class="shot{contain}"><img src="{img_attr}" alt="{_e(cap)}" /></div>'
                if img_attr
                else '<p class="muted">Imagem ausente.</p>'
            )
            fig_parts = [_e(cap)]
            if url:
                fig_parts.append(
                    f'<a href="{_e(url)}" target="_blank" rel="noopener">{_e(url)}</a>'
                )
            if col:
                fig_parts.append(_e(f"coleta {col}"))
            figcap = " · ".join(fig_parts)
            blocks.append(
                f"""
  <h3><span class="id-label">{_e(sid)}</span> — {_e(cap)}</h3>
  <figure>
    {img_block}
    <figcaption>{figcap}</figcaption>
  </figure>"""
            )
        shots_section = f"""
<section id="capturas">
  <h2>Capturas</h2>
  <details class="fold">
    <summary>Ver {len(shots)} print(s) embutido(s) · opcional para leitura rápida</summary>
    <p class="muted">Somente páginas com conteúdo útil — sem login wall.</p>
{"".join(blocks)}
  </details>
</section>"""
    # --- timeline ---
    timeline_section = ""
    if timeline:
        items = []
        for t in timeline:
            when = t.get("when") or t.get("year") or ""
            text = t.get("text") or t.get("body") or ""
            items.append(
                f'<div class="item"><div class="year">{_e(when)}</div>{_linkify_cell(text)}</div>'
            )
        timeline_section = f"""
<section id="timeline">
  <h2>Linha do tempo</h2>
  <div class="timeline">
{"".join(items)}
  </div>
</section>"""

    # --- gaps ---
    gaps_section = ""
    if gaps:
        gaps_section = f"""
<section id="lacunas">
  <h2>Lacunas e limites</h2>
  <div class="note">
    {_render_list(gaps)}
  </div>
</section>"""
    else:
        gaps_section = """
<section id="lacunas">
  <h2>Lacunas e limites</h2>
  <p class="muted">Nenhuma lacuna registrada neste inventário.</p>
</section>"""

    footer = footer or (
        "Inventário material de fontes abertas · imagens embutidas (base64) quando presentes · "
        "não constitui análise conclusiva nem peça jurídica · gerado por tarrafa dossier"
    )
    bar_label = screen_bar_label or "Tarrafa dossier · perfil material"

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Perfil — {_e(title)}</title>
<style>
  :root {{
    --bg: #f4f1eb;
    --paper: #fffcf7;
    --ink: #1a1a18;
    --muted: #5c5a54;
    --line: #ddd6c8;
    --accent: #0f3d3e;
    --accent-soft: #e4efef;
    --chip: #f0ebe3;
    --warn: #7a4a12;
    --warn-bg: #f7efe3;
    --shadow: 0 12px 40px rgba(26, 26, 24, 0.08);
    --radius: 14px;
    --max: 920px;
  }}
  * {{ box-sizing: border-box; }}
  html {{ scroll-behavior: smooth; }}
  body {{
    margin: 0;
    font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
    color: var(--ink);
    background:
      radial-gradient(1200px 600px at 10% -10%, #e8efe9 0%, transparent 55%),
      radial-gradient(900px 500px at 100% 0%, #efe6d8 0%, transparent 50%),
      var(--bg);
    line-height: 1.55;
    font-size: 15.5px;
  }}
  a {{ color: var(--accent); text-underline-offset: 2px; }}
  a:hover {{ opacity: 0.85; }}
  .screen-bar {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    padding: 10px 18px;
    background: #1a2a2a;
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
    border-radius: 8px;
  }}
  .wrap {{ max-width: var(--max); margin: 0 auto; padding: 28px 18px 64px; }}
  header.hero {{
    background: var(--paper);
    border: 1px solid var(--line);
    border-radius: calc(var(--radius) + 4px);
    box-shadow: var(--shadow);
    padding: 28px 28px 24px;
    display: grid;
    grid-template-columns: 148px 1fr;
    gap: 24px;
    align-items: center;
  }}
  .avatar-wrap {{
    width: 148px; height: 148px;
    border-radius: 50%;
    overflow: hidden;
    border: 3px solid var(--accent);
    box-shadow: 0 8px 24px rgba(15,61,62,.18);
    background: #ddd;
    flex-shrink: 0;
  }}
  .avatar-wrap.avatar-empty {{
    background: linear-gradient(145deg, #d8d2c6, #ebe6dc);
  }}
  .avatar-wrap img {{
    width: 100%; height: 100%;
    object-fit: cover;
    display: block;
  }}
  .kicker {{
    font-size: 11px;
    letter-spacing: .14em;
    text-transform: uppercase;
    color: var(--muted);
    font-weight: 600;
    margin: 0 0 6px;
  }}
  h1 {{
    margin: 0 0 8px;
    font-size: clamp(1.55rem, 2.5vw, 2rem);
    line-height: 1.15;
    letter-spacing: -0.02em;
    color: var(--accent);
  }}
  .subtitle {{ margin: 0 0 14px; color: var(--muted); font-size: 0.98rem; }}
  .chips {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  .chip {{
    background: var(--chip);
    border: 1px solid var(--line);
    border-radius: 999px;
    padding: 5px 12px;
    font-size: 12.5px;
    color: var(--ink);
    white-space: nowrap;
  }}
  nav.toc.jump {{
    position: sticky;
    top: 0;
    z-index: 20;
    margin: 14px 0 0;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    padding: 10px 12px;
    background: rgba(255, 252, 247, 0.94);
    border: 1px solid var(--line);
    border-radius: 12px;
    box-shadow: 0 4px 16px rgba(26, 26, 24, 0.06);
    backdrop-filter: blur(8px);
  }}
  nav.toc .toc-pill {{
    text-decoration: none;
    color: var(--accent);
    font-size: 12.5px;
    font-weight: 600;
    padding: 5px 11px;
    border-radius: 999px;
    border: 1px solid var(--line);
    background: var(--chip);
  }}
  nav.toc .toc-pill:hover {{
    background: var(--accent-soft);
    border-color: #b7c9c9;
  }}
  section {{
    margin-top: 18px;
    background: var(--paper);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    padding: 18px 20px 16px;
  }}
  section.sec-sintese {{
    border-color: #c5d6d6;
    background: linear-gradient(180deg, #f7fbfb 0%, var(--paper) 48%);
  }}
  section.sec-meta {{
    padding: 14px 18px;
  }}
  .stats {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: 10px;
    margin: 0 0 14px;
  }}
  .stat {{
    background: #faf7f1;
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: 10px 12px;
    text-align: center;
  }}
  .stat-v {{
    font-size: 1.15rem;
    font-weight: 700;
    color: var(--accent);
    letter-spacing: -0.02em;
    line-height: 1.2;
  }}
  .stat-l {{
    margin-top: 4px;
    font-size: 11.5px;
    color: var(--muted);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }}
  p.lead {{ margin: 0 0 10px; }}
  details.fold {{
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: 8px 12px 10px;
    background: #faf7f1;
  }}
  details.fold > summary {{
    cursor: pointer;
    font-weight: 650;
    color: var(--accent);
    list-style: none;
    padding: 6px 2px;
  }}
  details.fold > summary::-webkit-details-marker {{ display: none; }}
  details.fold[open] > summary {{ margin-bottom: 8px; }}
  table.compact th, table.compact td {{
    padding: 6px 8px;
    font-size: 12.5px;
  }}
  section h2 {{
    margin: 0 0 14px;
    font-size: 1.12rem;
    color: var(--accent);
    letter-spacing: -0.01em;
    display: flex;
    align-items: center;
    gap: 10px;
  }}
  section h2::before {{
    content: "";
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--accent);
    flex-shrink: 0;
  }}
  h3 {{
    margin: 18px 0 8px;
    font-size: 0.98rem;
    color: var(--ink);
  }}
  p {{ margin: 0 0 10px; }}
  .meta-bar {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px 16px;
    font-size: 12.5px;
    color: var(--muted);
    margin-bottom: 14px;
    padding-bottom: 12px;
    border-bottom: 1px dashed var(--line);
  }}
  .quote {{
    margin: 12px 0 0;
    padding: 12px 14px;
    background: var(--accent-soft);
    border-left: 3px solid var(--accent);
    border-radius: 0 10px 10px 0;
    color: #243636;
    font-size: 0.95rem;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13.5px;
  }}
  th, td {{
    text-align: left;
    padding: 9px 10px;
    border-bottom: 1px solid var(--line);
    vertical-align: top;
  }}
  th {{
    width: 34%;
    color: var(--muted);
    font-weight: 600;
    background: #faf7f1;
  }}
  tr:last-child th, tr:last-child td {{ border-bottom: 0; }}
  ul {{ margin: 6px 0 10px; padding-left: 1.15rem; }}
  li {{ margin: 4px 0; }}
  .grid-2 {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 14px;
  }}
  .card {{
    background: #faf7f1;
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: 14px;
  }}
  .card h3 {{ margin-top: 0; }}
  .muted {{ color: var(--muted); font-size: 13px; }}
  .badge {{
    display: inline-block;
    background: var(--accent);
    color: #fff;
    font-size: 11px;
    font-weight: 650;
    letter-spacing: .04em;
    text-transform: uppercase;
    padding: 3px 8px;
    border-radius: 6px;
    vertical-align: middle;
  }}
  .badge.warn {{
    background: var(--warn-bg);
    color: var(--warn);
    border: 1px solid #e5d2b4;
  }}
  .shot {{
    margin: 12px 0 4px;
    border: 1px solid var(--line);
    border-radius: 12px;
    overflow: hidden;
    background: #111;
  }}
  .shot img {{
    display: block;
    width: 100%;
    height: auto;
  }}
  .shot.contain {{
    background: #f7f4ee;
  }}
  .shot.contain img {{
    object-fit: contain;
    max-height: 720px;
    margin: 0 auto;
  }}
  figcaption {{
    font-size: 12.5px;
    color: var(--muted);
    margin: 6px 2px 14px;
  }}
  .timeline {{
    border-left: 2px solid var(--line);
    margin: 8px 0 0 6px;
    padding-left: 16px;
  }}
  .timeline .item {{
    position: relative;
    margin: 0 0 14px;
  }}
  .timeline .item::before {{
    content: "";
    position: absolute;
    left: -21px; top: 6px;
    width: 10px; height: 10px;
    border-radius: 50%;
    background: var(--accent);
    border: 2px solid var(--paper);
    box-shadow: 0 0 0 1px var(--accent);
  }}
  .timeline .year {{
    font-weight: 700;
    font-size: 13px;
    color: var(--accent);
  }}
  .note {{
    background: var(--warn-bg);
    border: 1px solid #e5d2b4;
    border-radius: 10px;
    padding: 12px 14px;
    color: #4a3418;
    font-size: 13.5px;
  }}
  .note ul {{ margin: 0; padding-left: 1.1rem; }}
  .id-label {{
    font-family: Consolas, "Courier New", monospace;
    font-size: 0.85em;
    font-weight: 700;
  }}
  footer.doc {{
    margin-top: 28px;
    text-align: center;
    color: var(--muted);
    font-size: 12px;
  }}
  @media (max-width: 720px) {{
    header.hero {{ grid-template-columns: 1fr; justify-items: center; text-align: center; }}
    .chips {{ justify-content: center; }}
    nav.toc {{ justify-content: center; }}
    .grid-2 {{ grid-template-columns: 1fr; }}
    th {{ width: 40%; }}
  }}
  @media print {{
    body {{ background: #fff; }}
    .screen-bar {{ display: none !important; }}
    .wrap {{ max-width: none; padding: 0; }}
    header.hero, section {{ box-shadow: none; break-inside: avoid; }}
    nav.toc.jump {{ position: static; box-shadow: none; }}
    details.fold {{ border: 0; background: transparent; padding: 0; }}
    details.fold > summary {{ display: none; }}
    details.fold[open], details.fold {{ display: block; }}
  }}
</style>
</head>
<body>
  <div class="screen-bar">
    <span>{_e(bar_label)}</span>
    <button type="button" onclick="window.print()">Imprimir / PDF</button>
  </div>
  <div class="wrap">

<header class="hero">
{avatar_block}
  <div>
    <p class="kicker">{_e(kicker)}</p>
    <h1>{_e(title)}</h1>
    {f'<p class="subtitle">{_e(subtitle)}</p>' if subtitle else ''}
    {chips_html}
  </div>
</header>

{toc_html}

<section id="meta" class="sec-meta">
  {meta_bar}
  {intro_html}
</section>

{facts_section}
{id_section}
{sections_html}
{timeline_section}
{sources_section}
{shots_section}
{gaps_section}

<footer class="doc">{_e(footer)}</footer>

  </div>
</body>
</html>
"""

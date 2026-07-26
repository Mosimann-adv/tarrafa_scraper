# -*- coding: utf-8 -*-
"""
HTML print-ready — laudo order-risk (chargeback / pedido e-commerce).

Imagens sempre via data URI embutida (image_src), nunca path relativo.
"""
from __future__ import annotations

import html
from typing import Any


def _e(s: Any) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def _band_class(level: str | None) -> str:
    lv = (level or "").lower()
    if lv in ("low", "baixo"):
        return "low"
    if lv in ("high", "alto"):
        return "high"
    if lv in ("unknown", "desconhecido"):
        return "unk"
    return "mid"


def _band_label(level: str | None) -> str:
    m = {
        "low": "Baixo",
        "mid": "Médio",
        "high": "Alto",
        "low_mid": "Baixo–moderado residual",
        "unknown": "Desconhecido",
    }
    return m.get((level or "").lower(), level or "—")


def _pol_class(p: str) -> str:
    return {
        "positive": "pos",
        "negative": "neg",
        "neutral": "neu",
        "gap": "gap",
    }.get(p, "neu")


def render_order_risk(
    *,
    title: str,
    collected_at: str,
    store_url: str,
    buyer: dict[str, Any],
    bands: dict[str, Any],
    signals: list[dict[str, Any]],
    store: dict[str, Any] | None = None,
    djen: dict[str, Any] | None = None,
    shots: list[dict[str, Any]] | None = None,
    notes: list[str] | None = None,
    artifacts: list[str] | None = None,
    kicker: str = "Tarrafa · order-risk",
) -> str:
    """
    shots[]: {id, caption, image_src}  — image_src DEVE ser data: URI embutida.
    """
    store = store or {}
    djen = djen or {}
    shots = list(shots or [])
    notes = list(notes or [])
    artifacts = list(artifacts or [])

    pos = [s for s in signals if s.get("polarity") == "positive"]
    neg = [s for s in signals if s.get("polarity") == "negative"]
    gaps = [s for s in signals if s.get("polarity") in ("gap", "neutral")]

    def _sig_li(s: dict[str, Any]) -> str:
        return (
            f'<li class="{_pol_class(str(s.get("polarity")))}">'
            f"<strong>{_e(s.get('label'))}</strong>"
            f'<span class="detail">{_e(s.get("detail"))}</span></li>'
        )

    pos_html = "\n".join(_sig_li(s) for s in pos) or "<li class='neu'><strong>Nenhum</strong></li>"
    neg_html = "\n".join(_sig_li(s) for s in neg) or "<li class='neu'><strong>Nenhum negativo material</strong></li>"
    gap_html = "\n".join(_sig_li(s) for s in gaps) or ""

    shots_html_parts: list[str] = []
    for sh in shots:
        src = (sh.get("image_src") or "").strip()
        if not src:
            continue
        # Only allow data: or https: for safety
        if not (src.startswith("data:") or src.startswith("https://") or src.startswith("http://")):
            continue
        cap = sh.get("caption") or sh.get("id") or "Evidência"
        sid = sh.get("id") or ""
        shots_html_parts.append(
            f"""<figure class="shot">
  <img src="{_e(src)}" alt="{_e(cap)}" />
  <figcaption><strong>{_e(sid)}</strong>{_e(cap)}</figcaption>
</figure>"""
        )
    shots_block = ""
    if shots_html_parts:
        shots_block = f"""
<section class="block">
  <h2><span class="dot info"></span> Evidências visuais</h2>
  <p class="box-muted">Imagens embutidas (data URI) — HTML autocontido para anexo/arquivo único.</p>
  <div class="gallery">
    {"".join(shots_html_parts)}
  </div>
</section>"""

    store_rows = []
    for k, label in (
        ("title", "Título"),
        ("url", "URL"),
        ("cnpj_formatted", "CNPJ"),
        ("company_name", "Razão"),
        ("alias", "Alias"),
        ("cnpj_status", "Situação"),
        ("founded", "Fundação"),
        ("address", "Endereço empresa"),
        ("domain_created", "Domínio desde"),
        ("domain_expires", "Domínio expira"),
    ):
        v = store.get(k)
        if v:
            store_rows.append(f"<tr><td>{_e(label)}</td><td>{_e(v)}</td></tr>")

    djen_block = ""
    if djen.get("queried") or djen.get("processos_sample"):
        procs = djen.get("processos_sample") or []
        tags = " ".join(f'<span class="tag">{_e(p)}</span>' for p in procs[:12])
        djen_block = f"""
<section class="block">
  <h2><span class="dot info"></span> DJEN / Datajud</h2>
  <p>Comunicações (CPF): <strong>{_e(djen.get("cpf_hits", 0))}</strong> ·
     processos únicos: <strong>{_e(djen.get("unique_processos", 0))}</strong>
     {_e(" · nome civil ≈ " + djen["civil_name_hint"]) if djen.get("civil_name_hint") else ""}</p>
  <div>{tags}</div>
</section>"""

    notes_html = "".join(f"<li>{_e(n)}</li>" for n in notes)
    art_html = "".join(f"<li class='mono'>{_e(a)}</li>" for a in artifacts)

    buyer_rows = []
    for k, label in (
        ("name", "Nome"),
        ("cpf", "CPF"),
        ("dob", "Nascimento"),
        ("gender", "Gênero"),
        ("phone", "Telefone"),
        ("email", "E-mail"),
        ("street", "Logradouro"),
        ("number", "Número"),
        ("complement", "Complemento"),
        ("neighborhood", "Bairro"),
        ("city", "Cidade"),
        ("state", "UF"),
        ("cep", "CEP"),
    ):
        v = buyer.get(k)
        if v:
            buyer_rows.append(
                f"<dt>{_e(label)}</dt><dd class='{'mono' if k in ('cpf','phone','email','cep') else ''}'>{_e(v)}</dd>"
            )

    id_band = bands.get("identity_fraud")
    mer_band = bands.get("merchant")
    ff_band = bands.get("friendly_fraud_residual")

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_e(title)}</title>
  <style>
    :root {{
      --bg: #f4f1ec; --paper: #fffcf7; --ink: #1a1a1a; --muted: #5c5a56;
      --line: #e4ddd3; --green: #1b6b3a; --green-bg: #e8f5ec;
      --amber: #8a5a00; --amber-bg: #fbf3e0; --red: #8b1e1e; --red-bg: #f8eaea;
      --blue: #1a3a5c; --accent: #c45c26;
      --mono: "Cascadia Mono", Consolas, ui-monospace, monospace;
      --sans: "Segoe UI", system-ui, sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--ink); font-family: var(--sans); font-size: 15px; line-height: 1.55; }}
    .wrap {{ max-width: 920px; margin: 0 auto; padding: 32px 20px 64px; }}
    header.hero, section.block {{
      background: var(--paper); border: 1px solid var(--line); border-radius: 14px;
      padding: 24px 28px; margin-bottom: 16px;
    }}
    .kicker {{ font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); font-weight: 600; margin-bottom: 10px; }}
    h1 {{ margin: 0 0 8px; font-size: 1.5rem; letter-spacing: -0.02em; }}
    .subtitle {{ color: var(--muted); font-size: 14px; margin: 0; }}
    .grid-verdict {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 20px; }}
    @media (max-width: 720px) {{ .grid-verdict {{ grid-template-columns: 1fr; }} }}
    .card-v {{ border-radius: 12px; border: 1px solid var(--line); padding: 14px 16px; background: #fff; }}
    .card-v.low {{ border-left: 4px solid var(--green); }}
    .card-v.mid {{ border-left: 4px solid #d4a017; }}
    .card-v.high {{ border-left: 4px solid var(--red); }}
    .card-v.unk {{ border-left: 4px solid #999; }}
    .card-v .label {{ font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); font-weight: 700; }}
    .card-v .level {{ font-size: 1.1rem; font-weight: 700; margin: 4px 0; }}
    .card-v.low .level {{ color: var(--green); }}
    .card-v.mid .level {{ color: var(--amber); }}
    .card-v.high .level {{ color: var(--red); }}
    .synth {{ margin-top: 16px; padding: 12px 14px; border-radius: 10px; background: var(--green-bg); border: 1px solid #b9dfc6; font-size: 14px; color: #143d24; }}
    h2 {{ margin: 0 0 12px; font-size: 1.05rem; display: flex; align-items: center; gap: 10px; }}
    .dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}
    .dot.pos {{ background: var(--green); }} .dot.neg {{ background: var(--amber); }}
    .dot.info {{ background: var(--blue); }} .dot.gap {{ background: #888; }}
    .meta-row {{ display: grid; grid-template-columns: 140px 1fr; gap: 6px 16px; font-size: 14px; }}
    .meta-row dt {{ color: var(--muted); font-weight: 600; }} .meta-row dd {{ margin: 0; }}
    ul.checks {{ list-style: none; margin: 0; padding: 0; }}
    ul.checks li {{ position: relative; padding: 10px 12px 10px 36px; border-bottom: 1px solid var(--line); }}
    ul.checks li:last-child {{ border-bottom: 0; }}
    ul.checks li::before {{ position: absolute; left: 8px; top: 10px; width: 20px; height: 20px; border-radius: 50%;
      text-align: center; font-size: 12px; font-weight: 700; line-height: 20px; }}
    ul.checks li.pos::before {{ content: "✓"; background: var(--green-bg); color: var(--green); }}
    ul.checks li.neg::before {{ content: "!"; background: var(--amber-bg); color: var(--amber); }}
    ul.checks li.gap::before, ul.checks li.neu::before {{ content: "·"; background: #eee; color: #666; }}
    ul.checks li .detail {{ display: block; margin-top: 4px; color: var(--muted); font-size: 13px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13.5px; }}
    th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--line); vertical-align: top; }}
    th {{ font-size: 11px; text-transform: uppercase; color: var(--muted); background: #f7f3ed; }}
    .mono {{ font-family: var(--mono); font-size: 12.5px; }}
    .tag {{ display: inline-block; font-family: var(--mono); font-size: 11px; background: #f0ebe3; padding: 2px 7px; border-radius: 4px; margin: 2px; }}
    .box-muted {{ background: #f7f3ed; border-radius: 10px; padding: 12px 14px; font-size: 13px; color: var(--muted); }}
    .gallery {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 8px; }}
    @media (max-width: 720px) {{ .gallery {{ grid-template-columns: 1fr; }} .meta-row {{ grid-template-columns: 1fr; }} }}
    figure.shot {{ margin: 0; border: 1px solid var(--line); border-radius: 10px; overflow: hidden; background: #fff; }}
    figure.shot img {{ display: block; width: 100%; height: auto; max-height: 420px; object-fit: contain; background: #f0ebe3; }}
    figure.shot figcaption {{ padding: 10px 12px; font-size: 12.5px; color: var(--muted); border-top: 1px solid var(--line); }}
    figure.shot figcaption strong {{ display: block; color: var(--ink); margin-bottom: 2px; }}
    footer.foot {{ text-align: center; font-size: 12px; color: var(--muted); padding: 16px; }}
    @media print {{ body {{ background: #fff; }} .wrap {{ padding: 0; }} section.block, header.hero, figure.shot {{ break-inside: avoid; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <header class="hero">
      <div class="kicker">{_e(kicker)} · {_e(collected_at)}</div>
      <h1>{_e(title)}</h1>
      <p class="subtitle">Loja: <strong>{_e(store_url)}</strong></p>
      <div class="grid-verdict">
        <div class="card-v {_band_class(id_band)}">
          <div class="label">Identidade / cartão roubado</div>
          <div class="level">{_e(_band_label(id_band))}</div>
        </div>
        <div class="card-v {_band_class(ff_band)}">
          <div class="label">Friendly fraud (residual)</div>
          <div class="level">{_e(_band_label(ff_band))}</div>
        </div>
        <div class="card-v {_band_class(mer_band)}">
          <div class="label">Merchant (loja)</div>
          <div class="level">{_e(_band_label(mer_band))}</div>
        </div>
      </div>
      <div class="synth">
        <strong>Síntese:</strong> bandas derivadas de checks materiais (CPF, CEP, DJEN, CNPJ/RDAP).
        Não substitui gateway/BIN/device/3DS.
      </div>
    </header>

    <section class="block">
      <h2><span class="dot info"></span> Cadastro do pedido</h2>
      <dl class="meta-row">
        {"".join(buyer_rows)}
      </dl>
    </section>

    <section class="block">
      <h2><span class="dot pos"></span> Sinais positivos</h2>
      <ul class="checks">{pos_html}</ul>
    </section>

    <section class="block">
      <h2><span class="dot neg"></span> Sinais negativos / atenção</h2>
      <ul class="checks">{neg_html}</ul>
    </section>

    {f'''<section class="block">
      <h2><span class="dot gap"></span> Gaps / neutros</h2>
      <ul class="checks">{gap_html}</ul>
    </section>''' if gap_html else ""}

    {f'''<section class="block">
      <h2><span class="dot info"></span> Loja</h2>
      <table><thead><tr><th>Item</th><th>Achado</th></tr></thead>
      <tbody>{"".join(store_rows)}</tbody></table>
    </section>''' if store_rows else ""}

    {djen_block}
    {shots_block}

    {f'''<section class="block">
      <h2><span class="dot info"></span> Notas</h2>
      <ul>{notes_html}</ul>
    </section>''' if notes_html else ""}

    {f'''<section class="block">
      <h2><span class="dot info"></span> Artefatos</h2>
      <ul>{art_html}</ul>
    </section>''' if art_html else ""}

    <footer class="foot">
      tarrafa order-risk · material-only · imagens embutidas · {_e(collected_at)}
    </footer>
  </div>
</body>
</html>
"""

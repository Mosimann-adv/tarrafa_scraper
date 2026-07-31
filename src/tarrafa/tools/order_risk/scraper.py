# -*- coding: utf-8 -*-
"""
tarrafa order-risk — triagem de risco de chargeback em pedido e-commerce.

Orquestra checks materiais (CPF, CEP, DJEN/Datajud, loja/CNPJ/RDAP, opcional IG/Maps)
e gera envelope JSON + HTML print-ready com imagens **embutidas** (data URI).

  tarrafa order-risk \\
    --store-url "https://loja.example" \\
    --name "Nome Comprador" \\
    --cpf "000.000.000-00" \\
    --cep "00000-000" \\
    --city "Cidade" --state UF \\
    --street "Rua Exemplo" --number "100" \\
    --phone "(00) 90000-0000" --email "user@example.com" \\
    --out-dir ./caso_order_risk --html --shot-maps

Material-only: sinais e bandas transparentes; sem biografia inventada.
Não menciona nem depende de pedidos/pessoas reais embutidos no código.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from tarrafa.core.envelope import build_envelope
from tarrafa.core.http import DEFAULT_TIMEOUT, DEFAULT_UA, ensure_httpx
from tarrafa.core.media import ensure_dir, file_to_data_uri
from tarrafa.core.run import register_artifact
from tarrafa.core.writers import utc_now_iso, write_json
from tarrafa.templates.order_risk_html import render_order_risk
from tarrafa.tools.order_risk.checks import (
    build_signals_from_facts,
    compute_bands,
    digits_only,
    domain_from_url,
    extract_cnpjs,
    extract_emails,
    extract_wa_me,
    format_cep,
    format_cpf,
    match_address_fields,
    normalize_phone_br,
    number_in_cep_range,
    parse_dob,
    validate_cpf,
)


def _http_json(url: str, *, timeout: float) -> dict[str, Any]:
    httpx = ensure_httpx()
    headers = {"User-Agent": DEFAULT_UA, "Accept": "application/json"}
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            r = client.get(url)
            if r.status_code != 200:
                return {"ok": False, "status": r.status_code, "error": f"HTTP {r.status_code}", "data": None}
            try:
                data = r.json()
            except Exception as e:
                return {"ok": False, "status": r.status_code, "error": f"json: {e}", "data": None}
            return {"ok": True, "status": r.status_code, "error": None, "data": data}
    except Exception as e:
        return {"ok": False, "status": None, "error": f"{type(e).__name__}: {e}", "data": None}


def fetch_viacep(cep: str, *, timeout: float) -> dict[str, Any]:
    d = digits_only(cep)
    if len(d) != 8:
        return {"ok": False, "error": "CEP precisa 8 dígitos", "via": None}
    res = _http_json(f"https://viacep.com.br/ws/{d}/json/", timeout=timeout)
    data = res.get("data") if res.get("ok") else None
    if not isinstance(data, dict) or data.get("erro"):
        return {
            "ok": False,
            "error": res.get("error") or "CEP não encontrado",
            "via": data if isinstance(data, dict) else None,
        }
    return {"ok": True, "error": None, "via": data}


def fetch_rdap_br(domain: str, *, timeout: float) -> dict[str, Any]:
    res = _http_json(f"https://rdap.registro.br/domain/{domain}", timeout=timeout)
    if not res.get("ok") or not isinstance(res.get("data"), dict):
        return {"ok": False, "error": res.get("error") or "rdap fail", "events": [], "raw": res.get("data")}
    data = res["data"]
    events = []
    for ev in data.get("events") or []:
        if isinstance(ev, dict):
            events.append({"action": ev.get("eventAction"), "date": ev.get("eventDate")})
    by_action = {e["action"]: e["date"] for e in events if e.get("action")}
    return {
        "ok": True,
        "error": None,
        "events": events,
        "created": by_action.get("registration"),
        "expires": by_action.get("expiration"),
        "changed": by_action.get("last changed"),
        "status": data.get("status"),
        "handle": data.get("handle") or domain,
    }


def _safe_shot(
    *,
    url: str,
    out_dir: Path,
    item_id: str,
    timeout: float,
    storage_state: str | None = None,
    wait_ms: int = 3000,
) -> dict[str, Any]:
    """Chama tarrafa shot programaticamente; retorna path PNG se ok."""
    try:
        from tarrafa.tools.shot import scraper as shot_mod
    except Exception as e:
        return {"ok": False, "error": f"shot import: {e}", "path": None}

    argv = [
        "--url",
        url,
        "--out-dir",
        str(out_dir),
        "--id",
        item_id,
        "--clip",
        "page",
        "--width",
        "1280",
        "--height",
        "900",
        "--dpr",
        "1",
        "--wait-ms",
        str(wait_ms),
        "--timeout",
        str(int(timeout)),
    ]
    if storage_state:
        argv.extend(["--storage-state", storage_state])
    try:
        code = shot_mod.main(argv)
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 1
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "path": None}

    png = out_dir / f"{item_id}.png"
    if code == 0 and png.is_file() and png.stat().st_size > 500:
        return {"ok": True, "error": None, "path": str(png), "bytes": png.stat().st_size}
    return {
        "ok": False,
        "error": f"shot exit={code} or empty png",
        "path": str(png) if png.is_file() else None,
    }


def _capture_store_page(url: str, *, timeout: float, out_json: Path) -> dict[str, Any]:
    try:
        from tarrafa.tools.page import scraper as page_mod
    except Exception as e:
        return {"ok": False, "error": f"page import: {e}", "text": "", "title": None, "url": url}

    argv = ["--url", url, "--out", str(out_json), "--timeout", str(int(timeout))]
    try:
        code = page_mod.main(argv)
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 1
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "text": "", "title": None, "url": url}

    if not out_json.is_file():
        return {"ok": False, "error": f"page exit={code}, sem arquivo", "text": "", "title": None, "url": url}
    try:
        env = json.loads(out_json.read_text(encoding="utf-8"))
    except Exception as e:
        return {"ok": False, "error": f"page json: {e}", "text": "", "title": None, "url": url}

    items = env.get("items") or []
    it = items[0] if items else {}
    text = it.get("text") or it.get("text_main") or ""
    # append structured facts / meta into search blob
    blob_parts = [text, json.dumps(it.get("meta_tags") or {}, ensure_ascii=False)]
    for fact in it.get("structured_facts") or []:
        if isinstance(fact, dict):
            blob_parts.append(str(fact.get("value") or ""))
    blob = "\n".join(blob_parts)
    return {
        "ok": code == 0 and bool(text or it.get("title")),
        "error": None if code == 0 else f"page exit={code}",
        "text": blob,
        "title": it.get("title"),
        "url": it.get("final_url") or it.get("url") or url,
        "envelope_path": str(out_json),
    }


def _run_djen_cpf(cpf: str, *, max_items: int, timeout: float, raw_dir: Path) -> dict[str, Any]:
    from tarrafa.tools.djen.scraper import _follow_datajud, collect_comunicacoes, mask_cpf

    formatted = format_cpf(cpf)
    digits = digits_only(cpf)
    result: dict[str, Any] = {
        "queried": True,
        "cpf_hits": 0,
        "unique_processos": 0,
        "processos_sample": [],
        "by_tribunal": {},
        "civil_name_hint": None,
        "error": None,
    }
    try:
        coll = collect_comunicacoes(
            cpf=formatted,
            papel="parte",
            max_items=max_items,
            post_filter=False,
            timeout=timeout,
        )
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["queried"] = True
        return result

    items = coll.get("items") or []
    summary = coll.get("summary") or {}
    # envelope partial dump
    env = build_envelope(
        "djen",
        source={
            "papel": "parte",
            "cpf": mask_cpf(formatted),
            "search_priority": "cpf",
            "from": "order-risk",
        },
        items=[{"kind": "djen_summary", **summary}] + items,
        meta=coll.get("meta") or {},
        errors=coll.get("errors") or [],
        notes=["Gerado por tarrafa order-risk (busca DJEN por CPF)."],
    )
    djen_path = raw_dir / "djen_cpf.json"
    write_json(djen_path, env)
    result["path"] = str(djen_path)

    result["cpf_hits"] = len(items)
    result["unique_processos"] = summary.get("unique_processos") or len(summary.get("processos_sample") or [])
    result["processos_sample"] = list(summary.get("processos_sample") or [])[:20]
    result["by_tribunal"] = summary.get("by_tribunal") or {}

    # civil name heuristic from texto_plain when CPF appears
    name_hint = None
    # simpler: look for "NOME CPF: xxx" patterns
    for it in items:
        plain = it.get("texto_plain") or ""
        if digits not in digits_only(plain) and formatted not in plain:
            continue
        m = re.search(
            r"([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇa-záéíóúâêôãõç' ]{5,80}?)\s+CPF:\s*"
            + re.escape(formatted),
            plain,
        )
        if not m:
            m = re.search(
                r"AUTOR:\s*([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇa-záéíóúâêôãõç' ]{5,80}?)\s+CPF:\s*"
                + re.escape(formatted),
                plain,
                re.I,
            )
        if m:
            name_hint = re.sub(r"\s+", " ", m.group(1)).strip(" :")
            break
    result["civil_name_hint"] = name_hint

    # follow datajud on sample
    cnjs = result["processos_sample"][:8]
    if cnjs:
        try:
            dj_out = raw_dir / "datajud_cpf.json"
            follow = _follow_datajud(cnjs, out_path=dj_out, max_cnj=8, timeout=timeout)
            result["datajud"] = follow
        except Exception as e:
            result["datajud_error"] = f"{type(e).__name__}: {e}"

    if coll.get("errors"):
        result["errors"] = coll["errors"]
    return result


def _lookup_cnpj(cnpj: str, *, timeout: float, out_json: Path) -> dict[str, Any]:
    from tarrafa.tools.cnpj.scraper import fetch_office, format_cnpj, summarize_office

    res = fetch_office(cnpj, timeout=timeout)
    if not res.get("ok") or not res.get("data"):
        return {
            "ok": False,
            "error": res.get("error"),
            "cnpj": digits_only(cnpj),
            "cnpj_formatted": format_cnpj(cnpj),
        }
    summary = summarize_office(res["data"])
    env = build_envelope(
        "cnpj",
        source={"url": res.get("url"), "cnpjs": [digits_only(cnpj)], "from": "order-risk"},
        items=[{"kind": "cnpj_office", **summary, "raw": res["data"]}],
        meta={"provider": "cnpja", "from": "order-risk"},
        notes=["Gerado por tarrafa order-risk."],
    )
    write_json(out_json, env)
    return {
        "ok": True,
        "error": None,
        "path": str(out_json),
        "cnpj": summary.get("cnpj") or digits_only(cnpj),
        "cnpj_formatted": summary.get("cnpj_formatted") or format_cnpj(cnpj),
        "company_name": summary.get("company_name"),
        "alias": summary.get("alias"),
        "status": (summary.get("status") if isinstance(summary.get("status"), str) else None)
        or summary.get("status"),
        "founded": summary.get("founded"),
        "address": summary.get("address"),
        "summary": summary,
    }


def _ig_capture(
    url: str,
    *,
    raw_dir: Path,
    shots_dir: Path,
    timeout: float,
    storage_state: str | None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"url": url, "ok": False}
    handle_m = re.search(r"instagram\.com/([^/?#]+)", url, re.I)
    out["handle"] = handle_m.group(1) if handle_m else None

    page_out = raw_dir / "ig_profile.json"
    try:
        from tarrafa.tools.page import scraper as page_mod

        argv = ["--url", url, "--out", str(page_out), "--mode", "browser", "--timeout", str(int(timeout))]
        if storage_state:
            argv.extend(["--storage-state", storage_state])
        try:
            code = page_mod.main(argv)
        except SystemExit as e:
            code = int(e.code) if e.code is not None else 1
        if page_out.is_file():
            env = json.loads(page_out.read_text(encoding="utf-8"))
            it = (env.get("items") or [{}])[0]
            text = it.get("text") or ""
            meta = it.get("meta_tags") or {}
            out["title"] = it.get("title") or meta.get("og:title")
            out["private"] = bool(re.search(r"private|privado", text, re.I))
            # display name from og:title "Name (@handle)"
            og = meta.get("og:title") or out.get("title") or ""
            m = re.match(r"(.+?)\s*\(@", og)
            out["display_name"] = m.group(1).strip() if m else None
            # bio link
            m = re.search(r"instagram\.com/([\w.]+)\?", text)
            link_m = re.search(r"(https?://\S+|instagram\.com/[\w.?=&%-]+|linktr\.ee/\S+)", text)
            out["bio_link"] = link_m.group(0) if link_m else None
            out["ok"] = code == 0
            out["path"] = str(page_out)
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"

    shot = _safe_shot(
        url=url,
        out_dir=shots_dir,
        item_id="ig_profile",
        timeout=timeout,
        storage_state=storage_state,
        wait_ms=4000,
    )
    out["shot"] = shot
    return out


def run_order_risk(
    *,
    store_url: str | None,
    buyer: dict[str, Any],
    out_dir: Path,
    html: bool = True,
    shot_maps: bool = False,
    shot_store: bool = False,
    ig_url: str | None = None,
    storage_state: str | None = None,
    max_djen: int = 50,
    skip_djen: bool = False,
    skip_store: bool = False,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """
    Executa a triagem e grava artefatos em out_dir.
    Retorna o envelope order-risk (dict).
    """
    out_dir = ensure_dir(out_dir)
    raw_dir = ensure_dir(out_dir / "raw")
    shots_dir = ensure_dir(out_dir / "shots")
    errors: list[str] = []
    notes: list[str] = [
        "Material-only: sinais verificáveis em fontes abertas; sem score ML proprietário.",
        "Bandas identity/merchant são regras transparentes sobre os checks.",
        "HTML embute imagens em data URI (arquivo autocontido).",
        "Não avalia BIN/AVS/CVV/IP/device/3DS — gaps explícitos.",
    ]
    artifacts: list[str] = []
    shot_records: list[dict[str, Any]] = []

    # --- buyer local checks ---
    cpf_info = validate_cpf(buyer.get("cpf"))
    dob_info = parse_dob(buyer.get("dob"))
    phone_info = normalize_phone_br(buyer.get("phone"))

    cep_block: dict[str, Any] = {"api_ok": False}
    if buyer.get("cep"):
        via_res = fetch_viacep(str(buyer["cep"]), timeout=timeout)
        cep_block["api_ok"] = bool(via_res.get("ok"))
        cep_block["error"] = via_res.get("error")
        cep_block["via"] = via_res.get("via")
        cep_block["formatted"] = format_cep(str(buyer["cep"]))
        if via_res.get("ok") and via_res.get("via"):
            cep_block["field_matches"] = match_address_fields(
                street=buyer.get("street"),
                neighborhood=buyer.get("neighborhood"),
                city=buyer.get("city"),
                state=buyer.get("state"),
                via=via_res["via"],
            )
            cep_block["number_range"] = number_in_cep_range(
                buyer.get("number"),
                (via_res["via"] or {}).get("complemento"),
            )
            write_json(raw_dir / "cep_viacep.json", via_res["via"])
            artifacts.append(str(raw_dir / "cep_viacep.json"))
        else:
            errors.append(f"viacep: {via_res.get('error')}")

    # --- store ---
    store_block: dict[str, Any] = {"url": store_url}
    if store_url and not skip_store:
        page = _capture_store_page(store_url, timeout=timeout, out_json=raw_dir / "store_home.json")
        store_block["reachable"] = True if page.get("ok") else None
        store_block["title"] = page.get("title")
        store_block["url"] = page.get("url") or store_url
        store_block["error"] = page.get("error")
        if not page.get("ok"):
            errors.append(f"store: {page.get('error') or 'captura inconclusiva'}")
        if page.get("envelope_path"):
            artifacts.append(page["envelope_path"])
        text = page.get("text") or ""
        cnpjs = extract_cnpjs(text)
        # also try privacy-like paths if no cnpj
        if not cnpjs and store_url:
            base = store_url.rstrip("/")
            for path in ("/politica-de-privacidade", "/politica-de-privacidade/", "/privacy"):
                try:
                    p2 = _capture_store_page(
                        base + path,
                        timeout=min(timeout, 25),
                        out_json=raw_dir / "store_privacy.json",
                    )
                    cnpjs = extract_cnpjs(p2.get("text") or "")
                    if cnpjs:
                        text += "\n" + (p2.get("text") or "")
                        if p2.get("envelope_path"):
                            artifacts.append(p2["envelope_path"])
                        break
                except Exception:
                    pass
        store_block["cnpjs_found"] = cnpjs
        store_block["emails_found"] = extract_emails(text)[:10]
        store_block["wa_found"] = extract_wa_me(text)

        if cnpjs:
            cnpj_res = _lookup_cnpj(cnpjs[0], timeout=timeout, out_json=raw_dir / "cnpj_store.json")
            if cnpj_res.get("path"):
                artifacts.append(cnpj_res["path"])
            status = cnpj_res.get("status")
            # summarize_office may nest status
            if isinstance(status, dict):
                status = status.get("text")
            sum_status = None
            if cnpj_res.get("summary"):
                sum_status = cnpj_res["summary"].get("status")
                if isinstance(sum_status, dict):
                    sum_status = sum_status.get("text")
            status_txt = status or sum_status or ""
            if not cnpj_res.get("ok"):
                errors.append(f"cnpj: {cnpj_res.get('error') or 'consulta inconclusiva'}")
            store_block["cnpj"] = cnpj_res.get("cnpj")
            store_block["cnpj_formatted"] = cnpj_res.get("cnpj_formatted")
            store_block["company_name"] = cnpj_res.get("company_name")
            store_block["alias"] = cnpj_res.get("alias")
            store_block["cnpj_status"] = status_txt
            store_block["founded"] = cnpj_res.get("founded")
            store_block["address"] = cnpj_res.get("address")
            status_cf = str(status_txt).strip().casefold()
            status_is_active = status_cf == "ativa" or status_cf.startswith("ativa ")
            store_block["cnpj_verified"] = bool(cnpj_res.get("ok"))
            store_block["cnpj_active"] = bool(cnpj_res.get("ok")) and status_is_active
            store_block["cnpj_inactive"] = (
                bool(cnpj_res.get("ok"))
                and bool(status_cf)
                and not status_is_active
            )

        dom = domain_from_url(store_url)
        if dom and dom.endswith(".br"):
            rdap = fetch_rdap_br(dom, timeout=timeout)
            write_json(raw_dir / "rdap_domain.json", rdap)
            artifacts.append(str(raw_dir / "rdap_domain.json"))
            store_block["domain"] = dom
            store_block["domain_registered"] = bool(rdap.get("ok"))
            store_block["domain_created"] = rdap.get("created")
            store_block["domain_expires"] = rdap.get("expires")
            store_block["rdap_events"] = rdap.get("events")
            if not rdap.get("ok"):
                errors.append(f"rdap: {rdap.get('error') or 'consulta inconclusiva'}")

        if shot_store:
            sh = _safe_shot(
                url=store_url,
                out_dir=shots_dir,
                item_id="store_home",
                timeout=timeout,
                wait_ms=2500,
            )
            store_block["shot"] = sh
            if sh.get("ok") and sh.get("path"):
                shot_records.append(
                    {
                        "id": "store_home",
                        "caption": f"Home da loja — {store_url}",
                        "path": sh["path"],
                    }
                )
            else:
                errors.append(f"shot-store: {sh.get('error') or 'captura inconclusiva'}")
    elif not store_url:
        notes.append("Loja não informada (--store-url); checks de merchant ficam unknown.")
    else:
        notes.append("Captura da loja ignorada (--skip-store).")

    # --- maps shot ---
    if shot_maps and buyer.get("street") and buyer.get("city"):
        parts = [
            buyer.get("street") or "",
            buyer.get("number") or "",
            buyer.get("neighborhood") or "",
            buyer.get("city") or "",
            buyer.get("state") or "",
            buyer.get("cep") or "",
        ]
        q = ", ".join(p for p in parts if p)
        maps_url = f"https://www.google.com/maps/search/?api=1&query={quote(q)}"
        # place-style URL also
        maps_place = f"https://www.google.com/maps/place/{quote(q)}"
        sh = _safe_shot(
            url=maps_place,
            out_dir=shots_dir,
            item_id="maps_address",
            timeout=max(timeout, 45),
            wait_ms=4000,
        )
        if not sh.get("ok"):
            sh = _safe_shot(
                url=maps_url,
                out_dir=shots_dir,
                item_id="maps_address",
                timeout=max(timeout, 45),
                wait_ms=4000,
            )
        if sh.get("ok") and sh.get("path"):
            shot_records.append(
                {
                    "id": "maps_address",
                    "caption": f"Google Maps — {q}",
                    "path": sh["path"],
                }
            )
        else:
            errors.append(f"shot-maps: {sh.get('error') or 'captura inconclusiva'}")
        # satellite attempt
        if buyer.get("cep") and cep_block.get("via"):
            # no guaranteed lat in ViaCEP; optional second shot of place is enough
            pass

    # --- DJEN ---
    djen_block: dict[str, Any] = {"queried": False}
    if not skip_djen and buyer.get("cpf") and cpf_info.get("ok"):
        try:
            djen_block = _run_djen_cpf(
                str(buyer["cpf"]),
                max_items=max_djen,
                timeout=timeout,
                raw_dir=raw_dir,
            )
            if djen_block.get("path"):
                artifacts.append(djen_block["path"])
            if djen_block.get("datajud", {}).get("path"):
                artifacts.append(djen_block["datajud"]["path"])
            if djen_block.get("error"):
                errors.append(f"djen: {djen_block['error']}")
            for error in djen_block.get("errors") or []:
                errors.append(f"djen: {error}")
            if djen_block.get("datajud_error"):
                errors.append(f"datajud: {djen_block['datajud_error']}")
        except Exception as e:
            djen_block = {"queried": False, "error": f"{type(e).__name__}: {e}"}
            errors.append(f"djen: {e}")
    elif skip_djen:
        djen_block = {"queried": False, "error": "skip"}
        notes.append("DJEN ignorado (--skip-djen).")
    elif not buyer.get("cpf"):
        djen_block = {"queried": False, "error": "no_cpf"}

    # --- IG ---
    ig_block: dict[str, Any] = {}
    if ig_url:
        ig_block = _ig_capture(
            ig_url,
            raw_dir=raw_dir,
            shots_dir=shots_dir,
            timeout=timeout,
            storage_state=storage_state,
        )
        if ig_block.get("path"):
            artifacts.append(ig_block["path"])
        if ig_block.get("error"):
            errors.append(f"ig: {ig_block['error']}")
        sh = ig_block.get("shot") or {}
        if sh.get("ok") and sh.get("path"):
            shot_records.append(
                {
                    "id": "ig_profile",
                    "caption": f"Instagram — {ig_block.get('handle') or ig_url}",
                    "path": sh["path"],
                }
            )
        elif sh.get("error"):
            errors.append(f"shot-ig: {sh['error']}")

    facts = {
        "buyer": buyer,
        "cpf": cpf_info,
        "cep": cep_block,
        "phone": phone_info,
        "dob": dob_info,
        "djen": djen_block,
        "store": store_block,
        "ig": ig_block,
    }
    signals = build_signals_from_facts(facts)
    bands = compute_bands(signals)

    # embed shots
    embedded_shots: list[dict[str, Any]] = []
    for sh in shot_records:
        p = Path(sh["path"])
        if not p.is_file():
            continue
        try:
            uri = file_to_data_uri(p)
        except Exception as e:
            errors.append(f"embed {p.name}: {e}")
            continue
        embedded_shots.append(
            {
                "id": sh.get("id"),
                "caption": sh.get("caption"),
                "path": str(p),
                "image_src": uri,
                "bytes": p.stat().st_size,
            }
        )
        artifacts.append(str(p))

    collected_at = utc_now_iso()
    title = f"order-risk — {buyer.get('name') or 'comprador'}"
    if store_url:
        host = urlparse(store_url).hostname or store_url
        title = f"order-risk — {buyer.get('name') or 'comprador'} × {host}"

    html_path = None
    if html:
        html_path = out_dir / "order_risk.html"
        html_doc = render_order_risk(
            title=title,
            collected_at=collected_at,
            store_url=store_url or "—",
            buyer={
                "name": buyer.get("name"),
                "cpf": cpf_info.get("formatted") or buyer.get("cpf"),
                "dob": dob_info.get("display") or buyer.get("dob"),
                "gender": buyer.get("gender"),
                "phone": phone_info.get("display") or buyer.get("phone"),
                "email": buyer.get("email"),
                "street": buyer.get("street"),
                "number": buyer.get("number"),
                "complement": buyer.get("complement"),
                "neighborhood": buyer.get("neighborhood"),
                "city": buyer.get("city"),
                "state": buyer.get("state"),
                "cep": format_cep(str(buyer["cep"])) if buyer.get("cep") else None,
            },
            bands=bands,
            signals=signals,
            store=store_block,
            djen=djen_block,
            shots=embedded_shots,
            notes=notes,
            artifacts=artifacts,
        )
        html_path.write_text(html_doc, encoding="utf-8")
        register_artifact(html_path, kind="html")
        artifacts.append(str(html_path))

    envelope = build_envelope(
        "order-risk",
        source={
            "store_url": store_url,
            "buyer_name": buyer.get("name"),
            "has_cpf": bool(buyer.get("cpf")),
            "has_ig": bool(ig_url),
        },
        items=[
            {
                "kind": "order_risk_report",
                "bands": bands,
                "signals": signals,
                "buyer": buyer,
                "cpf": cpf_info,
                "cep": {k: v for k, v in cep_block.items() if k != "via"} | {"via_keys": list((cep_block.get("via") or {}).keys())},
                "phone": phone_info,
                "dob": dob_info,
                "djen": {
                    k: djen_block.get(k)
                    for k in (
                        "queried",
                        "cpf_hits",
                        "unique_processos",
                        "processos_sample",
                        "by_tribunal",
                        "civil_name_hint",
                        "error",
                        "path",
                    )
                },
                "store": {k: store_block.get(k) for k in store_block if k != "shot"},
                "ig": {k: ig_block.get(k) for k in ig_block if k != "shot"},
                "shots": [
                    {"id": s["id"], "caption": s["caption"], "path": s["path"], "bytes": s.get("bytes")}
                    for s in embedded_shots
                ],
                "html": str(html_path) if html_path else None,
            }
        ],
        meta={
            "bands": bands,
            "signal_counts": {
                "positive": sum(1 for s in signals if s["polarity"] == "positive"),
                "negative": sum(1 for s in signals if s["polarity"] == "negative"),
                "gap": sum(1 for s in signals if s["polarity"] == "gap"),
                "neutral": sum(1 for s in signals if s["polarity"] == "neutral"),
            },
            "out_dir": str(out_dir),
            "html": str(html_path) if html_path else None,
            "shots_embedded": len(embedded_shots),
        },
        errors=errors,
        notes=notes,
        collected_at=collected_at,
    )
    out_json = out_dir / "order_risk.json"
    write_json(out_json, envelope)
    artifacts.append(str(out_json))
    envelope["meta"]["artifacts"] = artifacts
    # rewrite with artifacts list complete
    write_json(out_json, envelope)
    return envelope


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(
        prog="tarrafa order-risk",
        description=(
            "Triagem de risco de chargeback em pedido e-commerce: "
            "CPF, CEP, DJEN/Datajud, loja (CNPJ/RDAP), opcional Maps/IG. "
            "Gera JSON + HTML com imagens embutidas (data URI). Material-only."
        ),
    )
    ap.add_argument("--store-url", default=None, help="URL da loja (home)")
    ap.add_argument("--name", default=None, help="Nome no checkout")
    ap.add_argument("--cpf", default=None, help="CPF do comprador")
    ap.add_argument("--dob", default=None, help="Data de nascimento (dd/mm/yyyy ou yyyy-mm-dd)")
    ap.add_argument("--gender", default=None, help="Gênero (opcional)")
    ap.add_argument("--phone", default=None, help="Telefone")
    ap.add_argument("--email", default=None, help="E-mail")
    ap.add_argument("--street", default=None, help="Logradouro")
    ap.add_argument("--number", default=None, help="Número")
    ap.add_argument("--complement", default=None, help="Complemento")
    ap.add_argument("--neighborhood", default=None, help="Bairro")
    ap.add_argument("--city", default=None, help="Cidade")
    ap.add_argument("--state", default=None, help="UF")
    ap.add_argument("--cep", default=None, help="CEP")
    ap.add_argument("--ig", default=None, dest="ig_url", help="URL do perfil Instagram (opcional)")
    ap.add_argument(
        "--storage-state",
        default=None,
        help="Playwright storage_state.json (sessão IG logada, opcional)",
    )
    ap.add_argument(
        "--out-dir",
        required=True,
        help="Diretório de saída (order_risk.json, order_risk.html, raw/, shots/)",
    )
    ap.add_argument("--html", action=argparse.BooleanOptionalAction, default=True, help="Gerar HTML (default: sim)")
    ap.add_argument("--shot-maps", action="store_true", help="Screenshot Google Maps do endereço")
    ap.add_argument("--shot-store", action="store_true", help="Screenshot da home da loja")
    ap.add_argument("--skip-djen", action="store_true", help="Não consultar DJEN/Datajud")
    ap.add_argument("--skip-store", action="store_true", help="Não capturar loja/CNPJ/RDAP")
    ap.add_argument("--max-djen", type=int, default=50, help="Máx. comunicações DJEN (default 50)")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="Timeout rede/browser (s)")
    ap.add_argument(
        "--buyer-json",
        default=None,
        help="JSON com campos do comprador (sobrescrito por flags explícitas)",
    )
    args = ap.parse_args(argv)

    buyer: dict[str, Any] = {}
    if args.buyer_json:
        p = Path(args.buyer_json)
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            print("error: --buyer-json deve ser objeto", file=sys.stderr)
            return 2
        buyer.update(data)

    def _set(key: str, val: Any) -> None:
        if val is not None and val != "":
            buyer[key] = val

    _set("name", args.name)
    _set("cpf", args.cpf)
    _set("dob", args.dob)
    _set("gender", args.gender)
    _set("phone", args.phone)
    _set("email", args.email)
    _set("street", args.street)
    _set("number", args.number)
    _set("complement", args.complement)
    _set("neighborhood", args.neighborhood)
    _set("city", args.city)
    _set("state", args.state)
    _set("cep", args.cep)

    if not any(buyer.get(k) for k in ("cpf", "name", "cep", "email", "phone")) and not args.store_url:
        print(
            "error: informe ao menos comprador (cpf/name/cep/…) e/ou --store-url",
            file=sys.stderr,
        )
        return 2

    out_dir = Path(args.out_dir)
    try:
        env = run_order_risk(
            store_url=args.store_url,
            buyer=buyer,
            out_dir=out_dir,
            html=bool(args.html),
            shot_maps=bool(args.shot_maps),
            shot_store=bool(args.shot_store),
            ig_url=args.ig_url,
            storage_state=args.storage_state,
            max_djen=int(args.max_djen),
            skip_djen=bool(args.skip_djen),
            skip_store=bool(args.skip_store),
            timeout=float(args.timeout),
        )
    except Exception as e:
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    meta = env.get("meta") or {}
    bands = meta.get("bands") or {}
    print(
        f"order-risk: wrote {out_dir / 'order_risk.json'}  "
        f"identity={bands.get('identity_fraud')}  merchant={bands.get('merchant')}  "
        f"signals={meta.get('signal_counts')}  "
        f"html={meta.get('html') or '—'}  embedded_shots={meta.get('shots_embedded', 0)}"
    )
    if env.get("errors"):
        for er in env["errors"][:8]:
            print(f"  ! {er}", file=sys.stderr)
    return 1 if env.get("errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())

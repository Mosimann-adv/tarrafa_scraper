# -*- coding: utf-8 -*-
"""
Checks puros (sem rede) para tarrafa order-risk.

Sinais materiais: polarity positive | negative | neutral | gap.
Nível de banda derivado de regras transparentes (não é score ML).
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any


def digits_only(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def validate_cpf(cpf: str | None) -> dict[str, Any]:
    """Valida dígitos verificadores do CPF."""
    d = digits_only(cpf)
    if len(d) != 11:
        return {"ok": False, "reason": "len", "digits": d, "formatted": cpf or ""}
    if re.fullmatch(r"(.)\1{10}", d):
        return {"ok": False, "reason": "repeated", "digits": d, "formatted": format_cpf(d)}
    nums = [int(c) for c in d]
    s = sum(nums[i] * (10 - i) for i in range(9))
    r = s % 11
    dv1 = 0 if r < 2 else 11 - r
    if nums[9] != dv1:
        return {"ok": False, "reason": "dv1", "digits": d, "formatted": format_cpf(d)}
    s = sum(nums[i] * (11 - i) for i in range(10))
    r = s % 11
    dv2 = 0 if r < 2 else 11 - r
    if nums[10] != dv2:
        return {"ok": False, "reason": "dv2", "digits": d, "formatted": format_cpf(d)}
    return {"ok": True, "reason": "valid", "digits": d, "formatted": format_cpf(d)}


def format_cpf(digits: str) -> str:
    d = digits_only(digits)
    if len(d) != 11:
        return d
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


def format_cep(digits: str) -> str:
    d = digits_only(digits)
    if len(d) != 8:
        return d
    return f"{d[:5]}-{d[5:]}"


def parse_dob(raw: str | None) -> dict[str, Any]:
    """Aceita dd/mm/yyyy ou yyyy-mm-dd."""
    s = (raw or "").strip()
    if not s:
        return {"ok": False, "reason": "empty", "iso": None, "age": None}
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            dt = datetime.strptime(s, fmt).date()
            today = date.today()
            age = today.year - dt.year - ((today.month, today.day) < (dt.month, dt.day))
            return {"ok": True, "reason": "ok", "iso": dt.isoformat(), "age": age, "display": dt.strftime("%d/%m/%Y")}
        except ValueError:
            continue
    return {"ok": False, "reason": "parse", "iso": None, "age": None}


def normalize_phone_br(phone: str | None) -> dict[str, Any]:
    d = digits_only(phone)
    if d.startswith("55") and len(d) >= 12:
        d = d[2:]
    ddd = d[:2] if len(d) >= 10 else ""
    rest = d[2:] if len(d) >= 10 else d
    mobile = bool(rest) and rest[0] == "9" and len(rest) == 9
    landline = bool(rest) and rest[0] in "2345" and len(rest) == 8
    ok = len(d) in (10, 11) and bool(ddd)
    display = ""
    if ok and mobile:
        display = f"({ddd}) {rest[:5]}-{rest[5:]}"
    elif ok and landline:
        display = f"({ddd}) {rest[:4]}-{rest[4:]}"
    elif d:
        display = d
    return {
        "ok": ok,
        "digits": d,
        "ddd": ddd,
        "mobile": mobile,
        "landline": landline,
        "display": display,
    }


def email_local_has_token(email: str | None, tokens: list[str]) -> bool:
    local = (email or "").split("@")[0].casefold()
    return any(t.casefold() in local for t in tokens if t and len(t) >= 3)


def name_tokens(name: str | None) -> list[str]:
    stop = {"da", "de", "do", "das", "dos", "e"}
    parts = re.findall(r"[A-Za-zÀ-ÿ]+", name or "")
    return [p for p in parts if p.casefold() not in stop]


def number_in_cep_range(number: str | None, complemento_via: str | None) -> dict[str, Any]:
    """
    ViaCEP complemento ex.: 'de 799/800 ao fim' | 'até 798/799' | ''
    Heurística fraca — gap se não interpretar.
    """
    num_s = digits_only(number)
    if not num_s:
        return {"ok": None, "reason": "no_number"}
    try:
        n = int(num_s)
    except ValueError:
        return {"ok": None, "reason": "bad_number"}
    c = (complemento_via or "").strip().casefold()
    if not c:
        return {"ok": None, "reason": "no_range"}
    m = re.search(r"de\s+(\d+)\s*/\s*(\d+)\s+ao\s+fim", c)
    if m:
        lo = min(int(m.group(1)), int(m.group(2)))
        return {"ok": n >= lo, "reason": "from_to_end", "lo": lo, "number": n}
    m = re.search(r"at[eé]\s+(\d+)\s*/\s*(\d+)", c)
    if m:
        hi = max(int(m.group(1)), int(m.group(2)))
        return {"ok": n <= hi, "reason": "until", "hi": hi, "number": n}
    return {"ok": None, "reason": "unparsed", "complemento": c, "number": n}


def match_address_fields(
    *,
    street: str | None,
    neighborhood: str | None,
    city: str | None,
    state: str | None,
    via: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Compara campos do pedido com payload ViaCEP/BrasilAPI-like."""
    via = via or {}
    checks: list[dict[str, Any]] = []

    def _norm(s: str | None) -> str:
        s = (s or "").casefold()
        s = re.sub(r"[^\w\s]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        for a, b in (
            ("á", "a"),
            ("à", "a"),
            ("ã", "a"),
            ("â", "a"),
            ("é", "e"),
            ("ê", "e"),
            ("í", "i"),
            ("ó", "o"),
            ("ô", "o"),
            ("õ", "o"),
            ("ú", "u"),
            ("ç", "c"),
        ):
            s = s.replace(a, b)
        return s

    def _street_parts(s: str | None) -> tuple[str | None, set[str]]:
        normalized = _norm(s)
        aliases = {
            "r": "rua",
            "av": "avenida",
            "rod": "rodovia",
            "estr": "estrada",
            "al": "alameda",
            "tv": "travessa",
            "pca": "praca",
        }
        kinds = {
            "rua",
            "avenida",
            "rodovia",
            "estrada",
            "alameda",
            "travessa",
            "praca",
        }
        stop = {"da", "das", "de", "do", "dos", "e"}
        tokens = [aliases.get(t, t) for t in normalized.split()]
        kind = next((t for t in tokens if t in kinds), None)
        core = {t for t in tokens if t not in kinds and t not in stop and len(t) > 1}
        return kind, core

    pairs = [
        ("street", street, via.get("logradouro") or via.get("street")),
        ("neighborhood", neighborhood, via.get("bairro") or via.get("neighborhood")),
        ("city", city, via.get("localidade") or via.get("city")),
        ("state", state, via.get("uf") or via.get("state")),
    ]
    for key, given, expected in pairs:
        if not given:
            checks.append({"field": key, "match": None, "given": given, "expected": expected, "reason": "missing_given"})
            continue
        if not expected:
            checks.append({"field": key, "match": None, "given": given, "expected": expected, "reason": "missing_api"})
            continue
        g, e = _norm(str(given)), _norm(str(expected))
        if key == "street":
            given_kind, given_core = _street_parts(str(given))
            expected_kind, expected_core = _street_parts(str(expected))
            kind_ok = not given_kind or not expected_kind or given_kind == expected_kind
            overlap = given_core & expected_core
            core_ok = bool(given_core and expected_core) and (
                given_core <= expected_core
                or expected_core <= given_core
                or len(overlap) / max(len(given_core), len(expected_core)) >= 0.75
            )
            ok = kind_ok and core_ok
        elif key == "state":
            ok = g[:2] == e[:2]
        else:
            ok = g == e or g in e or e in g
        checks.append({"field": key, "match": ok, "given": given, "expected": expected, "reason": "ok" if ok else "mismatch"})
    return checks


def extract_cnpjs(text: str | None) -> list[str]:
    """Extrai CNPJs formatados ou 14 dígitos; retorna dígitos únicos válidos em comprimento."""
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}", text):
        d = digits_only(m.group(0))
        if len(d) == 14 and d not in seen:
            seen.add(d)
            found.append(d)
    return found


def extract_emails(text: str | None) -> list[str]:
    if not text:
        return []
    return sorted(set(re.findall(r"[\w.+-]+@[\w.-]+\.\w+", text or "")))


def extract_wa_me(text: str | None) -> list[str]:
    if not text:
        return []
    return sorted(set(re.findall(r"wa\.me/\d+", text or "", flags=re.I)))


def domain_from_url(url: str | None) -> str | None:
    if not url:
        return None
    m = re.match(r"https?://([^/]+)", url.strip(), flags=re.I)
    if not m:
        return None
    host = m.group(1).lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def signal(
    *,
    id: str,
    label: str,
    polarity: str,
    detail: str,
    weight: str = "normal",
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assert polarity in ("positive", "negative", "neutral", "gap")
    assert weight in ("critical", "normal", "soft")
    return {
        "id": id,
        "label": label,
        "polarity": polarity,
        "detail": detail,
        "weight": weight,
        "evidence": evidence or {},
    }


def compute_bands(signals: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Banda transparente:
      identity: low | mid | high
      merchant: low | mid | high | unknown
      friendly_fraud_residual: always low-mid residual note
    """
    by_id = {s["id"]: s for s in signals}

    identity = "mid"
    if by_id.get("cpf_valid", {}).get("polarity") == "negative":
        identity = "high"
    else:
        pos_crit = sum(
            1
            for s in signals
            if s["polarity"] == "positive"
            and s["id"]
            in (
                "cpf_valid",
                "cep_match",
                "djen_cpf_anchor",
                "phone_ddd_match",
            )
        )
        neg = sum(1 for s in signals if s["polarity"] == "negative" and s["weight"] in ("critical", "normal"))
        djen_anchored = by_id.get("djen_cpf_anchor", {}).get("polarity") == "positive"
        if (
            by_id.get("cpf_valid", {}).get("polarity") == "positive"
            and djen_anchored
            and pos_crit >= 3
            and neg == 0
        ):
            identity = "low"
        elif neg >= 2 or by_id.get("cep_match", {}).get("polarity") == "negative":
            identity = "high" if by_id.get("cep_match", {}).get("weight") == "critical" else "mid"

    merchant = "unknown"
    if by_id.get("store_cnpj_inactive", {}).get("polarity") == "negative":
        merchant = "high"
    elif by_id.get("store_cnpj_active", {}).get("polarity") == "positive":
        merchant = "low"
    elif by_id.get("store_reachable", {}).get("polarity") == "positive":
        merchant = "mid"

    return {
        "identity_fraud": identity,
        "merchant": merchant,
        "friendly_fraud_residual": "low_mid",
        "rule_notes": [
            "Bandas derivadas de checks materiais (CPF, CEP, DJEN, loja) — não é score ML.",
            "Identidade baixa exige âncora DJEN no mesmo CPF e ao menos dois checks adicionais.",
            "Falha de captura da loja permanece unknown; não é evidência de risco do merchant.",
            "Friendly fraud residual sempre existe em cartão sem histórico de gateway.",
        ],
    }


def build_signals_from_facts(facts: dict[str, Any]) -> list[dict[str, Any]]:
    """Monta lista de signals a partir do dicionário de fatos coletados."""
    out: list[dict[str, Any]] = []
    buyer = facts.get("buyer") or {}
    cpf = facts.get("cpf") or {}
    cep = facts.get("cep") or {}
    phone = facts.get("phone") or {}
    dob = facts.get("dob") or {}
    djen = facts.get("djen") or {}
    store = facts.get("store") or {}
    ig = facts.get("ig") or {}

    # CPF
    if cpf.get("ok") is True:
        out.append(
            signal(
                id="cpf_valid",
                label="CPF com dígitos verificadores válidos",
                polarity="positive",
                detail=cpf.get("formatted") or "",
                weight="critical",
                evidence=cpf,
            )
        )
    elif buyer.get("cpf"):
        out.append(
            signal(
                id="cpf_valid",
                label="CPF inválido (dígitos)",
                polarity="negative",
                detail=cpf.get("reason") or "invalid",
                weight="critical",
                evidence=cpf,
            )
        )
    else:
        out.append(
            signal(
                id="cpf_valid",
                label="CPF não informado",
                polarity="gap",
                detail="Sem CPF não há âncora forte de identidade",
                weight="critical",
            )
        )

    # CEP / endereço
    addr_checks = cep.get("field_matches") or []
    matches = [c for c in addr_checks if c.get("match") is True]
    mismatches = [c for c in addr_checks if c.get("match") is False]
    if cep.get("api_ok") and matches and not mismatches:
        out.append(
            signal(
                id="cep_match",
                label="CEP e campos de endereço batem (ViaCEP)",
                polarity="positive",
                detail=f"CEP {cep.get('formatted')}: {', '.join(c['field'] for c in matches)}",
                weight="critical",
                evidence={"matches": matches, "via": cep.get("via")},
            )
        )
    elif mismatches:
        out.append(
            signal(
                id="cep_match",
                label="Divergência endereço × CEP",
                polarity="negative",
                detail="; ".join(f"{c['field']}: dado={c.get('given')!r} api={c.get('expected')!r}" for c in mismatches),
                weight="critical",
                evidence={"mismatches": mismatches, "via": cep.get("via")},
            )
        )
    elif buyer.get("cep"):
        out.append(
            signal(
                id="cep_match",
                label="CEP sem validação completa",
                polarity="gap",
                detail=cep.get("error") or "API indisponível ou campos insuficientes",
                weight="normal",
                evidence=cep,
            )
        )

    nr = cep.get("number_range") or {}
    if nr.get("ok") is True:
        out.append(
            signal(
                id="street_number_range",
                label="Número na faixa do logradouro (ViaCEP)",
                polarity="positive",
                detail=str(nr),
                weight="soft",
                evidence=nr,
            )
        )
    elif nr.get("ok") is False:
        out.append(
            signal(
                id="street_number_range",
                label="Número fora da faixa declarada do CEP",
                polarity="negative",
                detail=str(nr),
                weight="normal",
                evidence=nr,
            )
        )

    # Phone × CEP DDD
    via_ddd = str((cep.get("via") or {}).get("ddd") or "")
    if phone.get("ok") and via_ddd and phone.get("ddd") == via_ddd:
        out.append(
            signal(
                id="phone_ddd_match",
                label="DDD do telefone alinha ao CEP",
                polarity="positive",
                detail=f"DDD {phone.get('ddd')} = ViaCEP {via_ddd}",
                weight="normal",
                evidence={"phone": phone, "via_ddd": via_ddd},
            )
        )
    elif phone.get("ok") and via_ddd and phone.get("ddd") != via_ddd:
        out.append(
            signal(
                id="phone_ddd_match",
                label="DDD do telefone diverge do CEP",
                polarity="negative",
                detail=f"telefone {phone.get('ddd')} vs CEP {via_ddd}",
                weight="normal",
                evidence={"phone": phone, "via_ddd": via_ddd},
            )
        )
    elif buyer.get("phone"):
        out.append(
            signal(
                id="phone_ddd_match",
                label="Telefone não cruzado com DDD do CEP",
                polarity="gap",
                detail=phone.get("display") or buyer.get("phone") or "",
                weight="soft",
            )
        )

    # Email token
    tokens = name_tokens(buyer.get("name"))
    if buyer.get("email") and email_local_has_token(buyer.get("email"), tokens):
        hit = [t for t in tokens if t.casefold() in (buyer.get("email") or "").casefold()]
        out.append(
            signal(
                id="email_name_token",
                label="E-mail contém token do nome",
                polarity="positive",
                detail=f"{buyer.get('email')} ~ {hit}",
                weight="soft",
            )
        )
    elif buyer.get("email"):
        out.append(
            signal(
                id="email_name_token",
                label="E-mail sem token óbvio do nome",
                polarity="neutral",
                detail=buyer.get("email") or "",
                weight="soft",
            )
        )

    # DOB
    if dob.get("ok"):
        out.append(
            signal(
                id="dob_ok",
                label="Data de nascimento parseável",
                polarity="positive",
                detail=f"{dob.get('display')} (~{dob.get('age')} anos)",
                weight="soft",
                evidence=dob,
            )
        )

    # DJEN CPF anchor
    if djen.get("cpf_hits", 0) > 0:
        out.append(
            signal(
                id="djen_cpf_anchor",
                label="DJEN com âncora no mesmo CPF",
                polarity="positive",
                detail=(
                    f"{djen.get('cpf_hits')} comunicação(ões); "
                    f"processos≈{djen.get('unique_processos')}; "
                    f"tribunais={djen.get('by_tribunal')}"
                ),
                weight="critical",
                evidence={
                    "processos_sample": djen.get("processos_sample"),
                    "civil_name_hint": djen.get("civil_name_hint"),
                },
            )
        )
    elif buyer.get("cpf") and djen.get("queried"):
        out.append(
            signal(
                id="djen_cpf_anchor",
                label="DJEN sem comunicações para o CPF",
                polarity="neutral",
                detail="Ausência não prova inexistência de pessoa",
                weight="soft",
            )
        )
    elif buyer.get("cpf") and not djen.get("queried"):
        out.append(
            signal(
                id="djen_cpf_anchor",
                label="DJEN não consultado",
                polarity="gap",
                detail=djen.get("error") or "skip",
                weight="normal",
            )
        )

    if djen.get("civil_name_hint") and buyer.get("name"):
        bn = buyer.get("name") or ""
        cn = djen.get("civil_name_hint") or ""
        if bn.casefold() != cn.casefold() and all(t.casefold() in cn.casefold() for t in name_tokens(bn)[:2]):
            out.append(
                signal(
                    id="name_checkout_partial",
                    label="Nome no checkout incompleto vs autos",
                    polarity="negative",
                    detail=f"pedido={bn!r} · autos≈{cn!r}",
                    weight="soft",
                    evidence={"buyer_name": bn, "civil_name_hint": cn},
                )
            )

    # Store
    if store.get("reachable"):
        out.append(
            signal(
                id="store_reachable",
                label="Loja alcançável",
                polarity="positive",
                detail=store.get("title") or store.get("url") or "",
                weight="normal",
                evidence={"url": store.get("url"), "title": store.get("title")},
            )
        )
    elif store.get("url"):
        out.append(
            signal(
                id="store_reachable",
                label="Captura da loja inconclusiva",
                polarity="gap",
                detail=store.get("error") or store.get("url") or "",
                weight="normal",
            )
        )

    if store.get("cnpj_active"):
        out.append(
            signal(
                id="store_cnpj_active",
                label="CNPJ da loja ativo (CNPJá)",
                polarity="positive",
                detail=f"{store.get('company_name')} · {store.get('cnpj_formatted')} · {store.get('cnpj_status')}",
                weight="critical",
                evidence={
                    "cnpj": store.get("cnpj"),
                    "founded": store.get("founded"),
                    "alias": store.get("alias"),
                },
            )
        )
    elif store.get("cnpjs_found"):
        out.append(
            signal(
                id="store_cnpj_active",
                label="CNPJ encontrado mas não confirmado ativo",
                polarity="gap",
                detail=str(store.get("cnpjs_found")),
                weight="normal",
            )
        )

    if store.get("cnpj_inactive"):
        out.append(
            signal(
                id="store_cnpj_inactive",
                label="CNPJ da loja verificado como não ativo",
                polarity="negative",
                detail=f"{store.get('company_name')} · {store.get('cnpj_formatted')} · {store.get('cnpj_status')}",
                weight="critical",
                evidence={
                    "cnpj": store.get("cnpj"),
                    "status": store.get("cnpj_status"),
                },
            )
        )

    if store.get("domain_registered"):
        out.append(
            signal(
                id="store_domain",
                label="Domínio registrado (RDAP)",
                polarity="positive",
                detail=f"desde {store.get('domain_created')} · expira {store.get('domain_expires')}",
                weight="soft",
                evidence=store.get("rdap_events"),
            )
        )

    # IG
    if ig.get("handle") or ig.get("url"):
        if ig.get("display_name") or ig.get("handle"):
            out.append(
                signal(
                    id="ig_profile",
                    label="Perfil Instagram capturado",
                    polarity="positive" if ig.get("ok") else "gap",
                    detail=(
                        f"@{ig.get('handle') or '?'} · {ig.get('display_name') or ''} · "
                        f"privado={ig.get('private')} · link={ig.get('bio_link') or '—'}"
                    ),
                    weight="soft",
                    evidence=ig,
                )
            )

    # Payment gaps
    out.append(
        signal(
            id="payment_gaps",
            label="Dados de pagamento / device não avaliados",
            polarity="gap",
            detail="BIN, nome no cartão, AVS, CVV, IP, device, 3DS, valor — fora do escopo material desta tool",
            weight="normal",
        )
    )

    return out

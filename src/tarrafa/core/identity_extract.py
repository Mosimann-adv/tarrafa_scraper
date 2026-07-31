# -*- coding: utf-8 -*-
"""Material-only extraction of identity hints from free text (DJEN teores, PDFs).

No biography invention — only patterns present in the source text.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

# CPF with mask or digits
_CPF_RE = re.compile(
    r"\b(\d{3}\.?\d{3}\.?\d{3}-?\d{2})\b"
)
# CNJ masked or 20 digits
_CNJ_MASK_RE = re.compile(
    r"\b(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})\b"
)
_CNJ_DIGITS_RE = re.compile(r"\b(\d{20})\b")
# Email
_EMAIL_RE = re.compile(
    r"\b([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b"
)
# BR phones (loose)
_PHONE_RE = re.compile(
    r"(?:\+?55\s*)?(?:\(?\d{2}\)?\s*)?(?:9\s*)?\d{4,5}[.\-\s]?\d{4}\b"
)
# Instagram / social handles
_HANDLE_RE = re.compile(
    r"(?<![A-Za-z0-9_])@([A-Za-z0-9._]{2,30})\b"
)
# RG-ish (avoid swallowing CPF)
_RG_RE = re.compile(
    r"\bRG[:\s nº.]*(\d{1,3}(?:\.\d{3}){1,2}(?:-?\d|[A-Za-z])?|\d{5,12}(?:-?[A-Za-z0-9])?)"
    r"(?:\s*[-/]?\s*SSP\s*[/]?\s*([A-Z]{2}))?",
    re.I,
)
# Date of birth near keywords
_DN_RE = re.compile(
    r"(?:data\s+de\s+nascimento|nasc(?:imento)?\.?|DN)[:\s]*"
    r"(\d{1,2}[./]\d{1,2}[./]\d{2,4})",
    re.I,
)
# CEP
_CEP_RE = re.compile(r"\b(\d{5}-?\d{3})\b")
# Address lines (heuristic)
_ADDR_RE = re.compile(
    r"(?:(?:Rua|R\.|Avenida|Av\.|Alameda|Travessa|Tv\.|Rodovia|Rod\.|Servid[aã]o|SGAN|SQN|SQS|"
    r"Setor|Quadra|Pra[cç]a|P[cç]\.|Estrada|Est\.)\s+"
    r"[^\n,;]{5,90})"
    r"(?:,?\s*(?:n[ºo°.]?\s*)?\d[\w/\-]*)?"
    r"(?:,?\s*[^\n,;]{0,40})?"
    r"(?:,?\s*CEP\s*\d{5}-?\d{3})?",
    re.I,
)


def digits_only(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _format_11_digits(d: str) -> str:
    return f"{d[0:3]}.{d[3:6]}.{d[6:9]}-{d[9:11]}"


def validate_cpf(cpf: str | None) -> dict[str, Any]:
    """Valida os dígitos verificadores do CPF.

    Fonte única de verdade do projeto: qualquer tool que precise decidir se uma
    sequência de 11 dígitos é um CPF real deve usar esta função, e não apenas
    conferir o comprimento. Sem isso, número de protocolo, conta e guia viram
    "CPF encontrado".
    """
    d = digits_only(cpf)
    if len(d) != 11:
        return {"ok": False, "reason": "len", "digits": d, "formatted": cpf or ""}
    if re.fullmatch(r"(.)\1{10}", d):
        return {"ok": False, "reason": "repeated", "digits": d, "formatted": _format_11_digits(d)}
    nums = [int(c) for c in d]
    s = sum(nums[i] * (10 - i) for i in range(9))
    r = s % 11
    dv1 = 0 if r < 2 else 11 - r
    if nums[9] != dv1:
        return {"ok": False, "reason": "dv1", "digits": d, "formatted": _format_11_digits(d)}
    s = sum(nums[i] * (11 - i) for i in range(10))
    r = s % 11
    dv2 = 0 if r < 2 else 11 - r
    if nums[10] != dv2:
        return {"ok": False, "reason": "dv2", "digits": d, "formatted": _format_11_digits(d)}
    return {"ok": True, "reason": "valid", "digits": d, "formatted": _format_11_digits(d)}


def cpf_has_valid_dv(cpf: str | None) -> bool:
    """Atalho booleano sobre :func:`validate_cpf`."""
    return bool(validate_cpf(cpf)["ok"])


def format_cpf(digits: str) -> str | None:
    """Formata 11 dígitos como CPF. Formatador, não validador.

    Não confere dígito verificador de propósito: chamadores que precisam saber
    se o número é um CPF real usam :func:`validate_cpf`.
    """
    d = digits_only(digits)
    if len(d) != 11:
        return None
    # weak check: reject obvious invalids
    if d == d[0] * 11:
        return None
    return _format_11_digits(d)


def format_cnj(digits: str) -> str | None:
    d = digits_only(digits)
    if len(d) != 20:
        return None
    return f"{d[0:7]}-{d[7:9]}.{d[9:13]}.{d[13]}.{d[14:16]}.{d[16:20]}"


def format_cep(raw: str) -> str | None:
    d = digits_only(raw)
    if len(d) != 8:
        return None
    return f"{d[0:5]}-{d[5:8]}"


def _norm_phone(raw: str) -> str | None:
    d = digits_only(raw)
    if len(d) == 13 and d.startswith("55"):
        d = d[2:]
    if len(d) == 12 and d.startswith("55"):
        d = d[2:]
    if len(d) == 11:
        return f"({d[0:2]}) {d[2:7]}-{d[7:11]}"
    if len(d) == 10:
        return f"({d[0:2]}) {d[2:6]}-{d[6:10]}"
    if 8 <= len(d) <= 9:
        return d
    return None


def extract_identity_hints(text: str, *, max_each: int = 40) -> dict[str, Any]:
    """Extract structured identity/contact/process hints from free text."""
    if not text:
        return {
            "cpfs": [],
            "cpfs_rejected": [],
            "rgs": [],
            "datas_nascimento": [],
            "emails": [],
            "phones": [],
            "handles": [],
            "cnjs": [],
            "ceps": [],
            "addresses": [],
        }

    # Só entra em `cpfs` a sequência cujos dígitos verificadores fecham. As demais
    # ficam em `cpfs_rejected`: em autos, 11 dígitos seguidos costumam ser protocolo,
    # conta ou guia, e emiti-los como CPF gera conferência manual inútil.
    cpfs: list[str] = []
    cpfs_rejected: list[str] = []
    for m in _CPF_RE.finditer(text):
        fmt = format_cpf(m.group(1))
        if not fmt:
            continue
        if cpf_has_valid_dv(fmt):
            if fmt not in cpfs:
                cpfs.append(fmt)
        elif fmt not in cpfs_rejected:
            cpfs_rejected.append(fmt)
        if len(cpfs) >= max_each or len(cpfs_rejected) >= max_each:
            break

    rgs: list[str] = []
    for m in _RG_RE.finditer(text):
        rg = m.group(1).strip()
        uf = (m.group(2) or "").upper()
        # drop if this is actually a CPF
        if format_cpf(rg):
            continue
        label = f"{rg}-SSP/{uf}" if uf else rg
        if label not in rgs:
            rgs.append(label)
        if len(rgs) >= max_each:
            break

    dns: list[str] = []
    for m in _DN_RE.finditer(text):
        d = m.group(1).replace(".", "/")
        if d not in dns:
            dns.append(d)
        if len(dns) >= max_each:
            break

    emails: list[str] = []
    for m in _EMAIL_RE.finditer(text):
        e = m.group(1).lower()
        # skip obvious court/system noise lightly
        if e.endswith((".png", ".jpg", ".gif")):
            continue
        if e not in emails:
            emails.append(e)
        if len(emails) >= max_each:
            break

    phones: list[str] = []
    for m in _PHONE_RE.finditer(text):
        p = _norm_phone(m.group(0))
        if p and p not in phones:
            phones.append(p)
        if len(phones) >= max_each:
            break

    handles: list[str] = []
    for m in _HANDLE_RE.finditer(text):
        h = m.group(1).lower().rstrip(".")
        if h in ("gmail", "hotmail", "outlook", "yahoo", "uol"):
            continue
        if h not in handles:
            handles.append(h)
        if len(handles) >= max_each:
            break

    cnjs: list[str] = []
    for m in _CNJ_MASK_RE.finditer(text):
        fmt = format_cnj(m.group(1))
        if fmt and fmt not in cnjs:
            cnjs.append(fmt)
        if len(cnjs) >= max_each:
            break
    for m in _CNJ_DIGITS_RE.finditer(text):
        fmt = format_cnj(m.group(1))
        if fmt and fmt not in cnjs:
            cnjs.append(fmt)
        if len(cnjs) >= max_each:
            break

    ceps: list[str] = []
    for m in _CEP_RE.finditer(text):
        c = format_cep(m.group(1))
        if c and c not in ceps:
            ceps.append(c)
        if len(ceps) >= max_each:
            break

    addresses: list[str] = []
    for m in _ADDR_RE.finditer(text):
        a = re.sub(r"\s+", " ", m.group(0)).strip(" ,;")
        if len(a) < 12:
            continue
        if a not in addresses:
            addresses.append(a)
        if len(addresses) >= max_each:
            break

    return {
        "cpfs": cpfs,
        "cpfs_rejected": cpfs_rejected,
        "rgs": rgs,
        "datas_nascimento": dns,
        "emails": emails,
        "phones": phones,
        "handles": handles,
        "cnjs": cnjs,
        "ceps": ceps,
        "addresses": addresses,
    }


def merge_hints(hint_list: list[dict[str, Any]], *, max_each: int = 50) -> dict[str, Any]:
    """Merge multiple hint dicts; preserve first-seen order, count frequencies."""
    keys = (
        "cpfs",
        "cpfs_rejected",
        "rgs",
        "datas_nascimento",
        "emails",
        "phones",
        "handles",
        "cnjs",
        "ceps",
        "addresses",
    )
    ordered: dict[str, list[str]] = {k: [] for k in keys}
    counts: dict[str, Counter[str]] = {k: Counter() for k in keys}
    for h in hint_list:
        if not isinstance(h, dict):
            continue
        for k in keys:
            for v in h.get(k) or []:
                s = str(v).strip()
                if not s:
                    continue
                counts[k][s] += 1
                if s not in ordered[k]:
                    ordered[k].append(s)
    return {
        **{k: ordered[k][:max_each] for k in keys},
        "counts": {k: dict(counts[k].most_common(max_each)) for k in keys},
    }

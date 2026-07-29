# -*- coding: utf-8 -*-
"""Skill embutida: gera o arquivo de instruções da Tarrafa para hosts de IA.

O template vive em ``tarrafa/skills/tarrafa.md.tmpl`` e é versionado junto com o
código, então ele nunca descreve uma flag que não existe mais. Os caminhos são
resolvidos **na instalação**: a máquina de cada usuário tem um venv diferente, e
uma skill com caminho errado faz a IA cair em "command not found" e improvisar.
"""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

TEMPLATE_RESOURCE = "skills/tarrafa.md.tmpl"
SKILL_FILENAME = "SKILL.md"
SKILL_DIRNAME = "tarrafa"

# Marcador de arquivo gerado. Precisa ser inequívoco: só sobrescrevemos o que a
# própria Tarrafa escreveu, e uma skill escrita à mão pode perfeitamente citar o
# comando `tarrafa skills install` no corpo do texto sem ser gerada por ele.
GENERATED_MARKER = "<!-- tarrafa-skill:generated -->"

# Hosts que usam o formato "pasta de skills com SKILL.md" (frontmatter + markdown).
# Cada entrada: (chave, rótulo, variável de ambiente que sobrepõe o home, home padrão)
_HOST_SPECS: tuple[tuple[str, str, str | None, str], ...] = (
    ("claude", "Claude Code", "CLAUDE_CONFIG_DIR", ".claude"),
    ("grok", "Grok CLI", "GROK_CONFIG_DIR", ".grok"),
)


@dataclass
class Host:
    key: str
    label: str
    root: Path
    target: Path

    @property
    def detected(self) -> bool:
        """O host está instalado nesta máquina (a pasta de config existe)."""
        return self.root.is_dir()

    @property
    def installed(self) -> bool:
        return self.target.is_file()


def _home() -> Path:
    return Path.home()


def detect_hosts() -> list[Host]:
    """Lista os hosts conhecidos, detectados ou não.

    ``CLAUDE_CONFIG_DIR`` (e equivalentes) têm prioridade sobre ``~/.claude``:
    instalar no caminho padrão quando o usuário moveu a config grava a skill num
    lugar que o host nunca lê.
    """
    hosts: list[Host] = []
    for key, label, env_var, default_dirname in _HOST_SPECS:
        override = os.environ.get(env_var) if env_var else None
        root = Path(override).expanduser() if override else _home() / default_dirname
        target = root / "skills" / SKILL_DIRNAME / SKILL_FILENAME
        hosts.append(Host(key=key, label=label, root=root, target=target))
    return hosts


def resolve_bin() -> str:
    """Caminho absoluto do executável ``tarrafa`` desta instalação.

    Preferimos o console script que vive ao lado do interpretador em execução —
    é literalmente o ``tarrafa`` que está rodando agora, mesmo que o PATH aponte
    para outro. Só então caímos no PATH e, por fim, em ``-m tarrafa.cli``.
    """
    scripts_dir = Path(sys.executable).parent
    name = "tarrafa.exe" if os.name == "nt" else "tarrafa"
    candidate = scripts_dir / name
    if candidate.is_file():
        return str(candidate)

    on_path = shutil.which("tarrafa")
    if on_path:
        return str(Path(on_path).resolve())

    return f'"{sys.executable}" -m tarrafa.cli'


def source_repo() -> Path | None:
    """Raiz do checkout, quando rodando de um clone (instalação editável)."""
    try:
        root = Path(__file__).resolve().parents[3]
    except IndexError:
        return None
    if (root / "AGENTS.md").is_file() and (root / "pyproject.toml").is_file():
        return root
    return None


def _template_text() -> str:
    from importlib.resources import files

    return files("tarrafa").joinpath(TEMPLATE_RESOURCE).read_text(encoding="utf-8")


def _repo_section(repo: Path | None) -> str:
    if repo is None:
        return (
            "## Mais contexto\n\n"
            "Contrato completo e pipeline de perfil: "
            "<https://github.com/Mosimann-adv/tarrafa_scraper>."
        )
    lines = [
        "## Mais contexto",
        "",
        f"- Contrato completo: `{repo / 'AGENTS.md'}`",
        f"- Pipeline de perfil: `{repo / 'docs' / 'PROFILE_PIPELINE.md'}`",
    ]
    storage = repo / "storage_state.json"
    if storage.is_file():
        lines.append(f"- Sessão IG já salva: `{storage}`")
    stj_storage = repo / "stj_storage.json"
    if stj_storage.is_file():
        lines.append(f"- Sessão STJ já salva: `{stj_storage}`")
    return "\n".join(lines)


def render(*, shell: str = "auto", bin_path: str | None = None) -> str:
    """Preenche o template com os caminhos reais desta máquina."""
    from tarrafa import __version__

    if shell == "auto":
        shell = "powershell" if os.name == "nt" else "bash"
    if shell not in ("powershell", "bash"):
        raise ValueError(f"shell inválido: {shell!r} (use powershell, bash ou auto)")

    binary = bin_path or resolve_bin()
    repo = source_repo()

    if shell == "powershell":
        call = f'& "{binary}"' if not binary.startswith('"') else f"& {binary}"
        cont = "`"
        shell_label = "PowerShell"
        shell_note = (
            "Em bash/WSL na mesma máquina, troque o `& \"…\"` por "
            f'`"{binary}"` e a continuação de linha de `` ` `` para `\\`.'
        )
    else:
        call = binary if binary.startswith('"') else f'"{binary}"'
        cont = "\\"
        shell_label = "bash"
        shell_note = (
            "Em PowerShell na mesma máquina, prefixe a chamada com o operador `&` "
            "e use `` ` `` como continuação de linha."
        )

    storage_label = (
        "`--storage-state CAMINHO.json`, gravada antes com `--save-storage`"
    )

    values = {
        "TARRAFA_BIN": binary,
        "TARRAFA_CALL": call,
        "TARRAFA_CONT": cont,
        "TARRAFA_SHELL": shell,
        "TARRAFA_SHELL_LABEL": shell_label,
        "TARRAFA_SHELL_NOTE": shell_note,
        "TARRAFA_STORAGE_LABEL": storage_label,
        "TARRAFA_VERSION": __version__,
        "TARRAFA_REPO_SECTION": _repo_section(repo),
    }

    text = _template_text()
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)

    leftover = _unresolved(text)
    if leftover:
        raise RuntimeError(f"placeholders não resolvidos no template: {', '.join(leftover)}")
    return text


def _unresolved(text: str) -> list[str]:
    import re

    return sorted(set(re.findall(r"\{\{[A-Z_]+\}\}", text)))


def install(
    hosts: Iterable[Host],
    *,
    shell: str = "auto",
    force: bool = False,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Grava a skill renderizada em cada host. Não sobrescreve edição manual sem --force."""
    content = render(shell=shell)
    results: list[dict[str, Any]] = []

    for host in hosts:
        entry: dict[str, Any] = {
            "host": host.key,
            "label": host.label,
            "path": str(host.target),
        }
        current = _read(host.target)

        if current == content:
            entry["action"] = "unchanged"
        elif current is None:
            entry["action"] = "created"
        elif _is_generated(current) or force:
            entry["action"] = "updated"
        else:
            entry["action"] = "skipped"
            entry["reason"] = "arquivo não foi gerado pela Tarrafa; use --force para sobrescrever"

        if not dry_run and entry["action"] in ("created", "updated"):
            host.target.parent.mkdir(parents=True, exist_ok=True)
            host.target.write_text(content, encoding="utf-8")

        results.append(entry)

    return results


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _is_generated(text: str) -> bool:
    return GENERATED_MARKER in text


def status(*, shell: str = "auto") -> list[dict[str, Any]]:
    """Estado por host, para o ``doctor``: instalada, ausente ou desatualizada."""
    try:
        content = render(shell=shell)
    except Exception as exc:  # template quebrado não deve derrubar o doctor
        return [{"host": "-", "label": "skill", "state": "error", "detail": str(exc)}]

    out: list[dict[str, Any]] = []
    for host in detect_hosts():
        current = _read(host.target)
        if current is None:
            state = "missing"
        elif current == content:
            state = "current"
        elif _is_generated(current):
            state = "stale"
        else:
            state = "manual"
        out.append(
            {
                "host": host.key,
                "label": host.label,
                "detected": host.detected,
                "path": str(host.target),
                "state": state,
            }
        )
    return out

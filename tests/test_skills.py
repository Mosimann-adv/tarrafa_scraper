# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import pytest

from tarrafa.core import skills


def test_render_resolves_every_placeholder():
    text = skills.render(shell="bash")
    assert skills._unresolved(text) == []


def test_render_embeds_absolute_binary_path():
    """O ponto da skill gerada: o caminho tem que ser o desta instalação."""
    text = skills.render(shell="bash")
    assert skills.resolve_bin() in text


def test_render_shell_syntax_differs():
    ps = skills.render(shell="powershell")
    sh = skills.render(shell="bash")
    assert ps.startswith("---")
    assert "```powershell" in ps
    assert "```bash" in sh
    # continuação de linha correta para cada shell
    assert " `\n" in ps
    assert " \\\n" in sh


def test_render_rejects_unknown_shell():
    with pytest.raises(ValueError):
        skills.render(shell="fish")


def test_frontmatter_has_name_and_description():
    text = skills.render(shell="bash")
    head = text.split("---")[1]
    assert "name: tarrafa" in head
    assert "description:" in head


def test_detect_hosts_honours_config_env(monkeypatch, tmp_path):
    """CLAUDE_CONFIG_DIR movido: instalar em ~/.claude gravaria onde ninguém lê."""
    custom = tmp_path / "config-alternativa"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(custom))
    claude = next(h for h in skills.detect_hosts() if h.key == "claude")
    assert claude.root == custom
    assert claude.target == custom / "skills" / "tarrafa" / "SKILL.md"


def test_detect_hosts_falls_back_to_home(monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    claude = next(h for h in skills.detect_hosts() if h.key == "claude")
    assert claude.root == Path.home() / ".claude"


def _host(tmp_path: Path) -> skills.Host:
    root = tmp_path / "host"
    return skills.Host(
        key="teste",
        label="Host de teste",
        root=root,
        target=root / "skills" / "tarrafa" / "SKILL.md",
    )


def test_install_creates_then_reports_unchanged(tmp_path):
    host = _host(tmp_path)

    first = skills.install([host], shell="bash")
    assert first[0]["action"] == "created"
    assert host.target.is_file()

    second = skills.install([host], shell="bash")
    assert second[0]["action"] == "unchanged"


def test_install_updates_its_own_stale_file(tmp_path):
    host = _host(tmp_path)
    host.target.parent.mkdir(parents=True)
    host.target.write_text(
        f"{skills.GENERATED_MARKER}\nversão 0.0.1\nconteúdo velho\n",
        encoding="utf-8",
    )

    result = skills.install([host], shell="bash")
    assert result[0]["action"] == "updated"
    assert "conteúdo velho" not in host.target.read_text(encoding="utf-8")


def test_mentioning_the_command_does_not_mark_a_file_as_generated(tmp_path):
    """Skill escrita à mão pode citar `tarrafa skills install` sem virar sobrescrevível."""
    host = _host(tmp_path)
    host.target.parent.mkdir(parents=True)
    original = "Minha skill.\nPara atualizar rode `tarrafa skills install`.\n"
    host.target.write_text(original, encoding="utf-8")

    result = skills.install([host], shell="bash")
    assert result[0]["action"] == "skipped"
    assert host.target.read_text(encoding="utf-8") == original


def test_generated_output_carries_the_marker():
    """O marcador vem depois do frontmatter: `---` precisa abrir o arquivo."""
    text = skills.render(shell="bash")
    assert text.startswith("---")
    assert skills.GENERATED_MARKER in text
    assert skills._is_generated(text)


def test_install_preserves_handwritten_file(tmp_path):
    """A skill que o usuário escreveu à mão não pode ser sobrescrita em silêncio."""
    host = _host(tmp_path)
    host.target.parent.mkdir(parents=True)
    host.target.write_text("skill escrita à mão\n", encoding="utf-8")

    result = skills.install([host], shell="bash")
    assert result[0]["action"] == "skipped"
    assert host.target.read_text(encoding="utf-8") == "skill escrita à mão\n"

    forced = skills.install([host], shell="bash", force=True)
    assert forced[0]["action"] == "updated"
    assert "name: tarrafa" in host.target.read_text(encoding="utf-8")


def test_install_dry_run_writes_nothing(tmp_path):
    host = _host(tmp_path)
    result = skills.install([host], shell="bash", dry_run=True)
    assert result[0]["action"] == "created"
    assert not host.target.exists()


def test_status_reports_states(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("GROK_CONFIG_DIR", str(tmp_path / "grok"))

    before = {r["host"]: r["state"] for r in skills.status(shell="bash")}
    assert before["claude"] == "missing"

    claude = next(h for h in skills.detect_hosts() if h.key == "claude")
    skills.install([claude], shell="bash")

    after = {r["host"]: r["state"] for r in skills.status(shell="bash")}
    assert after["claude"] == "current"


def test_dest_alone_does_not_touch_detected_hosts(tmp_path, monkeypatch):
    """--dest sozinho não pode gravar na config global do usuário por tabela."""
    from tarrafa.cli import main

    claude_root = tmp_path / "claude"
    grok_root = tmp_path / "grok"
    claude_root.mkdir()
    grok_root.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_root))
    monkeypatch.setenv("GROK_CONFIG_DIR", str(grok_root))

    dest = tmp_path / "dest"
    assert main(["skills", "install", "--dest", str(dest)]) == 0

    assert (dest / "tarrafa" / "SKILL.md").is_file()
    assert not (claude_root / "skills" / "tarrafa" / "SKILL.md").exists()
    assert not (grok_root / "skills" / "tarrafa" / "SKILL.md").exists()


def test_dest_with_all_also_writes_hosts(tmp_path, monkeypatch):
    from tarrafa.cli import main

    claude_root = tmp_path / "claude"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_root))
    monkeypatch.setenv("GROK_CONFIG_DIR", str(tmp_path / "grok"))

    dest = tmp_path / "dest"
    assert main(["skills", "install", "--dest", str(dest), "--all"]) == 0

    assert (dest / "tarrafa" / "SKILL.md").is_file()
    assert (claude_root / "skills" / "tarrafa" / "SKILL.md").is_file()


def test_provider_path_stays_documented_but_optional():
    """Quem tem chave continua podendo buscar no CLI; quem não tem não é bloqueado."""
    text = skills.render(shell="bash")
    section = text.split("## Antes de capturar")[1].split("## Tools")[0]
    assert "search" in section
    assert "--queries-file" in section
    assert "BRAVE_SEARCH_API_KEY" in section
    assert "Provedor próprio é opcional" in section


def test_skill_documents_deep_profile_discovery():
    text = skills.render(shell="bash")
    section = text.split("## Antes de capturar")[1].split("## Tools")[0]
    assert "profile --name" in section
    assert "queries_followup.txt" in section
    assert "sitemap" in section
    assert "nunca aceita CPF, e-mail ou telefone" in section


def test_public_docs_keep_search_providers_optional():
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    env_example = (root / ".env.example").read_text(encoding="utf-8")

    assert "--from-agent" in readme
    assert "Opcionais; apenas para busca executada dentro do CLI" in readme
    assert "Ao menos um para descoberta" not in readme
    assert "Provedores opcionais" in env_example
    assert "Configure ao menos um provedor" not in env_example


def test_skill_documents_verified_flag_behaviour():
    """page não define --headed; a skill não pode sugerir o contrário."""
    text = skills.render(shell="bash")
    assert "`page` não aceita `--headed`" in text


def test_skill_tells_ai_to_search_instead_of_asking_for_setup():
    """A instrução tem que mandar a IA buscar, não pedir configuração ao usuário.

    Sem isso a IA trava pedindo Brave/SearXNG, que quase ninguém tem.
    """
    text = skills.render(shell="bash")
    secao = text.split("## Antes de capturar")[1].split("## Tools")[0]
    assert "Busque você mesmo" in secao
    assert "não peça ao usuário" in secao.lower()
    assert "--from-agent" in secao
    assert "URLs descartadas e motivos" in secao
    assert "opcional" in secao


def test_skill_forbids_inventing_search_results():
    text = skills.render(shell="bash")
    secao = text.split("## Antes de capturar")[1].split("## Tools")[0]
    assert "Nunca invente handle, URL ou resultado" in secao
    assert "candidato, não fato" in secao

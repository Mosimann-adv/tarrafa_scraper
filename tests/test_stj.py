# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from tarrafa.cli import main as cli_main
from tarrafa.core.challenge import is_challenge_page, is_pdf_bytes
from tarrafa.tools.stj.scraper import (
    EX_ARGS,
    build_inteiro_teor_url,
    dt_to_publicacao_data,
    extract_documento_links,
    load_seeds,
    normalize_dt_publicacao,
    parse_seed_line,
    pdf_stem,
    pick_documento_link,
)


def test_cli_list_includes_stj(capsys):
    assert cli_main(["list"]) == 0
    assert "stj" in capsys.readouterr().out


def test_normalize_dt_publicacao():
    assert normalize_dt_publicacao("23/08/2019") == "23/08/2019"
    assert normalize_dt_publicacao("2019-08-23") == "23/08/2019"
    assert normalize_dt_publicacao("3/8/2019") == "03/08/2019"


def test_build_inteiro_teor_url():
    u = build_inteiro_teor_url("201600461292", "23/08/2019")
    assert "scon.stj.jus.br" in u
    assert "GetInteiroTeorDoAcordao" in u
    assert "num_registro=201600461292" in u
    assert "dt_publicacao=23%2F08%2F2019" in u or "dt_publicacao=23/08/2019" in u


def test_parse_seed_line_pipe_and_url():
    s = parse_seed_line("201600461292|23/08/2019")
    assert s is not None
    assert s["num_registro"] == "201600461292"
    assert "GetInteiroTeor" in s["url"]

    s2 = parse_seed_line(
        "https://scon.stj.jus.br/SCON/GetInteiroTeorDoAcordao?"
        "num_registro=201600461292&dt_publicacao=23/08/2019"
    )
    assert s2 is not None
    assert s2["num_registro"] == "201600461292"

    assert parse_seed_line("# comment") is None
    assert parse_seed_line("") is None


def test_load_seeds_dedupe(tmp_path: Path):
    f = tmp_path / "seeds.txt"
    f.write_text(
        "201600461292|23/08/2019\n"
        "201600461292|23/08/2019\n"
        "# ignore\n"
        "201902668550 04/06/2020\n",
        encoding="utf-8",
    )
    seeds = load_seeds(urls_file=f)
    assert len(seeds) == 2


def test_pdf_stem():
    assert pdf_stem({"num_registro": "123", "dt_publicacao": "01/02/2020"}) == "stj-123-01-02-2020"


def test_is_pdf_bytes():
    assert is_pdf_bytes(b"%PDF-1.4\n...")
    assert not is_pdf_bytes(b"<html>")
    assert not is_pdf_bytes(b"")


def test_is_challenge_page():
    assert is_challenge_page(title="Just a moment...", html="<html>cf</html>", status=403)
    assert is_challenge_page(
        title="x",
        html="cdn-cgi/challenge-platform/h/g/orchestrate",
        status=403,
        headers={"server": "cloudflare"},
    )
    assert is_challenge_page(
        title="",
        text="Verificação automática em andamento. Coordenadoria de Segurança e Defesa Cibernética",
        status=403,
    )
    assert not is_challenge_page(
        title="Acórdão",
        html="<html><body>APELAÇÃO CÍVEL art. 944</body></html>",
        status=200,
    )


def test_stj_main_requires_seeds(capsys):
    code = cli_main(["stj"])
    assert code == EX_ARGS


def test_stj_warmup_requires_save_storage():
    code = cli_main(["stj", "--warmup", "--headed"])
    assert code == EX_ARGS


def test_extract_and_pick_documento_links():
    html = """
    <a href="https://processo.stj.jus.br/processo/julgamento/eletronico/documento/?documento_tipo=integra&amp;documento_sequencial=116943792&amp;registro_numero=201902673936&amp;peticao_numero=202000335179&amp;publicacao_data=20201029&amp;O=JT">x</a>
    <a href="https://processo.stj.jus.br/processo/julgamento/eletronico/documento/?documento_tipo=integra&documento_sequencial=1&registro_numero=201600461292&publicacao_data=20190823&O=JT">y</a>
    """
    links = extract_documento_links(html)
    assert len(links) == 2
    assert all("processo.stj.jus.br" in u for u in links)
    assert "&amp;" not in links[0]
    picked = pick_documento_link(
        links, num_registro="201902673936", dt_publicacao="29/10/2020"
    )
    assert picked is not None
    assert "201902673936" in picked
    assert "20201029" in picked
    assert dt_to_publicacao_data("29/10/2020") == "20201029"

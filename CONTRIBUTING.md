# Contribuindo com o Tarrafa

Obrigado pelo interesse em melhorar o Tarrafa. O projeto é experimental,
source-available e distribuído sob a PolyForm Noncommercial 1.0.0.

## Antes de abrir uma issue

- Não publique dados de caso, documentos de autos, CPF, CNJ sensível, tokens,
  cookies, `.env` ou `storage_state.json`.
- Reproduza o problema com fixture sintética ou URL pública não sensível.
- Consulte `SECURITY.md` para vulnerabilidades exploráveis no próprio código.

## Ambiente de desenvolvimento

```bash
git clone https://github.com/Mosimann-adv/tarrafa_scraper.git
cd tarrafa_scraper
python -m venv .venv

# Windows
.\.venv\Scripts\Activate.ps1

# macOS / Linux
# source .venv/bin/activate

python -m pip install -e ".[dev]"
python -m playwright install chromium
```

## Verificações

```bash
ruff check src tests
pytest -q -m "not integration"
pytest -q -m integration  # acessa rede e Chromium
python -m build
python -m twine check dist/*
```

## Alterações

- Use português do Brasil (pt-BR) na comunicação, documentação, mensagens visíveis da
  CLI, issues, pull requests e mensagens de commit.
- Mantenha identificadores de código, APIs, flags e termos técnicos consolidados em
  inglês quando necessário para compatibilidade ou clareza.
- Mantenha commits pequenos e descritivos.
- Inclua teste para correções e comportamento novo.
- Atualize README/CHANGELOG quando a interface pública mudar.
- Preserve compatibilidade com Python 3.10+ e Windows.
- Não introduza dependência de um produto de IA, IDE ou vault específico.

Para adicionar uma nova tool, siga [`docs/ADDING_TOOLS.md`](docs/ADDING_TOOLS.md).

Ao participar, você concorda com o [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).

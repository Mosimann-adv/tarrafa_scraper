# Tarrafa

[![License: PolyForm Noncommercial](https://img.shields.io/badge/License-PolyForm%20Noncommercial-blue.svg)](LICENSE)
[![Status: Experimental](https://img.shields.io/badge/status-experimental-orange.svg)](SECURITY.md)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![CI](https://github.com/Mosimann-adv/tarrafa_scraper/actions/workflows/ci.yml/badge.svg)](https://github.com/Mosimann-adv/tarrafa_scraper/actions/workflows/ci.yml)
[![CodeQL](https://github.com/Mosimann-adv/tarrafa_scraper/actions/workflows/codeql.yml/badge.svg)](https://github.com/Mosimann-adv/tarrafa_scraper/actions/workflows/codeql.yml)
[![Release](https://img.shields.io/github/v/release/Mosimann-adv/tarrafa_scraper?include_prereleases)](https://github.com/Mosimann-adv/tarrafa_scraper/releases)

![Joga a rede. Puxa a prova.](assets/hero.jpg)

**Joga a rede. Puxa a prova.**

A Tarrafa é uma ferramenta de linha de comando para descobrir, capturar e organizar
material público da web. Ela reúne páginas, prints, sites, feeds, vídeos, Instagram,
CNPJ, DJEN, Datajud, decisões do STJ e PDFs em arquivos verificáveis.

Foi criada para pesquisa e documentação jurídica experimental. Não produz conclusões
jurídicas sozinha, não substitui conferência humana e não depende de uma IA específica.

## Inventário interno, não prova com cadeia de custódia

A Tarrafa serve para criar um inventário interno de materiais públicos: localizar fontes,
registrar URLs, horários, metadados e hashes, e organizar capturas para conferência. Esse
inventário ajuda a documentar o que foi encontrado, mas não substitui a obtenção formal da
prova nem a preservação por cadeia de custódia própria, adequada ao caso e à jurisdição
aplicável.

Quando o material puder ser usado em processo, obtenha e preserve a fonte original por
procedimento independente, documentando quem coletou, quando, como, onde e eventuais
transferências ou alterações. Confirme a autenticidade e a integridade conforme a orientação
profissional aplicável.

> **Projeto experimental, não um produto acabado.**
>
> Sites e APIs mudam; coletores podem quebrar; resultados precisam ser conferidos antes
> de uso como prova. Não há SLA nem garantia de adequação a um caso concreto. A licença
> [PolyForm Noncommercial 1.0.0](LICENSE) exige atribuição e não permite uso comercial
> sem autorização separada.

## Escolha o que você quer fazer

| Objetivo | Comece por | Resultado principal |
|----------|------------|---------------------|
| Pesquisar uma pessoa, seu site, artigos e Instagram | `tarrafa profile` | `profile.json` + `profile.html` |
| Salvar o conteúdo de uma página | `tarrafa page` | JSON com texto, links e fatos extraídos |
| Tirar um print verificável | `tarrafa shot` | PNG + JSON de metadados |
| Descobrir URLs na web | `tarrafa search` | Candidatos para conferência |
| Percorrer um site ou feed | `tarrafa site` / `tarrafa feed` | Inventário de páginas ou publicações |
| Coletar perfil ou comentários do Instagram | `tarrafa ig` | Inventário, print ou comentários com permalink |
| Consultar fontes jurídicas | `tarrafa djen`, `datajud`, `stj` | Comunicações, processos e PDFs |
| Consultar empresa | `tarrafa cnpj` | Dados públicos do CNPJ |
| Extrair texto de PDFs | `tarrafa pdf-extract` | Texto e indícios de identidade |
| Montar uma ficha visual | `tarrafa dossier` | HTML autocontido |
| Organizar prints e frames | `tarrafa album` | Álbum HTML pronto para imprimir |

Se você usa uma IA com acesso ao terminal, pode descrever o objetivo em linguagem comum.
Dentro deste repositório, ela deve ler o [`AGENTS.md`](AGENTS.md) e usar o CLI existente
em vez de improvisar outro scraper.

## Como a Tarrafa funciona

O fluxo normal tem três etapas:

1. Você informa uma URL, nome, número de processo ou outro dado de entrada.
2. A Tarrafa consulta a fonte e grava os artefatos na pasta escolhida.
3. Você ou uma IA confere o JSON, o HTML, os prints e as fontes originais.

A ferramenta distingue:

- resultado encontrado;
- lacuna ou ausência de resultado;
- erro de coleta;
- candidato ainda não confirmado.

Ela não transforma automaticamente semelhança de nome, resultado de busca ou máscara de
documento em identidade confirmada.

## Instalação

### Caminho recomendado: peça para uma IA instalar

Use uma IA que consiga ler arquivos e executar comandos no seu computador. Abra a IA na
pasta onde deseja guardar o projeto e envie:

```text
Quero instalar a Tarrafa para uso não comercial.

Repositório:
https://github.com/Mosimann-adv/tarrafa_scraper

Verifique se Git e Python 3.10 ou superior estão instalados. Depois:
1. clone o repositório;
2. leia o AGENTS.md;
3. crie o ambiente virtual .venv;
4. instale o projeto e o Chromium do Playwright;
5. execute tarrafa doctor e tarrafa list.

Não solicite nem digite minhas senhas. Não automatize login do Facebook ou recuperação
de senha. Ao final, informe a pasta instalada, os comandos executados e eventuais erros.
```

### Instalação manual no Windows

Instale primeiro [Python 3.10 ou superior](https://www.python.org/downloads/) e
[Git](https://git-scm.com/downloads). Depois abra o PowerShell na pasta desejada:

```powershell
git clone https://github.com/Mosimann-adv/tarrafa_scraper.git
cd tarrafa_scraper
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\tarrafa.exe doctor
.\.venv\Scripts\tarrafa.exe list
```

Não é necessário ativar o ambiente virtual: os comandos acima chamam os executáveis
diretamente. Se `py` não existir, tente `python -m venv .venv`.

### macOS ou Linux

```bash
git clone https://github.com/Mosimann-adv/tarrafa_scraper.git
cd tarrafa_scraper
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install .
./.venv/bin/python -m playwright install chromium
./.venv/bin/tarrafa doctor
./.venv/bin/tarrafa list
```

Com o ambiente virtual ativado ou a Tarrafa instalada no sistema, use simplesmente
`tarrafa`. Nos demais exemplos deste documento, esse é o formato adotado.

## Primeira coleta em dois minutos

Capture uma página pública:

```bash
tarrafa page \
  --url "https://example.com" \
  --out "./minha-primeira-coleta/pagina.json"
```

Tire também um print:

```bash
tarrafa shot \
  --url "https://example.com" \
  --out-dir "./minha-primeira-coleta/shots" \
  --id PAGINA01 --full-page --dpr 2
```

Ao terminar, a pasta terá o conteúdo estruturado em JSON, a imagem em PNG e metadados da
captura. Veja também um [JSON de exemplo](examples/page_capture.example.json).

Para evitar sobrescrever arquivos existentes, coloque `--no-clobber` antes da ferramenta:

```bash
tarrafa --no-clobber page --url "https://example.com" --out "./pagina.json"
```

## Usando com uma IA

Um pedido eficaz informa objetivo, entradas, pasta de saída e limites:

```text
Leia o AGENTS.md e use o CLI da Tarrafa disponível nesta pasta.

Objetivo:
Capture o conteúdo e um print da página indicada.

Entrada:
https://example.com

Pasta de saída:
./minha-pesquisa

Não invente dados, não escreva outro scraper e não sobrescreva arquivos existentes.
Ao final, informe os comandos, exit codes, arquivos, contagens, erros e limitações.
```

Fora deste repositório, instale a skill da Tarrafa para que a IA encontre o executável e
conheça as regras da versão instalada:

```bash
tarrafa skills list
tarrafa skills install --dry-run
tarrafa skills install
```

O instalador reconhece hosts compatíveis e não substitui silenciosamente uma skill escrita
à mão. `tarrafa skills show` imprime o conteúdo para instalação manual.

## Fluxos principais

### Perfil público aprofundado

`profile` combina descoberta web, leitura de páginas, expansão de site próprio, inventário
de artigos e cobertura específica do Instagram. O resultado visual é gerado por padrão.

```bash
tarrafa profile \
  --name "Marina Alves" \
  --handle "@marinaalves" \
  --profession "arquiteta" \
  --keyword "urbanismo" \
  --from-agent "./repasse.json" \
  --out-dir "./perfil"
```

Sem Brave ou SearXNG configurado, a IA faz a descoberta com as ferramentas disponíveis no
ambiente e registra os resultados em `repasse.json`. Isso é normal: provedor próprio de
busca é opcional.

O fluxo:

1. diversifica consultas por nome, handle, função, local e temas;
2. ranqueia candidatos sem tratá-los como identidade confirmada;
3. abre páginas e procura domínio profissional, sitemap, blog e artigos;
4. havendo handle ou perfil candidato, chama `tarrafa ig`;
5. registra separadamente `instagram_profile` e `instagram_posts`;
6. gera `profile.json` e `profile.html`.

LinkedIn ou outra rede social não substitui a cobertura do Instagram. Login wall,
hidratação incompleta ou sessão expirada permanecem como lacuna explícita. Use
`--no-instagram` ou `--no-html` somente quando isso for intencional.

O playbook detalhado está em [`docs/PROFILE_PIPELINE.md`](docs/PROFILE_PIPELINE.md).

### Descoberta web

Com Brave ou SearXNG já configurado:

```bash
tarrafa search \
  --query "\"Nome Completo\" cidade" \
  --max-results 30 \
  --urls-out "./out/urls.txt" \
  --out "./out/search.json"
```

Sem provedor, registre a busca feita pela IA:

```bash
tarrafa search \
  --from-agent "./repasse.json" \
  --urls-out "./out/urls.txt" \
  --out "./out/search.json"
```

`search` descobre candidatos; não confirma identidade. CPF, e-mail e telefone são
bloqueados como consultas, salvo decisão explícita com `--allow-sensitive-query`.

### Página, site e feed

```bash
tarrafa page --url "URL" --out "./pagina.json"
tarrafa page --urls-file "./urls.txt" --out "./paginas/"

tarrafa site \
  --url "https://example.com" \
  --out "./site.json" \
  --max-pages 15 --max-depth 2

tarrafa feed \
  --url "https://example.com/feed.xml" \
  --out "./feed.json" --max-entries 20
```

### Screenshot e álbum

```bash
# página inteira
tarrafa shot \
  --url "URL" --out-dir "./shots" --id PAGINA01 \
  --full-page --dpr 2

# conteúdo principal
tarrafa shot \
  --url "URL" --out-dir "./shots" --id PAGINA02 \
  --clip main --dpr 2

# álbum autocontido
tarrafa album \
  --dir "./shots" \
  --out "./shots/album.html" \
  --title "Inventário visual"
```

### Instagram

O caminho canônico é o CLI com Playwright embutido. A extensão MCP do Playwright não é
necessária para as coletas.

Primeiro, se necessário, faça login nativo manualmente e salve a sessão:

```bash
tarrafa ig \
  --url "https://www.instagram.com/accounts/login/" \
  --out "./login.json" \
  --headed --max-comments 0 \
  --save-storage "./storage_state.json"
```

Nunca automatize senha, login pelo Facebook ou recuperação de conta.

Inventarie um perfil:

```bash
tarrafa ig \
  --url "https://www.instagram.com/HANDLE/" \
  --out "./instagram/profile.json" \
  --profile-shot "./instagram/profile.png" \
  --storage-state "./storage_state.json"
```

Colete comentários de um post ou reel:

```bash
tarrafa ig \
  --url "https://www.instagram.com/p/SHORTCODE/" \
  --out "./instagram/comentarios.json" \
  --storage-state "./storage_state.json" \
  --expand-replies --max-comments 500
```

### CNPJ e fontes judiciais

```bash
# empresa
tarrafa cnpj \
  --cnpj "00.000.000/0001-91" \
  --out "./cnpj.json"

# advogado no DJEN
tarrafa djen \
  --oab 12345 --uf SP --max-items 100 \
  --out "./djen_advogado.json"

# parte: CPF tem prioridade e conferência exata local
tarrafa djen \
  --papel parte --cpf "000.000.000-00" \
  --max-items 50 --out "./djen_parte.json"

# parte sem CPF
tarrafa djen \
  --papel parte --nome "Nome Completo" \
  --max-items 50 --out "./djen_nome.json"

# processo conhecido
tarrafa datajud \
  --cnj "0000000-00.0000.0.00.0000" \
  --out "./datajud.json"

# texto e indícios extraídos de PDFs
tarrafa pdf-extract \
  --dir "./pdfs" --recursive \
  --out "./pdf_extract.json"
```

`datajud` deve receber CNJs conhecidos; o índice normalmente não contém nomes de partes.
Resultados por nome curto, máscaras de CPF/CNPJ e indícios extraídos de PDF exigem
conferência antes de qualquer associação.

Para decisões do STJ, o SCON pode exigir desafio Cloudflare:

```bash
tarrafa stj --warmup --headed --save-storage "./stj_storage.json"

tarrafa stj \
  --num-registro 201600461292 \
  --dt-publicacao 23/08/2019 \
  --storage-state "./stj_storage.json" \
  --out-dir "./stj_pdfs" \
  --out "./stj.json" --extract
```

### Vídeo

```bash
tarrafa video \
  --url "URL" \
  --out-dir "./video" \
  --id VID01 --frames 5

# download opcional; requer yt-dlp
tarrafa video \
  --url "URL" \
  --out-dir "./video" \
  --id VID01 --download --frames 5
```

`ffmpeg` é necessário para alguns fluxos de frames. `tarrafa doctor` informa se as
dependências opcionais estão disponíveis.

### Ficha HTML

`dossier` apenas renderiza os dados fornecidos; não pesquisa nem inventa biografia:

```bash
tarrafa dossier \
  --title "Nome do perfil" \
  --out "./perfil.html" \
  --meta "Área: arquitetura" \
  --fact "Achado com fonte citada" \
  --source "Site profissional | https://example.com | candidato" \
  --gap "Vínculo ainda não confirmado"
```

## Ferramentas disponíveis

| Ferramenta | Função |
|------------|--------|
| `init` | Cria um workspace opcional |
| `doctor` | Verifica instalação, navegadores, sessões e dependências |
| `skills` | Ensina a Tarrafa a hosts de IA compatíveis |
| `search` | Descobre URLs candidatas |
| `profile` | Aprofunda perfil, sites, artigos e Instagram |
| `page` | Captura uma ou várias páginas |
| `site` | Percorre páginas do mesmo site |
| `feed` | Inventaria RSS ou Atom |
| `shot` | Gera screenshot e metadados |
| `video` | Extrai metadados, frames e download opcional |
| `ig` | Inventaria perfil ou coleta comentários do Instagram |
| `cnpj` | Consulta a API pública CNPJá |
| `djen` | Pesquisa comunicações no DJEN |
| `datajud` | Consulta capa e movimentos por CNJ |
| `stj` | Baixa inteiro teor do SCON/STJ |
| `pdf-extract` | Extrai texto e indícios de PDFs |
| `order-risk` | Faz triagem material de pedido e-commerce |
| `album` | Compila imagens em HTML de impressão |
| `dossier` | Renderiza ficha HTML de perfil |

Use `tarrafa list` para a lista instalada e `tarrafa FERRAMENTA --help` para todas as
flags de uma ferramenta.

## Arquivos produzidos

| Formato | Conteúdo | Como abrir |
|---------|----------|------------|
| `.json` | Dados, fontes, horários, erros e notas | Editor de texto ou IA |
| `.png` | Print da página ou frame | Visualizador de imagens |
| `.html` | Perfil, ficha ou álbum autocontido | Navegador; pode imprimir em PDF |
| `.pdf` | Documento baixado da fonte | Leitor de PDF |
| `.ndjson` | Checkpoints incrementais | Editor ou ferramenta de dados |

O envelope JSON comum contém:

```text
tool, version, collected_at, source, meta, count, items[], errors[], notes[]
```

Capturas podem registrar SHA-256 para permitir a conferência posterior do arquivo.

## Workspaces e configuração

Um workspace organiza resultados, mas não é obrigatório:

```bash
tarrafa init "./meu-caso" --name "Pesquisa exemplo"
```

Estrutura criada:

```text
meu-caso/
  tarrafa.toml
  raw/
  shots/
  html/
  logs/
  meta/runs/
```

As configurações seguem esta precedência:

```text
flags → variáveis TARRAFA_* → ./tarrafa.toml → ~/.tarrafa/config.toml
```

Flags globais vêm antes da ferramenta:

```text
-v
--quiet
--force
--no-clobber
--timeout SEGUNDOS
--out-dir DIRETÓRIO
--workspace DIRETÓRIO
--json-logs
```

Exemplo:

```bash
tarrafa --workspace "./meu-caso" --timeout 60 page \
  --url "https://example.com" \
  --out "./meu-caso/raw/pagina.json"
```

Variáveis e segredos locais:

| Arquivo/variável | Uso |
|------------------|-----|
| `~/.tarrafa/.env` | Configuração preferida do usuário |
| `<repo>/.env` | Configuração local do projeto |
| `BRAVE_SEARCH_API_KEY` | Busca Brave opcional |
| `SEARXNG_URL` | Busca SearXNG opcional |
| `storage_state.json` | Sessão local do Instagram |

Brave e SearXNG são **Opcionais; apenas para busca executada dentro do CLI**. Sem eles,
a descoberta pode ser feita pela IA e registrada com `--from-agent`.

O CLI carrega o `.env`, mas não sobrescreve variáveis já definidas no processo.
`.env` e `storage_state.json` são ignorados pelo Git.

## Segurança e limites

- Nunca publique `.env`, `storage_state.json`, cookies, tokens ou credenciais.
- Nunca cole senhas em prompts, comandos ou issues.
- Não automatize Facebook OIDC, recuperação de senha ou captcha.
- Grave os artefatos na pasta do caso e reporte exit codes e erros.
- Use `--no-clobber` quando quiser impedir sobrescrita.
- Busca por nome ou handle produz candidatos, não confirmação de identidade.
- `profile` e `search` não devem usar CPF, e-mail ou telefone para ampliar exposição.
- Não associe processo, empresa ou perfil por nome curto ou máscara incompatível.
- Confira as fontes antes de usar qualquer resultado em peça, relatório ou prova.
- Não embuta print de login wall em ficha ou dossiê.

Consulte [`SECURITY.md`](SECURITY.md) antes de relatar uma vulnerabilidade ou enviar
material para uma issue pública.

## Exit codes

| Código | Significado |
|--------|-------------|
| `0` | Execução concluída |
| `1` | Execução parcial: artefatos gravados, mas houve falha |
| `2` | Argumento inválido, dependência ausente ou ferramenta desconhecida |
| `3–5` | Falha específica de navegação, autenticação ou login wall no Instagram |
| `6` | Nenhum item encontrado |

Um exit code diferente de zero não significa necessariamente que nenhum arquivo foi
criado. Confira sempre o envelope e a pasta de saída.

## Desenvolvimento

Instale as dependências de desenvolvimento:

```bash
python -m pip install -e ".[dev]"
python -m playwright install chromium
```

Validações principais:

```bash
python -m ruff check .
python -m pytest -m "not integration"
python -m build
python -m twine check dist/*
```

Para adicionar uma ferramenta, consulte
[`docs/ADDING_TOOLS.md`](docs/ADDING_TOOLS.md).

Estrutura do pacote:

```text
src/tarrafa/
  cli.py
  core/
  tools/
  skills/
  templates/
tests/
docs/
examples/
```

## Atualização

Dentro do repositório:

```bash
git pull
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\tarrafa.exe skills install
.\.venv\Scripts\tarrafa.exe doctor
```

No macOS ou Linux, substitua `.\.venv\Scripts\` por `./.venv/bin/`.

## Licença

Copyright © 2025–2026 Mosimann Advocacia e contribuidores.

Distribuído sob a [PolyForm Noncommercial 1.0.0](LICENSE):

- uso não comercial permitido;
- atribuição obrigatória;
- redistribuição deve preservar licença e avisos;
- uso comercial ou oferta como serviço exige autorização separada.

O software é fornecido sem garantias. Consulte o texto integral da licença.

## Apoie o projeto

Se a Tarrafa for útil em pesquisa, ensino ou experimentação, contribuições são
bem-vindas:

- relate bugs sem publicar dados sensíveis;
- envie correções e testes;
- proponha melhorias na documentação;
- compartilhe casos de uso anonimizados.

![QR Code Pix](assets/pix-qr.png)

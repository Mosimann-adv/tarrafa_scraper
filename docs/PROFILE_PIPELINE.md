# Pipeline de perfil (lições de caso · 2026-07)

Playbook operacional para dossiês de pessoa (influenciador / parte / sócio).  
Complementa `AGENTS.md` e a skill `tarrafa-perfil`. Material-only: o CLI captura; a orquestração fecha nexo e redige.

## Estrutura de pasta

```text
CASO/
  raw/                 # envelopes djen, cnpj, datajud, page, pdf-extract
  raw/processos/       # PDFs baixados do eproc (quando houver)
  shots/               # PNG via tarrafa shot (sempre gravar AQUI)
  perfil/
    foto_identificacao.png
    dossier.json       # V1 (trabalho)
    PERFIL_….html      # V1 HTML
    ANEXO_….pdf        # V2 judicial (quando pedido) — fora do tarrafa CLI
```

## Ordem de coleta

1. **Âncoras** — nome completo + handle e/ou cidade/função.
2. **Descoberta web aprofundada** — use `tarrafa profile` para diversificar consultas,
   pontuar candidatos, abrir páginas públicas, procurar site próprio e inventariar
   artigos/blog/sitemap. Sem provedor, faça a busca com as ferramentas do ambiente,
   registre o primeiro repasse com `--from-agent` e execute também as consultas gravadas
   em `queries_followup.txt`. Pular a segunda rodada e ir direto ao DJEN é uma lacuna.
3. **Instagram acoplado** — havendo handle ou perfil candidato, `profile` chama
   `tarrafa ig`, grava `instagram/profile.json` + `instagram/profile.png`, descobre
   posts/reels e coleta comentários. `social_profiles` genérico nunca substitui
   `instagram_profile`.
4. **`tarrafa shot` seletivo** no post/reel quando for necessária imagem adicional.
5. **`djen --papel parte --cpf`** quando houver CPF. Sem CPF, usar `--nome "Nome
   Completo"` e `--texto "handle"` (handles quase nunca saem no DJEN; o nome sim).
6. **`--follow-datajud`** ou `datajud` nos CNJs com nexo.
7. **`cnpj`** só com número; **não** atribuir QSA ao alvo sem CPF coerente.
8. **`pdf-extract --dir raw/processos`** quando o advogado baixar autos.
9. **V1** `dossier` (manifest); **V2** anexo PDF judicial se pedido (Times, sem paths internos).

```powershell
tarrafa profile --name "Marina Alves" --handle "@marinaalves" `
  --profession "arquiteta" --keyword "urbanismo" `
  --from-agent "CASO\raw\repasse.json" --out-dir "CASO\raw\profile" `
  --ig-storage-state ".\storage_state.json" --ig-expand-replies
```

O comando gera `profile.json` e `profile.html` por padrão. Não finalize um pedido de perfil
entregando apenas o JSON. `--no-html` é reservado a integrações machine-only; para outro
destino visual, use `--html-out "CASO\html\PERFIL.html"`.

Só considere a descoberta suficientemente profunda quando a matriz de cobertura registrar
consultas por nome/handle/contexto, domínio próprio avaliado, páginas institucionais
abertas, seção de artigos ou sitemap verificados e lacunas explicitadas. `profile` não usa
CPF, e-mail ou telefone como consulta e não transforma candidato em identidade confirmada.
Conteúdo autoral externo capturado deve constar no inventário com relação `candidate`, sem
ser confundido com artigos encontrados no domínio profissional. Para Instagram, confira
separadamente `instagram_profile` e `instagram_posts`: LinkedIn não cobre essas linhas.
`blocked` ou `missing` deve permanecer como lacuna, nunca ser promovido a sucesso.

## Instagram — o que falha e o que fazer

| Problema | Causa | Mitigação |
|----------|--------|-----------|
| MCP “File access denied” / hang na extensão | MCP grava só em roots da sessão; `--extension` espera Chrome conectado | **Não usar MCP** para coleta. **`tarrafa shot` / `tarrafa ig`** no path do caso. |
| “Sem imagem” no HTML | Shot existe mas crop do avatar falhou / sem `--avatar` | Usar print de perfil no `shots[]`; avatar: preferir **foto que o usuário indicar**, senão crop cuidadoso ou omitir. |
| Login wall no print / 0 comentários | Sessão sem login ou `storage_state` expirado | `tarrafa ig|shot --storage-state …`; se preciso, login headed + `--save-storage`. **Nunca** embutir modal de login no dossier. |
| Inventário com nome errado | ASR / label informal | Confirmar no **IG verificado** + autos; corrigir no meta. |

Comandos:

```powershell
tarrafa ig --url "https://www.instagram.com/HANDLE/" `
  --out "CASO\raw\profile\instagram\profile.json" `
  --profile-shot "CASO\raw\profile\instagram\profile.png" `
  --storage-state ".\storage_state.json"
tarrafa shot --url "https://www.instagram.com/HANDLE/" --out-dir "CASO\shots" --id ig_perfil --clip page --dpr 2
tarrafa shot --url "https://www.instagram.com/HANDLE/reel/ID/" --out-dir "CASO\shots" --id ig_reel --clip page --dpr 2
```

## Homônimos e CPF (crítico)

- Máscara de sócio no CNPJá `***ABCDEF**` = dígitos **4–9** do CPF informado.
- **Nunca** fundir QSA com a pessoa do perfil se a máscara **não** bate com o CPF dos autos.
- Se os dígitos centrais do CPF da parte divergirem da máscara do sócio, não atribuir o CNPJ à pessoa.
- Nexo forte de parte: **handle nos autos**, cônjuge co-parte com IG cruzado, e-mail de petição, nome civil + foto/handle.
- Criminal de homônimo → seção “não fundir”, não facts.

## DJEN parte

```powershell
tarrafa djen --papel parte --cpf "<CPF>" --max-items 50 --out raw\djen_cpf.json
tarrafa djen --papel parte --nome "Nome Completo" --max-items 50 --out raw\djen_nome.json
tarrafa djen --papel parte --texto "handleig" --max-items 30 --out raw\djen_handle.json
tarrafa djen --papel parte --cpf "<CPF>" --follow-datajud `
  --datajud-out raw\datajud.json --max-cnj 15 --out raw\djen.json
```

- Com `--cpf`, a ferramenta ignora `--nome`/`--texto` na consulta e só retém
  comunicações que contenham o CPF exato no teor ou no destinatário estruturado.
- `identity_hints` no summary = heurística; validar.
- Hit sem âncora = gap, não fato.

## pdf-extract (autos)

```powershell
tarrafa pdf-extract --dir raw\processos --recursive --out raw\pdf_extract.json
```

- Priorizar petição inicial / denúncia / procuração / mandado (qualificação).
- CPF nos autos prevalece sobre máscara CNPJ e sobre hints ruidosos (juízos, terceiros).

## Duas entregas

| | V1 HTML (`dossier`) | V2 PDF anexo judicial |
|--|---------------------|------------------------|
| Uso | Trabalho interno | Juntar aos autos |
| Paths internos / tarrafa / method | Pode ter | **Proibido** |
| Liminar/JG favorável ao alvo | Pode registrar | Não “comemorar”; se citar, só se necessário e factual |
| Travessão (—) | Indiferente | **Evitar** (vírgula / dois-pontos) |
| Títulos | Layout Custódio | Colados no parágrafo seguinte (`KeepTogether`) |
| Narrativa | Neutra ou “problemáticas” | Problemáticas lastreadas, sem inventar |

V2 **não** é tool do CLI (fica na orquestração / script de caso). CLI = captura + `dossier` HTML.

## Modo “problemáticas” (influenciador ofensor)

1. Mesma coleta multi-fonte.
2. Ênfase em: reel/ofensa documentada, denúncias/processos no polo passivo, penhora, contravenção/crime, capacidade de amplificação.
3. Outdoor / caso cliente: URL + legenda + transcrição local se houver.
4. V1 com gaps honestos; V2 enxuta para petição.

## Anti-padrões extras (casos reais)

- Card “Empresas/QSA” de homônimo no HTML depois de afastar CPF.
- Afirmar “sem acesso ao IG” quando o shot já existe em `shots/`.
- Fundir DJEN trabalhista de sócio industrial com influencer sem CPF.
- Colocar no V2: `raw/`, `obtidos_adv`, `tarrafa`, `INF-0x` como path de vault.

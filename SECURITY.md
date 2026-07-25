# Segurança

## Status do projeto

O Tarrafa é um **projeto experimental / em desenvolvimento**, não um produto comercial com SLA, suporte formal ou garantia de estabilidade.

Use por sua conta e risco. APIs e sites de terceiros mudam; scrapers quebram; resultados exigem validação humana.

## O que não enviar em issues, PRs ou discussões

**Nunca** publique material de caso ou dados pessoais, inclusive:

- autos, petições, prints de processo, e-mails de cliente  
- CPF, RG, CNH, telefone, endereço, data de nascimento  
- número CNJ, OAB de terceiros em contexto sensível  
- `storage_state.json`, cookies, tokens, `.env`, chaves de API  
- handles, nomes ou fatos que identifiquem parte em investigação  
- trechos de dossiê / HTML de perfil com conteúdo real de caso  

Para reportar bug de captura, use **URL pública de exemplo**, fixture sintética ou recorte anonimizado.

## Segredos e sessão

| Arquivo / dado | Regra |
|----------------|--------|
| `.env`, `~/.tarrafa/.env` | Local apenas; já no `.gitignore` |
| `PLAYWRIGHT_MCP_EXTENSION_TOKEN` | Não commitar; rotacionar se vazar |
| `storage_state.json` (Instagram etc.) | Sessão pessoal; nunca compartilhar nem versionar |
| `DATAJUD_API_KEY` (se usar) | Local apenas |
| Saídas `raw/`, `shots/`, pastas de caso | Fora do repositório do tool |

Preferir `tarrafa init` em pasta **fora** deste repo e gravar outputs só no workspace do caso.

Prefira variáveis de ambiente para credenciais. Embora o Tarrafa masque opções
sensíveis conhecidas nos manifests de execução, valores passados diretamente na
linha de comando também podem ficar visíveis temporariamente na lista de
processos do sistema operacional.

## Uso lícito

- Respeite ToS dos sites, LGPD e demais normas aplicáveis.  
- O software **não** presta serviço advocatício e **não** substitui análise jurídica.  
- Captura é material-only: não classifica ofensas nem inventa biografia.

## Reportar vulnerabilidade no código

Se encontrar falha de segurança **no próprio repositório** (ex.: vazamento acidental no git, path traversal, execução indevida):

1. **Não** abra issue pública com detalhes exploráveis.  
2. Contate o mantenedor em privado: **mosimannadv@gmail.com** (assunto: `Tarrafa security`).  
3. Inclua: descrição, passos de reprodução, impacto — **sem** dados de caso.

Resposta: melhor esforço, sem prazo garantido (projeto experimental).

## Escopo

| Dentro | Fora |
|--------|------|
| Código e dependências deste repo | Segurança de Instagram, CNPJá, DJEN, Datajud etc. |
| Vazamento de config no git | Contas, senhas e sessões do usuário |
| Bugs exploráveis no CLI | Conteúdo jurídico produzido com o tool |

## Referências

- Licença: [LICENSE](LICENSE) (PolyForm Noncommercial 1.0.0 — sem garantia)  
- Uso: [README.md](README.md)  

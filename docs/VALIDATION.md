# Relatório de validação — 17/10/2026

Branch local: `main/finalizar-mvp`, criada a partir de `origin/main`. Sem push, deploy, alterações de IAM/infraestrutura, chamadas ao bot/canal ou publicação. O serviço `dodfpmdfbot` não foi alterado. Nenhum segredo foi lido.

## Resultado por requisito

| Requisito | Resultado verificável | Pendência |
|---|---|---|
| Auditoria/correções | API pública, autenticação do webhook, corpo limitado, erros sanitizados, limites, dependências auditadas | Revisão da configuração real GCP e aceite de produção |
| Comandos públicos | `/start`, `/ajuda`, `/pncp`, `/licitacoes`, `/atas` testados com ID arbitrário sem allowlist | Deploy e teste com usuário real |
| Quota usuário | Janela móvel de 60 minutos, até 10 consultas, transação Firestore | Testar concorrência no emulador/ambiente autorizado |
| Cache/teto global | Cache 30 min em 256 slots, limite diário 1.500 updates e 400 chamadas PNCP, fail closed | Validar contadores/IAM reais |
| PNCP | OpenAPI oficial salvo, parâmetros/paginação limitados, 204 e erros cobertos, links canônicos, aviso amostral | Conferência visual dos dois deep links no portal; um não pôde ser acessado pela ferramenta |
| Atas | Endpoint oficial por atualização global; objeto, vigência/cancelamento e link à compra de origem | Aceite com bot real; não é catálogo de atas vigentes |
| Cloud Run | Workflow preparado para 0–1, 512 MiB, CPU por solicitação, concorrência 1 | Não aplicado: precisa autorização e inventário |
| IAM/segredos | Papel mínimo proposto; OIDC e Secret Manager com versões fixas | Bindings, environments e permissões reais não auditados/aplicados |
| Briefing | Gerador sem IA, cinco títulos oficiais recentes, verificação de página, preview/SHA/revisão e reivindicação semanal | Feeds redirecionam para login; nenhuma prévia real de cinco notícias validada. Cron/publicação automática desativados |
| Testes | 44 testes locais passaram; mocks de HTTP/Firestore e falhas externas | Python 3.12 Linux, Docker, teste opcional de emulador e fluxos GitHub ainda não executados |
| Observabilidade/custos | Eventos sem dados pessoais; suspensão local/remota; política de logs e runbook financeiro | Canal, valor/moeda de orçamento e aplicação dos alertas a confirmar |
| Workflows | CI, deploy por digest, prévia, publicação manual revisada, manutenção OIDC/SM; YAMLs parseados | Commit/push/revisão, ambientes protegidos, execução autorizada |

## Evidências executadas

- Teste original antes de alterar: **1 passou**.
- Suíte final: **44 passaram, 1 pulado** (emulador não configurado) em Python 3.13.7 no Windows, com dois avisos de depreciação de TestClient/httpx/AnyIO, sem falhas. CI preparada para Python 3.12 no Linux.
- `pip check`: sem dependências quebradas.
- `compileall`: fontes compiláveis; `git diff --check`: sem erros de whitespace.
- `pip-audit -r requirements.txt`: inicialmente detectou vulnerabilidades em Starlette 0.46.2. Após atualização para FastAPI 0.143.3/Starlette 1.3.1, **nenhuma vulnerabilidade conhecida encontrada**. Auditoria repetida após fixar transitivas em constraints. Isso é uma verificação da base consultada, não garantia de ausência de falhas.
- Seis arquivos de workflows parseados como YAML. Não equivale à execução/validação completa das APIs GitHub/GCP. Actions oficiais resolvidas via API GitHub e fixadas em SHA; imagem Python oficial fixada pelo digest de manifest.
- `https://pncp.gov.br/api/consulta/v3/api-docs`: consultado com sucesso, contrato salvo em `docs/pncp-openapi.json`. O contrato atual limita contratações a 10–50 registros/página e atas a 10–500; implementação usa 50.
- Duas requisições reais limitadas, 10 registros/página, período 10–17/10/2026: `/contratacoes/publicacao` (modalidade 6) **HTTP 200**; `/atas/atualizacao` **HTTP 200**, com metadados de paginação e campos usados pelo código.
- Compra real: `08778268000160-1-000627/2026`; link produzido `https://pncp.gov.br/app/editais/08778268000160/2026/627`, reconhecido como portal PNCP pela ferramenta web. A página é SPA e não retornou conteúdo textual verificável; não afirmar validação visual do registro.
- Ata real: `76208495000100-1-000009/2023-000001`, vinculada à compra `76208495000100-1-000009/2023`. Link produzido `https://pncp.gov.br/app/editais/76208495000100/2023/9`. Acesso direto encontrou encerramento de conexão e a ferramenta web não conseguiu abrir esse segundo link. Formato está coberto por teste; navegação completa ainda pendente.
- Notícias: requisição com redirects parecia retornar 200 inicialmente, mas inspeção sem seguir redirecionamentos mostrou **302 para login** em Gestão/Compras. PNCP feed retornou 401 e caminhos candidatos Fazenda/Tesouro, 404. Gerador abortou sem produzir briefing; esse bloqueio não foi contornado.

Teste de concorrência preparado em `tests/test_firestore_emulator.py`: recusará conexão não local ou projeto que não seja o fictício `radar-publico-test`. Foi pulado por ausência do emulador.

## Escopo dos testes

Comandos, autorização de webhook, grupos/bots ignorados, termos inválidos, payload excessivo/malformado, quota móvel e reset, deduplicação recente, orçamento diário e suspensão, reserva por chamada externa, cache hit/expiração/colisão, aliases e separação de atas, parâmetros/páginas, 204/429/500/resposta inválida, falha de persistência/cache/busca, ausência de cache em erro, sanitização de Telegram, seleção/deduplicação/data/domínio de notícias, XML com entidades externas, SHA e autorização de publicação, reivindicação semanal impedindo reenvio.

Os testes de Store usam dublês de documentos/transações: validam a lógica e a ordem de uso, **não comprovam concorrência/atomicidade do serviço Firestore real**. Antes de produção, exercitar transações concorrentes no emulador: 20 consultas simultâneas do mesmo usuário devem admitir no máximo 10; usuários diferentes continuam sujeitos ao teto global; nenhum contador pode exceder o teto. Nenhuma operação Firestore real foi realizada para evitar custos/efeitos no projeto sem confirmação.

## Limitações materiais

- O teto é operacional, não financeiro. Ataques HTTP, leituras rejeitadas/retries, logs, tráfego de saída, imagens e consumo compartilhado podem gerar cobrança.
- IAM de servidor no Firestore compartilhado não limita coleções. A proposta reduz permissões, mas não isola totalmente dados de outro serviço no mesmo banco.
- Reivindicação de update antes de processar e de publicação antes de enviar privilegia evitar duplicação; crashes podem perder respostas. Deduplicação de usuário cobre só os 32 updates recentes por 24h. Telegram não tem exactly-once.
- Documentos de usuário e imagens precisam de política aprovada de retenção/limpeza; não foram executadas exclusões.
- Gerador escolhe por termos no título e recência, sem IA: relevância editorial precisa de revisão humana. Publicação automática e horário exato de 09h não foram habilitados/validados; GitHub cron pode atrasar.
- `gcloud` e Docker não foram encontrados nesta sessão. Não foi validado build de imagem, IAM, rollback, orçamento, alerta nem estado atual de produção. CI e workflow de deploy são preparados, não comprovados em execução.

## Próxima etapa e confirmação necessária

Revisar código/documentação e autorizar separadamente: push/CI; inventário autenticado e teste de build/emulador; criação/ajuste de contas dedicadas, Artifact Registry, alertas e orçamento; só então deploy **do Radar** e teste de Telegram. Push pode disparar Actions e consumir franquia; implantação/armazenamento/acessos/rede podem gerar cobrança. Confirmar valor/moeda do orçamento e destino das notificações antes de criar alertas. Manter publicação automática bloqueada até uma prévia oficial real de cinco notícias ser validada.

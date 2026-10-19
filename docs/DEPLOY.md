# Implantação revisável — não executada em produção

Destino exclusivo: projeto `dodfpmdfbot`, Cloud Run **`radar-publico-bot`**, região `southamerica-east1`. O serviço **`dodfpmdfbot` não pode ser alterado**. Não desative faturamento/APIs do projeto compartilhado.

## Aprovação e inventário

Antes de qualquer mutação, confirmar o custo e a revisão do código. Não há gcloud/Docker disponíveis nesta sessão; IAM, configuração atual do serviço, localização do Firestore, faturas, segredos e budgets não foram inspecionados. Com acesso autorizado, executar apenas leituras inicialmente:

```bash
gcloud run services describe radar-publico-bot --project dodfpmdfbot --region southamerica-east1 --format export
gcloud run services get-iam-policy radar-publico-bot --project dodfpmdfbot --region southamerica-east1
gcloud firestore databases describe --database='(default)' --project dodfpmdfbot
gcloud secrets describe radar-telegram-token --project dodfpmdfbot
gcloud secrets describe radar-webhook-secret --project dodfpmdfbot
```

Guardar o inventário restritamente: pode conter variáveis sensíveis do deploy anterior. Registrar imagem digest e revisão anterior para rollback. Não listar nem imprimir valores de segredos.

## Contas e permissões propostas

Criar/usar contas dedicadas; jamais reutilizar a conta do DODF. Nenhuma permissão Owner/Editor ou chave JSON é necessária.

- **Execução Radar:** papel personalizado definido em `infra/runtime-role.json`, limitado ao banco `(default)` por condição IAM se suportado no binding. Conceder `roles/secretmanager.secretAccessor` somente nos segredos `radar-telegram-token` e `radar-webhook-secret`. Sem acesso a políticas IAM ou Secret Manager em todo o projeto.
- **Implantação GitHub:** `roles/run.developer` somente no serviço existente `radar-publico-bot`, `roles/iam.serviceAccountUser` somente na conta de execução e `roles/artifactregistry.writer` somente no repositório Docker dedicado `radar-publico-bot`. O fluxo atualiza o serviço, não muda sua política de acesso público e não usa Cloud Build. Validar que essas permissões atendem à política da organização, sem ampliar automaticamente para Run Admin.
- **Publicação/manutenção Telegram:** conta separada, acesso ao segredo de token; acesso ao segredo de webhook somente se usada para registrar webhook. Para briefing, precisa criar o documento de bloqueio de publicação no Firestore. Pode-se separar registrador de webhook e publicador para reduzir ainda mais privilégios.
- **OIDC:** Workload Identity Provider restrito ao repositório e ao proprietário, preferencialmente IDs numéricos, além de branch `refs/heads/main`. Para jobs com environment, restringir o `sub` ao environment correspondente. `roles/iam.workloadIdentityUser` no SA específico. Nenhuma credencial persistente de Google no GitHub.

Firestore IAM não restringe acesso por coleção como Security Rules do SDK web. A conta servidor ignora essas regras. Como `(default)` é compartilhado, o papel personalizado ainda pode ler/escrever documentos fora do namespace se o processo for comprometido. O código usa exclusivamente `radar_publico_*`; isolamento total exigiria outro banco/projeto, sujeito a aprovação e possível perda de franquia gratuita. Não fazer essa migração automaticamente.

Criar o papel e bindings só após confirmar esses limites. O papel de runtime não permite listar/excluir documentos; limpeza usa conta operacional separada. IDs de usuário ficam nos nomes de documentos privados, nunca em logs.

## Segredos e ambientes GitHub

O deploy de imagem preserva a configuração existente de `TELEGRAM_BOT_TOKEN` e
`TELEGRAM_WEBHOOK_SECRET`. Não converte variáveis literais em referências a segredos
durante uma atualização de código: o Cloud Run rejeita essa troca de tipo no mesmo
campo. Uma migração para Secret Manager deve ser planejada separadamente, mantendo
os valores em uso e coordenando o webhook. Os números de versão abaixo continuam
sendo usados pelos workflows de manutenção/publicação.

Em 19/10/2026 foi criada a conta `radar-publico-deploy` para implantação. Ela tem
`roles/run.developer` somente no serviço Radar, `roles/artifactregistry.writer`
somente no repositório Docker Radar e `roles/iam.serviceAccountUser` somente na
conta runtime. O vínculo federado exige o subject imutável
`repo:bravedragon-gif@227583959/radar-publico-bot@1417694623:environment:production`.
O provedor também restringe proprietário, ID do repositório e branch main.
`GCP_DEPLOY_SERVICE_ACCOUNT` deve apontar para essa conta; o workflow rejeita
contas de deploy e runtime iguais. Nenhuma chave JSON foi criada.

Secret Manager: versões numéricas existentes, sem `latest`. Token do bot e segredo de webhook devem ser os mesmos em execução e manutenção. Não rotacionar sem coordenar o webhook. Rotação é necessária se um segredo tiver sido exposto; nenhum valor foi lido nesta sessão.

Configurar Variables:

- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_DEPLOY_SERVICE_ACCOUNT`
- `GCP_RUNTIME_SERVICE_ACCOUNT`
- `GCP_PUBLISH_SERVICE_ACCOUNT`
- `TELEGRAM_TOKEN_VERSION`, `TELEGRAM_WEBHOOK_VERSION` (números)
- `BRIEFING_PUBLICATION_ENABLED` = `false`, no environment de publicação

Criar environments `production`, `telegram-maintenance`, `briefing-publication` com revisores obrigatórios e restrição à branch main. **O arquivo YAML não cria essa proteção**; validá-la no GitHub antes de habilitar execução. Workflows mutantes são manuais e restritos à main. Os workflows usam OIDC e Secret Manager; remover cópias antigas de tokens em GitHub Secrets apenas depois de confirmar a migração.

## Contêiner e Cloud Run

Criar repositório Artifact Registry dedicado somente após aprovação de custo, caso ainda não exista. O workflow constrói no runner GitHub e publica imagem com SHA de commit, usando digest no deploy. Dependências diretas e transitivas são fixadas em requirements/constraints; Actions por SHA e imagem base por digest. Revisar a auditoria e atualizar os pins de forma controlada. CI executa testes, auditoria e build em Python 3.12. Build local Docker pendente.

Configuração preparada em `Deploy Cloud Run`: mínimo 0 e máximo 1, tanto no serviço quanto na revisão, 512 MiB, 1 vCPU, CPU throttling (faturamento por solicitação), sem startup CPU boost, concorrência 1, timeout 60s, um worker. É um ponto inicial conservador: medir pico de memória e latência antes de reduzir para 256 MiB. Máximo de instâncias não é limite financeiro absoluto. Não adicionar instância mínima.

Executar workflow somente depois de merge/revisão e autorização expressa. A URL pública existente permanece; autenticação de webhook por segredo Telegram continua obrigatória. `/health` só verifica processo, não as dependências.

## Aceite em produção

Após deploy autorizado: confirmar configuração e imagem efetiva, `/health`, cabeçalho errado recusado, `/start` com usuário novo, `/pncp` e `/atas`, reentrega de update sem duplicata, cache aquecido e limite na 11ª consulta. Validar concorrência transacional no emulador/ambiente autorizado antes de abrir divulgação ampla. Não simular flood pago em produção.

Webhook já registrado: não registrar novamente sem necessidade. Se necessário, workflow manual preserva pendências (`drop_pending_updates` removido), fixa `max_connections=1` e usa o segredo existente.

## Briefing

`python -m app.briefing` gera `artifacts/briefing.json` e `.txt`, sem token. Exige cinco notícias publicadas nos últimos sete dias, assunto no título, HTTPS e domínio/caminho oficial permitido, título presente na página e hash de cada página. Falhas de fonte, datas, volume ou XML abortam. Não gera resumo factual por IA; publica títulos originais e links após curadoria humana.

Os feeds atuais estão bloqueados por login; verificar sua disponibilidade ou adaptar um coletor de outra fonte oficial antes de habilitar a rotina. Não afrouxar verificação ou preencher cinco itens com notícias antigas.

Revisar pertinência, atualidade, texto, links e o SHA256 exato do JSON. O workflow manual `Publish reviewed briefing` recebe run ID da prévia e SHA aprovado, baixa o artefato e requer environment protegido + variável de habilitação. Usa uma reivindicação atômica por semana no Firestore antes de enviar: se envio ficar incerto, não repete automaticamente. Só um operador, após conferir o canal, pode reconciliar a reivindicação. A falha pode causar omissão ou mensagem parcial; Telegram não oferece envio exactly-once.

Cron proposto: segunda, `0 12 * * 1` UTC = 09h Brasília, atualmente comentado. GitHub Actions pode atrasar execuções agendadas; horário exato não é garantido. Habilitar somente após validar fontes/resultados e obter autorização. O cron de prévia, isoladamente, não publica. Publicação automática ainda exige uma etapa posterior de aprovação e adaptação do fluxo.

## Rollback e suspensão

Primeiro suspender só Radar: atualizar `radar_publico_ops/control` com `suspended=true` ou definir `QUERIES_ENABLED=false` no serviço Radar. A suspensão persistida é lida em cada admissão; circuit breaker local pode atrasar retomada em até 60s. A variável interrompe todos os comandos após atualização da revisão.

Rollback: encaminhar tráfego somente para a revisão anterior do **Radar**, conferindo suas variáveis/IAM. Isso pode restaurar falhas antigas; se houver risco, manter suspenso até corrigir. Não usar rollback no serviço DODF.

## Teste opcional de concorrência Firestore

Com emulador local já instalado e iniciado, use um projeto fictício dedicado, nunca o projeto real:

```powershell
$env:FIRESTORE_EMULATOR_HOST='127.0.0.1:8085'
$env:GOOGLE_CLOUD_PROJECT='radar-publico-test'
.venv/Scripts/python -m pytest tests/test_firestore_emulator.py -q
```

O teste recusa hosts não locais e projetos diferentes, não faz exclusões e usa namespaces aleatórios no emulador. Sem essas variáveis ele é explicitamente pulado. Não apontar o teste para Firestore real.

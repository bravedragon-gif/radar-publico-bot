# Briefing automático e consultas — 19/10/2026

Este documento atualiza as seções sobre briefing de DEPLOY.md e VALIDATION.md, que descrevem o fluxo manual anterior.

## Operação

O workflow `weekly.yml` executa na main às segundas, 12h UTC (09h Brasília), e também aceita execução manual. Gera artefatos antes de publicar no canal `@logisticapmdf`. O job usa OIDC e a conta de publicação já prevista; não lê tokens do repositório nem cria serviços pagos. O ambiente `briefing-publication` deve ter `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_PUBLISH_SERVICE_ACCOUNT` e `TELEGRAM_TOKEN_VERSION` configurados. A conta precisa acessar a versão do segredo e criar a reivindicação semanal no Firestore. O bot precisa ser administrador do canal com permissão de publicar.

Se o environment exigir revisão em cada execução, o job aguardará aprovação e o envio não será autônomo. Essa configuração precisa ser conferida pelo administrador antes da ativação; não foi consultada nesta sessão. A rotina semanal habilita a publicação no próprio job; o fluxo manual separado continua exigindo SHA e a variável de habilitação do environment.

Publicação automática e manual compartilham o mesmo grupo de concorrência e a reivindicação atômica por semana. Uma tentativa de envio com resultado incerto exige conferência no canal e reconciliação pelo operador; não apagar a reivindicação para tentar novamente sem essa conferência. Telegram não oferece garantia de envio exatamente uma vez.

Fontes públicas permitidas: comunicados do Compras (RSS 1.0/RDF, datas dc:date) e Economia da Agência Brasil (RSS 2.0). O coletor se identifica como RadarPublico. Só publica títulos com palavras dos temas monitorados, data nos últimos sete dias, URL permitida e título confirmado na página. Até cinco resultados; sem candidatos recentes, publica aviso de ausência de novidades nas fontes disponíveis. Falha de todas as fontes ou de todas as páginas candidatas interrompe a geração. A cobertura dos feeds é limitada aos itens fornecidos por eles; não equivale a pesquisa exaustiva.

## Consultas

Continuam disponíveis em conversa privada com `@Log_pmdf_bot`: `/pncp`, `/compras`, `/pncp viaturas`, `/compras viaturas`, `/atas viaturas`, `/cancelar`. Os menus incluem licitações, atas e pesquisa. A publicação no canal não depende de receber comandos privados. Mantidos limites de usuário, orçamento, cache e pausa diante de HTTP 429.

## Evidências desta mudança

- Health check público do Cloud Run respondeu `status=ok`; isso não comprova Firestore ou Telegram.
- Consulta real PNCP: oito páginas, dois resultados para viaturas; Compras: três páginas, nenhum resultado na amostra. Validação feita a partir do computador local, sem Firestore/Telegram; não comprova liberação do IP do Cloud Run.
- Prévia real gerada: ambos os feeds disponíveis, nenhum título recente passou pelo filtro temático naquele momento. Nenhuma mensagem enviada.
- Suíte local: 78 aprovados, um teste de emulador ignorado, dois avisos de depreciação. Testes HTTP/Firestore usam dublês; não comprovam IAM de produção.

## Ativação e rollback

Após integrar a mudança, conferir as variáveis, permissões do environment e IAM; executar `weekly.yml` e verificar o job e a mensagem no canal. Para atualizar consultas no Cloud Run, usar o workflow existente de deploy somente do Radar. A autenticação local do GitHub CLI está inválida e não há gcloud disponível nesta sessão; configuração GCP e envio real ainda não foram validados.

Rollback: reverter o commit do workflow semanal para desativar o agendamento. Não alterar o serviço DODF, o faturamento compartilhado ou os dados de outros serviços. Reivindicações existentes devem ser preservadas.

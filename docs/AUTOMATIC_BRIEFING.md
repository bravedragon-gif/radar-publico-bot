# Notícias diárias — coleta, histórico e operação

Atualiza as descrições antigas de briefing em DEPLOY.md e VALIDATION.md. O canal é `@logisticapmdf`; consultas continuam em conversa privada com `@Log_pmdf_bot`. Não há IA paga ou serviço novo.

## Fluxo

O workflow `weekly.yml` preserva o caminho, mas executa diariamente às 12h UTC (09h Brasília) e aceita execução manual na main. Usa OIDC e a conta em `GCP_PUBLISH_SERVICE_ACCOUNT`, com o segredo existente `TELEGRAM_BOT_TOKEN` na versão numérica `TELEGRAM_TOKEN_VERSION`.

1. `python -m app.briefing --history` lê o histórico e pesquisa publicações dos últimos sete dias.
2. Coleta até 50 entradas por feed ou oito links por listagem HTML, sem paginação ilimitada. A verificação das páginas é intercalada entre fontes, limitada a 32 candidatas, com até quatro requisições concorrentes. São no máximo sete requisições de coleta e 32 de verificação, com resposta de até 2 MB e timeout de rede. Não segue redirects para login ou outros domínios.
3. Verifica título, data de publicação (não data de modificação), URL e tópico. Ordena por relevância operacional e data; o TCU recebe prioridade editorial por ser fonte de controle. Exclui avisos acadêmicos e correspondências textuais falsas, como solicitações/licitações. Os filtros são heurísticos, não uma curadoria humana.
4. Gera JSON/texto com até cinco itens e estado de cobertura (`ok`, `partial`, `unavailable`). Publica título e trecho da descrição da página, fonte, data, link e checklist editorial. Não gera resumo jurídico ou interpretação de acórdão. Recomendações editoriais não criam obrigações, prazos ou aplicabilidade automática à PMDF.
5. O job guarda os artefatos por sete dias e publica o JSON exato pelo SHA256.

## Fontes e limitações

| Fonte | Coleta pública | Observação |
|---|---|---|
| TCU | `https://portal.tcu.gov.br/rss.xml` | RSS oficial; verifica cada página de notícia, sem inferir conteúdo de acórdãos não consultados |
| Compras | coleção `comunicados-de-{year}/RSS` | RSS 1.0/RDF com datas `dc:date` |
| PNCP | `https://www.gov.br/pncp/pt-br/central-de-conteudo/noticias/RSS` | Endpoint consultado; se bloqueado é reportado, não contornado |
| Tesouro Nacional | `https://www.gov.br/tesouronacional/pt-br` | Links de notícias em destaque na capa; cobertura limitada aos destaques, pois a listagem completa depende de outro formato |
| Fazenda | `https://www.gov.br/fazenda/pt-br/assuntos/noticias/{year}` | Primeiros oito links de artigos da listagem pública; data/descrição verificadas na página |
| Gestão | `https://www.gov.br/gestao/pt-br/assuntos/noticias/RSS` | Se redirecionar para login, reporta indisponibilidade |
| Agência Brasil | `https://agenciabrasil.ebc.com.br/rss/economia/feed.xml` | Filtro temático de logística/finanças públicas; não inclui toda notícia econômica |

A janela de sete dias não significa busca exaustiva: depende dos itens disponibilizados por cada fonte e dos limites acima. Os coletores de Compras/Fazenda acompanham o ano corrente; na virada do ano sua cobertura dos últimos dias de dezembro pode ser reduzida. Notícias sem data verificável, futuras, antigas ou fora dos domínios/caminhos permitidos são excluídas. Redirecionamentos e mudanças de layout podem exigir manutenção.

Sem novidades e sem falhas, publica aviso de ausência de itens novos verificados. Com falhas e sem itens, publica aviso de coleta incompleta, sem afirmar que não existem notícias. Com todas as fontes indisponíveis, envia aviso operacional explícito. Falha no histórico do Firestore bloqueia a publicação.

## Histórico e duplicidade

- Documento `radar_publico_ops/news_history`: hashes SHA256 de URLs canônicas (sem query, fragmento ou barra final), com timestamp de reivindicação. Não registra credenciais. Retém 35 dias e limita a 400 entradas; normalmente até 175 entradas, com cinco por dia. Não cresce sem limite nem faz consultas por coleção ou exclusões.
- Documento `radar_publico_publications/AAAA-MM-DD`: claim diário na data de Brasília, SHA do artefato, IDs e status. A transação lê dia e histórico antes de escrever ambos. Uma URL já reivindicada ou um claim diário existente bloqueia o envio, inclusive claims gerados pela versão anterior.
- Após resposta bem-sucedida do Telegram, registra `status=sent`. Qualquer falha após a reivindicação deixa estado incerto; a notícia permanece reservada para não repetir uma entrega parcial. O operador deve conferir o canal antes de reconciliar documentos. Não limpar claims ou histórico como tentativa de recuperação.
- O protocolo conserva a garantia existente de evitar reenvios automáticos, não garante entrega exatamente uma vez. O Telegram pode dividir o boletim em mensagens, e falhas podem produzir entrega parcial. Títulos iguais são deduplicados dentro do boletim; URLs diferentes para a mesma matéria em dias diferentes não têm deduplicação semântica.
- Artefatos antigos (schema 1) devem ser regenerados. Publicação valida schema 2, recência dos itens, SHA, fontes e duplicidade. O fluxo manual também passa pela transação de histórico.

Operação normal: uma leitura do histórico na geração, duas leituras/duas escritas na reivindicação e uma leitura/uma escrita na confirmação, além de retries transacionais. Permissões requeridas: get/create/update de documentos, já previstas no papel do Radar. Não exige list/delete, serviço novo ou ampliação automática de IAM. O Firestore continua compartilhado e sujeito às limitações descritas no DEPLOY.md.

## Verificação e implantação

Testes cobrem RSS/RDF, HTML e JSON-LD, datas/fuso, janela de sete dias, filtro temático, fontes bloqueadas/parciais, limite de resposta, validação do artefato, histórico entre dias e preservação de claims incertos. Dublês de Firestore não comprovam concorrência no serviço real; o teste opcional de emulador exige ambiente local dedicado.

Para validar a coleta sem publicar e sem credenciais: `python -m app.briefing`. Para excluir histórico real: adicionar `--history` em ambiente autorizado com OIDC. Não executar testes contra Firestore de produção. A suíte de regressão inclui comandos PNCP/Compras e webhook.

A implantação desta funcionalidade é pelo merge do workflow e módulos na main; não requer atualizar o serviço Cloud Run para as consultas. Após CI e integração, executar manualmente com `preview_only=true` permite verificar fontes, acesso ao histórico e artefatos sem enviar mensagens nem reivindicar o dia. Sem essa opção, publica; o agendamento também publica. Um envio extra no mesmo dia continua bloqueado pelo claim existente. A autorização do environment `briefing-publication`, se configurada, continua sendo respeitada.

Rollback: reverter o commit dos coletores/workflow. Preservar histórico e claims. A versão anterior volta à seleção de 24h e não usa histórico entre dias; avaliar a suspensão do briefing até restaurar o código novo para não repetir matérias. Nenhuma alteração deve atingir o serviço DODF ou outros dados do projeto.

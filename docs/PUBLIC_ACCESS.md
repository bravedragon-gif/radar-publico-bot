# Acesso público e limites

Todos os IDs Telegram válidos podem usar `/start`, `/ajuda`, `/pncp`, `/licitacoes` e `/atas` em conversa privada. Não existe allowlist de usuários. Bots e mensagens de grupos são ignorados; o webhook exige o segredo Telegram correto.

`/pncp termo`, `/licitacoes termo` e `/atas termo` compartilham quota de 10 consultas por usuário nos últimos 3.600 segundos. Validação acontece antes da quota de consulta; comandos inválidos ainda consomem orçamento de atualizações aceitas. Cache hit também consome quota de usuário, impedindo abuso de envios. Consultas que falham depois da admissão consomem quota, sem reembolso ou retry externo automático.

Firestore: namespace `radar_publico_users` armazena até 10 timestamps e os últimos 32 update IDs por usuário, válidos por até 24h; duplicatas nesse recorte são ignoradas. Replays antigos fora do recorte podem ser processados novamente, mas permanecem sujeitos às quotas. A reivindicação antes de processar evita duplicação de custo; um crash posterior pode perder a resposta. Exatamente uma resposta por update não é garantida.

A mesma transação lê controle global, contador diário e usuário antes de escrever. Teto inicial: 1.500 atualizações novas/dia UTC (inclui comandos de ajuda e rejeições por quota de usuário) e 400 requisições PNCP/dia UTC, reservadas antes de cada chamada externa. Retries de transação são limitados a três tentativas. O webhook autentica e limita corpo a 16 KiB antes de persistência.

Cache: chave inclui comando, termo normalizado e data Brasília. Até 256 slots persistentes por hash; colisão causa miss, nunca resposta de outro termo. Resultado expira em 30 minutos; somente resultado completo é gravado. Cache não contorna quota nem suspensão. Não há TTL pago de limpeza automática. Documentos de usuário são persistentes; prever limpeza operacional revisada de usuários inativos, com conta separada e análise de retenção/custo.

`radar_publico_ops/control` com `suspended=true` bloqueia admissões; `QUERIES_ENABLED=false` interrompe todos os comandos. Ao atingir teto global ou falhar dependência, circuit breaker local suprime novas operações por 30–60 segundos, reduzindo repetição de leituras. A falha de Firestore impede consultas e não tenta envio ilimitado de avisos. Requisições continuam chegando ao Cloud Run: esses controles **não garantem teto monetário**, nem impedem cobrança por flood HTTP, logs ou reentregas.

As respostas sempre identificam a busca como amostral e mostram período/páginas. Contratações: publicações nas modalidades 6, 8, 4, 5; até duas páginas por modalidade. Atas: atualização global, até duas páginas; inclui atas expiradas/canceladas e links para a contratação de origem. Não apresentar esses resultados como catálogo completo de atas vigentes ou disponíveis para adesão.

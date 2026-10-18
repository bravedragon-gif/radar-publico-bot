# Consulta PNCP sem resposta útil — 18/10/2026

Após a correção das variáveis de Telegram pelo operador, `/start` respondeu.
A consulta `/pncp viaturas` de 12:20 recebeu HTTP 200 no webhook, seguida por
`cache_miss` e `dependency_failure`. A mensagem de indisponibilidade chegou ao
usuário, confirmando que o envio ao Telegram funcionou nesse pedido.

O evento antigo não contém etapa, categoria ou status HTTP. Portanto não é
possível atribuir a causa a timeout, PNCP ou persistência com certeza.

A reprodução local contra a API pública oficial completou sete páginas e
encontrou dois registros na amostra. Uma segunda execução, com timeout de leitura
de 10 segundos e conexão de 5 segundos, levou 4,03 segundos. O prazo total do
processamento PNCP continua limitado a 30 segundos; não foram adicionados retries,
páginas ou chamadas extras por consulta. Os resultados continuam amostrais.

Testes locais: `python -m pytest tests -q` no ambiente virtual: 48 aprovados,
1 ignorado (emulador Firestore), 2 avisos de depreciação. Quatro novos casos
verificam diagnóstico de timeout, rede, resposta inválida e HTTP 503, inclusive
ausência do texto sensível das exceções nos logs.

A correção acrescenta diagnóstico com etapa e categorias fixas, incluindo status
HTTP quando disponível. Não registra mensagens de exceção, URLs, tokens,
cabeçalhos, conteúdo da consulta ou identificadores de usuários.

Validação em produção pendente: implantar apenas o Radar, enviar uma nova consulta
e verificar `query_ok` ou a categoria segura da falha. A reprodução local não
comprova recuperação do serviço no Cloud Run.

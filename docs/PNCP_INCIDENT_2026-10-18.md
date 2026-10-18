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

## Causa confirmada após implantação do diagnóstico

Em 18/10, às 12:35:33 e 12:53:40 (Brasília), a revisão nova registrou
`stage=pncp`, `category=http_status`, `status=429`. A fonte recusou as chamadas;
o aumento de timeout não resolveu esse incidente. Não há evidência para afirmar
se o limite é por IP, rede, endpoint ou outra política da fonte.

Tratamento adicional: HTTP 429 interrompe imediatamente a busca, sem retries ou
resultados parciais. O bot persiste no documento de orçamento a data mínima para
novas chamadas, respeitando Retry-After em segundos ou data HTTP (mínimo 60s;
ausente/inválido: 300s). Reservas seguintes verificam esse prazo na leitura que já
faziam. Registrar o bloqueio custa uma leitura e uma escrita adicionais por 429.
O prazo sobrevive ao reinício do processo e à virada de dia. Ajuda e cache não
dependem dessa pausa. Falha ao persistir a pausa mantém bloqueio local seguro.

A mensagem explica o HTTP 429 e oferece o portal oficial para consulta manual.
Isso trata o bloqueio com segurança; não garante que a fonte aceitará chamadas
depois do prazo, nem contorna sua política de acesso.

Validação local ampliada: 57 testes aprovados, 1 ignorado, 2 avisos de depreciação.

# Acesso público ao bot Telegram

O bot responde a qualquer usuário em conversa privada. Não é necessário cadastrar IDs em `ALLOWED_TELEGRAM_USER_IDS`. O webhook continua protegido por `TELEGRAM_WEBHOOK_SECRET`.

## Limite distribuído

Até **10 consultas PNCP por usuário em uma janela fixa de 60 minutos**, contabilizada a partir da primeira consulta na janela. `/start`, `/ajuda` e `/atas` (ainda indisponível) não consomem quota.

O limite é implementado com transações do **Google Cloud Firestore** para funcionar entre múltiplas instâncias Cloud Run. Se o Firestore estiver indisponível ou não configurado, as consultas falham de forma segura, sem liberar tráfego ilimitado.

### Provisionamento

1. Ative `firestore.googleapis.com` no projeto Google Cloud do Cloud Run.
2. Crie uma base Firestore em **Native mode** (database ID `(default)`, salvo se definir `FIRESTORE_DATABASE`). Escolha uma região compatível com seus requisitos de residência e latência.
3. Conceda `roles/datastore.user` **à conta de serviço de execução do radar-publico-bot**, não à conta do DODF.
4. Faça novo deploy do Cloud Run a partir do commit com estas alterações.
5. Teste `/start` e `/pncp viaturas` com usuário antes não autorizado; confirme limite na 11ª consulta.

O comando `/pncp` ainda faz uma **busca amostral**, não uma pesquisa exaustiva. Não ative o briefing semanal até implementar a verificação de fontes oficiais.

### Notas operacionais

- Firestore tem custos e cotas próprios; monitore a cobrança no Google Cloud.
- A versão inicial não possui deduplicação persistente de `update_id` do Telegram. Reentregas do mesmo update podem consumir quota adicional.
- A API responde de forma síncrona às consultas; consultas longas podem exigir fila assíncrona em uma versão posterior.

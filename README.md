# Radar Público — Logística e Finanças

Bot Telegram para consultas amostrais ao PNCP e futuro briefing semanal de fontes oficiais.

## Estado
- API FastAPI com webhook autenticado e autorização por Telegram user ID.
- `/pncp termo` e `/licitacoes termo`: busca **amostral**, não exaustiva.
- Briefing semanal: **bloqueado até existir coleta e verificação de fontes oficiais**.
- Implantação Cloud Run e credenciais ainda pendentes.

## Segurança
Configure `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` e `ALLOWED_TELEGRAM_USER_IDS` via Secret Manager; não coloque segredos no Git. Canal: bot administrador com permissão de postagem.

## Atenção
O repositório foi identificado como **público** no GitHub. Altere para privado em Settings → General → Danger Zone → Change repository visibility se desejar acesso restrito.

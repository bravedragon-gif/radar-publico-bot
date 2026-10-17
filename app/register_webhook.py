"""Register Telegram webhook with sanitized error reporting."""
import asyncio
import os
import re
import httpx

URL = "https://radar-publico-bot-389001780280.southamerica-east1.run.app/telegram/webhook"

async def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
    if not token or not secret:
        raise SystemExit("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_WEBHOOK_SECRET")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", secret):
        raise SystemExit("Invalid TELEGRAM_WEBHOOK_SECRET: use 1-256 ASCII letters, digits, underscore or hyphen, without spaces")
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(f"https://api.telegram.org/bot{token}/setWebhook", json={
            "url": URL,
            "secret_token": secret,
            "allowed_updates": ["message"],
            "max_connections": 1,
        })
        if r.status_code != 200:
            try:
                desc = str(r.json().get("description", "No description"))
            except ValueError:
                desc = "Non-JSON response"
            # Never print raw response/request or credentials.
            desc = desc.replace(token, "[REDACTED]").replace(secret, "[REDACTED]")
            raise SystemExit(f"Telegram setWebhook HTTP {r.status_code}: {desc[:500]}")
        if not r.json().get("ok"):
            raise SystemExit("Telegram did not accept the webhook")
    print("Webhook registration succeeded")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        raise SystemExit('Webhook registration failed; inspect connectivity and secret configuration securely.') from None


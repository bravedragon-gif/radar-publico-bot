"""Register Telegram webhook without logging credentials."""
import asyncio
import os
import httpx

URL = "https://radar-publico-bot-389001780280.southamerica-east1.run.app/telegram/webhook"

async def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
    if not token or not secret:
        raise SystemExit("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_WEBHOOK_SECRET")
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(f"https://api.telegram.org/bot{token}/setWebhook", json={
            "url": URL,
            "secret_token": secret,
            "allowed_updates": ["message"],
            "drop_pending_updates": True,
        })
        r.raise_for_status()
        if not r.json().get("ok"):
            raise SystemExit("Telegram did not accept the webhook")
    print("Webhook registration succeeded")

if __name__ == "__main__":
    asyncio.run(main())

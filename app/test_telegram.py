"""Controlled Telegram publication test. No token is logged."""
import asyncio
import os
from app.core import telegram_send

async def main():
    channel = os.environ.get("TELEGRAM_CHANNEL_ID", "")
    if not channel.startswith("@"):
        raise SystemExit("TELEGRAM_CHANNEL_ID must be a public channel username")
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        raise SystemExit("Missing TELEGRAM_BOT_TOKEN Actions secret")
    await telegram_send(channel, "Radar Público — teste de integração\n\nCanal conectado ao bot. Esta mensagem é apenas um teste técnico; não contém briefing ou notícias.\n\nStatus: envio automatizado de teste.")
    print("Telegram test message sent successfully")

if __name__ == "__main__":
    asyncio.run(main())

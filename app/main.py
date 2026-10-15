import os
import secrets
from fastapi import FastAPI, Request, HTTPException
from app.core import pncp_search, format_pncp, telegram_send
from app.rate_limit import consume

app = FastAPI(title="Radar Público")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/telegram/webhook")
async def webhook(request: Request):
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
    header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not secret or not secrets.compare_digest(header, secret):
        raise HTTPException(403, "Forbidden")

    data = await request.json()
    msg = data.get("message") or {}
    text = (msg.get("text") or "").strip()
    chat = msg.get("chat") or {}
    sender = msg.get("from") or {}
    if chat.get("type") != "private" or sender.get("is_bot"):
        return {"ok": True}
    cid = chat.get("id")
    user_id = sender.get("id")
    if not isinstance(cid, int) or not isinstance(user_id, int):
        return {"ok": True}

    command = text.split(maxsplit=1)[0].split("@")[0].lower() if text else ""
    if command in ("/start", "/ajuda"):
        await telegram_send(cid, "Radar Público — consultas públicas\n/pncp termo — consulta amostral de contratações recentes\n/licitacoes termo — equivalente a /pncp\n/atas — em desenvolvimento\nLimite: 10 consultas por usuário por hora.")
    elif command in ("/pncp", "/licitacoes"):
        term = text.split(maxsplit=1)[1].strip() if " " in text else ""
        if not term:
            await telegram_send(cid, "Uso: /pncp viaturas")
            return {"ok": True}
        if len(term) > 120:
            await telegram_send(cid, "O termo deve ter no máximo 120 caracteres.")
            return {"ok": True}
        try:
            allowed = await consume(user_id)
        except Exception:
            # Do not bypass limits if the distributed store is unavailable.
            await telegram_send(cid, "Consultas temporariamente indisponíveis. Tente novamente mais tarde.")
            return {"ok": True}
        if not allowed:
            await telegram_send(cid, "Limite de 10 consultas por hora atingido. Tente novamente mais tarde.")
            return {"ok": True}
        try:
            result = await pncp_search(term)
            await telegram_send(cid, format_pncp(result))
        except Exception:
            await telegram_send(cid, "Consulta ao PNCP temporariamente indisponível. Tente novamente mais tarde.")
    elif command == "/atas":
        await telegram_send(cid, "Consulta de atas em desenvolvimento; ainda não está habilitada.")
    return {"ok": True}

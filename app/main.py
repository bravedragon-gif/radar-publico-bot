import os, secrets
from fastapi import FastAPI, Request, HTTPException
from app.core import pncp_search, format_pncp, telegram_send

app = FastAPI(title='Radar Público')

@app.get('/health')
def health():
    return {'status': 'ok'}

@app.post('/telegram/webhook')
async def webhook(request: Request):
    secret = os.environ.get('TELEGRAM_WEBHOOK_SECRET', '')
    if not secret or not secrets.compare_digest(request.headers.get('X-Telegram-Bot-Api-Secret-Token', ''), secret):
        raise HTTPException(403, 'Forbidden')
    data = await request.json()
    msg = data.get('message') or {}
    text = (msg.get('text') or '').strip()
    chat = msg.get('chat') or {}
    sender = msg.get('from') or {}
    if chat.get('type') != 'private':
        return {'ok': True}
    allowed = {x.strip() for x in os.environ.get('ALLOWED_TELEGRAM_USER_IDS', '').split(',') if x.strip()}
    if str(sender.get('id')) not in allowed:
        return {'ok': True}
    cid = chat.get('id')
    if text.startswith(('/start', '/ajuda')):
        await telegram_send(cid, 'Radar Público\n/pncp termo — consulta amostral de contratações recentes\n/licitacoes termo — equivalente a /pncp\n/atas — em desenvolvimento')
    elif text.startswith(('/pncp', '/licitacoes')):
        term = text.split(maxsplit=1)[1] if ' ' in text else ''
        if not term:
            await telegram_send(cid, 'Uso: /pncp viaturas')
        else:
            try:
                await telegram_send(cid, format_pncp(await pncp_search(term)))
            except Exception:
                await telegram_send(cid, 'Consulta temporariamente indisponível. Tente novamente mais tarde.')
    elif text.startswith('/atas'):
        await telegram_send(cid, 'Consulta de atas em desenvolvimento; ainda não está habilitada.')
    return {'ok': True}

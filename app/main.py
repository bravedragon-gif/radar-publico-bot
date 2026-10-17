"""Public Telegram commands; all persistence and external errors fail closed."""
import asyncio
import json
import logging
import os
import secrets
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from app.core import format_pncp, normalize, pncp_search, telegram_send, validate_term
from app.rate_limit import LimitReached, cache_key, store

app = FastAPI(title='Radar Público', docs_url=None, redoc_url=None, openapi_url=None)
logger = logging.getLogger('radar')
# Do not enable httpx/httpcore debug logs: Telegram URLs include credentials.
logging.getLogger('httpx').setLevel(logging.CRITICAL)
logging.getLogger('httpcore').setLevel(logging.CRITICAL)
lock = asyncio.Lock()
paused_until = 0.0
HELP = ('Radar Público — consultas públicas em conversa privada\n'
        '/pncp termo — contratações\n/licitacoes termo — equivalente a /pncp\n'
        '/atas termo — atas por atualização global\n'
        'Buscas amostrais de 7 dias, até 5 resultados. 10 consultas por usuário em 60 minutos. '
        'Fontes: PNCP. Sujeito a teto global e indisponibilidades.')


def event(name):
    logger.warning(json.dumps({'event': name, 'service': 'radar-publico-bot'}))


@app.get('/health')
def health():
    return {'status': 'ok'}


async def process(cid, uid, update, text):
    global paused_until
    parts = text.split(maxsplit=1)
    command = parts[0].split('@')[0].lower() if parts else ''
    if command not in ('/start', '/ajuda', '/pncp', '/licitacoes', '/atas'):
        return
    query = command in ('/pncp', '/licitacoes', '/atas')
    term = None
    invalid = False
    if query:
        try:
            term = validate_term(parts[1] if len(parts) > 1 else '')
        except ValueError:
            invalid = True
    try:
        accepted = await asyncio.to_thread(store.admit, uid, update, query and not invalid)
        if not accepted:
            event('duplicate_update')
            return
        if not query:
            await telegram_send(cid, HELP)
            return
        if invalid:
            await telegram_send(cid, 'Uso: /pncp termo ou /atas termo (2 a 120 caracteres).')
            return
        kind = 'atas' if command == '/atas' else 'pncp'
        day = datetime.now(ZoneInfo('America/Sao_Paulo')).date().isoformat()
        key = cache_key(kind, normalize(term), day)
        result = await asyncio.to_thread(store.cache_get, key)
        if result is None:
            event('cache_miss')
            async def reserve():
                await asyncio.to_thread(store.reserve)
            result = await asyncio.wait_for(pncp_search(term, kind=kind, reserve=reserve), timeout=30)
            await asyncio.to_thread(store.cache_set, key, result)
        else:
            event('cache_hit')
        await telegram_send(cid, format_pncp(result))
        event('query_ok')
    except LimitReached as exc:
        reason = str(exc)
        event('limit_' + reason)
        if reason in ('global', 'suspended', 'external'):
            paused_until = time.monotonic()+60
        await telegram_send(cid, 'Limite operacional atingido. Consultas temporariamente suspensas.' if reason != 'user' else 'Limite de 10 consultas em 60 minutos atingido. Tente mais tarde.')
    except Exception:
        event('dependency_failure')
        paused_until = time.monotonic()+30
        # Do not send on persistence failure: avoid an unmetered response flood.
        return


@app.post('/telegram/webhook')
async def webhook(request: Request):
    secret = os.environ.get('TELEGRAM_WEBHOOK_SECRET', '')
    header = request.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
    if not secret or not secrets.compare_digest(header.encode(), secret.encode()):
        raise HTTPException(403, 'Forbidden')
    if os.environ.get('QUERIES_ENABLED', 'true').lower() != 'true' or time.monotonic() < paused_until:
        return {'ok': True}
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 16384:
            raise HTTPException(413, 'Payload too large')
    try:
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError()
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, 'Invalid JSON') from None
    msg = data.get('message')
    if not isinstance(msg, dict):
        return {'ok': True}
    chat, sender = msg.get('chat'), msg.get('from')
    if not isinstance(chat, dict) or not isinstance(sender, dict):
        return {'ok': True}
    cid, uid, update = chat.get('id'), sender.get('id'), data.get('update_id')
    if (chat.get('type') != 'private' or sender.get('is_bot') or
            any(type(x) is not int for x in (cid, uid, update)) or uid <= 0 or update < 0):
        return {'ok': True}
    text = msg.get('text', '')
    if not isinstance(text, str) or len(text) > 4096:
        return {'ok': True}
    # One worker, bounded concurrency; no work runs after the HTTP response.
    if lock.locked():
        raise HTTPException(503, 'Busy')
    async with lock:
        await process(cid, uid, update, text.strip())
    return {'ok': True}

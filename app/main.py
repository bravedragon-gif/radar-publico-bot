"""Public Telegram commands; all persistence and external errors fail closed."""
import asyncio
import json
import logging
import os
import secrets
import time
import httpx
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from app.core import PNCPRateLimited, format_pncp, normalize, pncp_search, telegram_send, validate_term
from app.rate_limit import LimitReached, cache_key, store
from app.compras import compras_search, format_compras
from app.menus import CHOICES, KINDS, SOURCES, NAVIGATION, home_keyboard, keyboard, prompt, search_keyboard

app = FastAPI(title='Radar Público', docs_url=None, redoc_url=None, openapi_url=None)
logger = logging.getLogger('radar')
# Do not enable httpx/httpcore debug logs: Telegram URLs include credentials.
logging.getLogger('httpx').setLevel(logging.CRITICAL)
logging.getLogger('httpcore').setLevel(logging.CRITICAL)
lock = asyncio.Lock()
paused_until = 0.0
PNCP_LIMIT_MESSAGE = ('O PNCP recusou novas consultas por limite de acesso (HTTP 429). '
                      'O bot pausou as chamadas à fonte; a liberação depende do PNCP. '
                      'Você pode consultar diretamente: https://pncp.gov.br/app/editais')
HELP = ('Radar Público — consultas públicas em conversa privada\n'
        'Toque em PNCP ou Compras.gov.br, escolha Licitações, Atas ou Pesquisa e digite o termo.\n'
        'Menu principal permite trocar de fonte; Cancelar encerra a seleção.\n\n'
        'Atalhos opcionais:\n/menu — menu principal\n'
        '/pncp — menu PNCP\n/compras — menu Compras.gov.br\n/cancelar — encerrar seleção\n'
        '/pncp termo — contratações\n/licitacoes termo — equivalente a /pncp\n'
        '/atas termo — atas por atualização global\n'
        'Buscas amostrais de 7 dias, até 5 resultados. 10 consultas por usuário em 60 minutos. '
        'Fontes: PNCP e Compras.gov.br. Pesquisa é busca geral por termo, não pesquisa de preços. '
        'Sujeito a teto global e indisponibilidades.')


def event(name, **details):
    logger.warning(json.dumps({'event': name, 'service': 'radar-publico-bot', **details}))


def failure_details(exc, stage):
    # Never log exception messages, URLs, headers, payloads or user identifiers.
    details = {'stage': stage, 'category': 'unexpected'}
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        details['category'] = 'timeout'
    elif isinstance(exc, httpx.HTTPStatusError):
        details.update(category='http_status', status=exc.response.status_code)
    elif isinstance(exc, httpx.RequestError):
        details['category'] = 'network'
    elif isinstance(exc, ValueError):
        details['category'] = 'invalid_response'
    return details


@app.get('/health')
def health():
    return {'status': 'ok'}


async def process(cid, uid, update, text):
    global paused_until
    text = NAVIGATION.get(text, text)
    parts = text.split(maxsplit=1)
    command = parts[0].split('@')[0].lower() if parts else ''
    if command.startswith('/') and command not in ('/start', '/menu', '/ajuda', '/pncp', '/compras', '/licitacoes', '/atas', '/cancelar'):
        return
    source, selection = ('compras' if command == '/compras' else 'pncp'), None
    action = 'search'
    kind = 'atas' if command == '/atas' else 'licitacoes'
    if command in ('/pncp', '/compras') and len(parts) == 1:
        action = 'menu'
    elif text in CHOICES:
        source, kind = CHOICES[text]
        action = 'choose'
    elif command in ('/pncp', '/compras') and len(parts) == 2 and parts[1].lower() in KINDS:
        kind, action = parts[1].lower(), 'choose'
    elif command in ('/start', '/menu'):
        action = 'home'
    elif command in ('/ajuda', '/cancelar'):
        action = 'help' if command == '/ajuda' else 'cancel'
    query = command in ('/pncp', '/licitacoes', '/atas')
    query = action == 'search' and (query or command == '/compras')
    term = None
    invalid = False
    if query:
        try:
            term = validate_term(parts[1] if len(parts) > 1 else '')
        except ValueError:
            invalid = True
    accepted = False
    stage = 'admission'
    try:
        if not command.startswith('/') and action == 'search':
            selection = await asyncio.to_thread(store.menu_get, uid)
            if (selection and selection.get('source') in SOURCES and selection.get('kind') in KINDS):
                source, kind, query = selection['source'], selection['kind'], True
                try:
                    term = validate_term(text)
                except ValueError:
                    invalid = True
            else:
                action = 'expired'
        accepted = await asyncio.to_thread(store.admit, uid, update, query and not invalid)
        if not accepted:
            event('duplicate_update')
            return
        if not query:
            stage = 'telegram'
            if action == 'home':
                await asyncio.to_thread(store.menu_set, uid)
                await telegram_send(cid, 'Radar Público — escolha onde consultar:\n'
                                    'Toque na fonte, escolha o tipo de consulta e envie o termo.',
                                    reply_markup=home_keyboard())
            elif action == 'menu':
                await asyncio.to_thread(store.menu_set, uid)
                await telegram_send(cid, f'{SOURCES[source]} — escolha o tipo de consulta:', reply_markup=keyboard(source))
            elif action == 'choose':
                await asyncio.to_thread(store.menu_set, uid, source, kind)
                await telegram_send(cid, prompt(source, kind), reply_markup=search_keyboard(source))
            elif action == 'cancel':
                await asyncio.to_thread(store.menu_set, uid)
                await telegram_send(cid, 'Seleção encerrada. Escolha uma fonte nos botões para começar novamente.', reply_markup=home_keyboard())
            elif action == 'expired':
                await telegram_send(cid, 'Escolha a fonte nos botões e depois o tipo de consulta; a seleção expira em 10 minutos.', reply_markup=home_keyboard())
            else:
                await telegram_send(cid, HELP, reply_markup=home_keyboard())
            return
        if invalid:
            stage = 'telegram'
            await telegram_send(cid, 'Digite um termo de 2 a 120 caracteres, por exemplo: viaturas.',
                                reply_markup=search_keyboard(source) if selection else home_keyboard())
            return
        if source == 'pncp' and kind == 'licitacoes' and selection is None:
            kind = 'pncp'
        day = datetime.now(ZoneInfo('America/Sao_Paulo')).date().isoformat()
        key = cache_key(kind if source == 'pncp' else 'compras_'+kind, normalize(term), day)
        stage = 'cache_read'
        result = await asyncio.to_thread(store.cache_get, key)
        if result is None:
            event('cache_miss')
            async def reserve():
                nonlocal stage
                stage = 'budget'
                if source == 'compras':
                    await asyncio.to_thread(store.reserve, source)
                else:
                    await asyncio.to_thread(store.reserve)
                stage = source
            stage = source
            if source == 'compras':
                result = await asyncio.wait_for(compras_search(term, kind=kind, reserve=reserve), timeout=30)
            elif kind == 'pesquisa':
                async def general():
                    first = await pncp_search(term, kind='pncp', reserve=reserve)
                    second = await pncp_search(term, kind='atas', reserve=reserve)
                    second['items'] = second['items'][:2 if first['items'] else 5]
                    first['items'] = first['items'][:5-len(second['items'])]
                    return {'sections': [first, second]}
                result = await asyncio.wait_for(general(), timeout=30)
            else:
                result = await asyncio.wait_for(pncp_search(term, kind=kind, reserve=reserve), timeout=30)
            stage = 'cache_write'
            await asyncio.to_thread(store.cache_set, key, result)
        else:
            event('cache_hit')
        stage = 'format'
        message = (format_compras(result) if source == 'compras' else
                   '\n\n'.join(format_pncp(section) for section in result['sections'])
                   if kind == 'pesquisa' else format_pncp(result))
        stage = 'telegram'
        await telegram_send(cid, message, reply_markup=search_keyboard(source) if selection else home_keyboard())
        event('query_ok')
    except PNCPRateLimited as exc:
        event(source+'_rate_limited', retry_after_seconds=exc.retry_after)
        try:
            if source == 'compras':
                await asyncio.to_thread(store.defer_pncp, exc.retry_after, source)
            else:
                await asyncio.to_thread(store.defer_pncp, exc.retry_after)
        except Exception as storage_exc:
            event('dependency_failure', **failure_details(storage_exc, 'pncp_cooldown_write'))
            paused_until = time.monotonic() + exc.retry_after
        try:
            await telegram_send(cid, PNCP_LIMIT_MESSAGE if source == 'pncp' else
                'Compras.gov.br limitou o acesso (HTTP 429). Consultas à fonte pausadas. https://www.gov.br/compras')
        except Exception:
            event('telegram_failure')
    except LimitReached as exc:
        reason = str(exc)
        event('limit_' + reason)
        if reason in ('global', 'suspended', 'external'):
            paused_until = time.monotonic()+60
        await telegram_send(cid, 'Compras.gov.br limitou o acesso (HTTP 429). Consultas à fonte pausadas. https://www.gov.br/compras' if reason == 'compras' else PNCP_LIMIT_MESSAGE if reason == 'pncp' else (
            'Limite operacional atingido. Consultas temporariamente suspensas.' if reason != 'user' else 'Limite de 10 consultas em 60 minutos atingido. Tente mais tarde.'))
    except Exception as exc:
        event('dependency_failure', **failure_details(exc, stage))
        paused_until = time.monotonic()+30
        # Only admitted requests may send an error; persistence failures remain silent.
        if accepted:
            try:
                await telegram_send(cid, 'Fonte ou serviço temporariamente indisponível. Tente novamente mais tarde.')
            except Exception:
                event('telegram_failure')
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

"""Bounded official PNCP queries. Keyword filtering is local, never exhaustive."""
import os
import re
import unicodedata
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

PNCP = 'https://pncp.gov.br/api/consulta/v1'
TELEGRAM = 'https://api.telegram.org'


def normalize(term):
    return ''.join(c for c in unicodedata.normalize('NFD', term.casefold()) if not unicodedata.combining(c))


def validate_term(term):
    term = ' '.join(term.split())
    if not 2 <= len(term) <= 120 or any(ord(c) < 32 for c in term):
        raise ValueError('Informe um termo de 2 a 120 caracteres.')
    return term


def official_link(item, kind='pncp'):
    number = item.get('numeroControlePNCPCompra' if kind == 'atas' else 'numeroControlePNCP', '')
    match = re.fullmatch(r'(\d{14})-1-(\d+)/(\d{4})', str(number))
    if not match:
        return 'https://pncp.gov.br/app/atas' if kind == 'atas' else 'https://pncp.gov.br/app/editais'
    cnpj, sequence, year = match.groups()
    # Atas link to the official procurement record that owns the ata.
    return f'https://pncp.gov.br/app/editais/{cnpj}/{year}/{int(sequence)}'


async def pncp_search(term, days=7, limit=5, kind='pncp', reserve=None, client=None, today=None):
    term = validate_term(term)
    if kind not in ('pncp', 'atas') or not 1 <= days <= 30 or not 1 <= limit <= 5:
        raise ValueError('Parâmetros inválidos')
    today = today or datetime.now(ZoneInfo('America/Sao_Paulo')).date()
    params = {'dataInicial': (today-timedelta(days=days-1)).strftime('%Y%m%d'),
              'dataFinal': today.strftime('%Y%m%d'), 'tamanhoPagina': 50}
    own = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5), follow_redirects=False)
    items, seen, pages = [], set(), 0
    try:
        for modality in ((None,) if kind == 'atas' else (6, 8, 4, 5)):
            for page in (1, 2):
                query = dict(params, pagina=page)
                if modality is not None:
                    query['codigoModalidadeContratacao'] = modality
                if reserve:
                    await reserve()
                r = await client.get(f"{PNCP}/{'atas/atualizacao' if kind == 'atas' else 'contratacoes/publicacao'}", params=query)
                r.raise_for_status()
                pages += 1
                if r.status_code == 204:
                    break
                payload = r.json()
                if not isinstance(payload, dict) or not isinstance(payload.get('data'), list):
                    raise ValueError('Resposta PNCP inválida')
                total = payload.get('totalPaginas')
                if not isinstance(total, int) or isinstance(total, bool) or total < page:
                    raise ValueError('Paginação PNCP inválida')
                for item in payload['data']:
                    if not isinstance(item, dict):
                        raise ValueError('Registro PNCP inválido')
                    obj = item.get('objetoContratacao' if kind == 'atas' else 'objetoCompra') or ''
                    key = item.get('numeroControlePNCPAta' if kind == 'atas' else 'numeroControlePNCP')
                    if key and key not in seen and normalize(term) in normalize(str(obj)):
                        seen.add(key)
                        items.append(item)
                if page >= total:
                    break
    finally:
        if own:
            await client.aclose()
    return {'items': items[:limit], 'pages': pages, 'kind': kind, 'start': params['dataInicial'], 'end': params['dataFinal']}


def format_pncp(result):
    if isinstance(result, list):
        result = {'items': result, 'kind': 'pncp', 'pages': 0, 'start': '?', 'end': '?'}
    kind = result['kind']
    heading = (f"Busca amostral, não exaustiva. {result['pages']} páginas; período {result['start']} a {result['end']}. "
               + ('Atas por atualização global; não garante vigência ou adesão. Links levam à contratação de origem.' if kind == 'atas' else 'Publicações nas modalidades 6, 8, 4 e 5; até 2 páginas por modalidade.')
               + '\nMáximo de 5 resultados; filtro textual local.\n\n')
    out = []
    for x in result['items']:
        org = x.get('nomeOrgao') if kind == 'atas' else (x.get('orgaoEntidade') or {}).get('razaoSocial')
        obj = x.get('objetoContratacao' if kind == 'atas' else 'objetoCompra') or ''
        extra = f"\nAta: {str(x.get('numeroAtaRegistroPreco', ''))[:40]} | Cancelada: {x.get('cancelado', 'não informado')} | Vigência: {x.get('vigenciaFim', 'não informada')}" if kind == 'atas' else ''
        out.append(f"• {str(org or 'Órgão não informado')[:150]}\n{str(obj)[:220]}{extra}\n{official_link(x, kind)}")
    return heading + ('\n\n'.join(out) if out else 'Nenhum resultado na amostra. Isso não comprova inexistência no PNCP.')


async def telegram_send(chat_id, text, token=None):
    token = token or os.environ['TELEGRAM_BOT_TOKEN']
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
            for i in range(0, len(text), 1800):
                r = await client.post(f'{TELEGRAM}/bot{token}/sendMessage', json={'chat_id': chat_id, 'text': text[i:i+1800], 'disable_web_page_preview': True})
                r.raise_for_status()
                if not r.json().get('ok'):
                    raise ValueError('Telegram rejeitou envio')
    except Exception:
        # Never expose HTTP exceptions: Telegram request URLs contain the bot token.
        raise RuntimeError('Falha no envio Telegram') from None

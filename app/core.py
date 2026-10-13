import os, html
from datetime import date, timedelta
import httpx

PNCP = 'https://pncp.gov.br/api/consulta/v1'
TELEGRAM = 'https://api.telegram.org'

async def pncp_search(term: str, days: int = 30, limit: int = 10):
    if not term.strip() or len(term) > 120:
        raise ValueError('Informe um termo de até 120 caracteres')
    days = max(1, min(days, 90))
    end = date.today()
    start = end - timedelta(days=days)
    items = []
    async with httpx.AsyncClient(timeout=22, follow_redirects=True) as client:
        for modality in (6, 8, 4, 5):
            params = {'dataInicial': start.strftime('%Y%m%d'), 'dataFinal': end.strftime('%Y%m%d'), 'codigoModalidadeContratacao': modality, 'pagina': 1, 'tamanhoPagina': 50}
            r = await client.get(f'{PNCP}/contratacoes/publicacao', params=params)
            r.raise_for_status()
            items.extend(r.json().get('data', []))
    return [x for x in items if term.casefold() in (x.get('objetoCompra') or '').casefold()][:limit]

def format_pncp(items):
    if not items:
        return 'Nenhuma contratação encontrada na amostra consultada. Isso não comprova inexistência no PNCP.'
    out = []
    for x in items:
        org = x.get('orgaoEntidade') or {}
        number = x.get('numeroControlePNCP', '')
        link = f'https://pncp.gov.br/app/editais/{number}' if number else 'https://pncp.gov.br/app/editais'
        out.append(f"• {org.get('razaoSocial', 'Órgão não informado')}\n{str(x.get('objetoCompra', ''))[:220]}\n{link}")
    return '\n\n'.join(out)

async def telegram_send(chat_id, text, token=None):
    token = token or os.environ['TELEGRAM_BOT_TOKEN']
    async with httpx.AsyncClient(timeout=25) as client:
        for i in range(0, len(text), 3800):
            r = await client.post(f'{TELEGRAM}/bot{token}/sendMessage', json={'chat_id': chat_id, 'text': text[i:i+3800], 'disable_web_page_preview': True})
            r.raise_for_status()

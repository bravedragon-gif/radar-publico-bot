"""Bounded samples from the official Compras.gov.br OpenAPI."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import httpx
from app.core import PNCPRateLimited, normalize, official_link, retry_delay, validate_term

BASE = 'https://dadosabertos.compras.gov.br'


async def compras_search(term, kind='licitacoes', reserve=None, client=None, today=None):
    term = validate_term(term)
    if kind not in ('licitacoes', 'atas', 'pesquisa'):
        raise ValueError('Tipo inválido')
    today = today or datetime.now(ZoneInfo('America/Sao_Paulo')).date()
    start, end = (today-timedelta(days=6)).isoformat(), today.isoformat()
    requests = []
    if kind != 'atas':
        # SIASG codes differ from PNCP: e.g. 5 = pregão (PNCP 6).
        for modality in ((3, 4, 5, 6, 7) if kind == 'pesquisa' else (3, 4, 5)):
            requests.append(('/modulo-contratacoes/1_consultarContratacoes_PNCP_14133',
                {'dataPublicacaoPncpInicial': start, 'dataPublicacaoPncpFinal': end,
                 'codigoModalidade': modality}, 'licitacoes'))
    if kind != 'licitacoes':
        requests.append(('/modulo-arp/1_consultarARP',
            {'dataVigenciaInicialMin': start, 'dataVigenciaInicialMax': end}, 'atas'))
    own = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5), follow_redirects=False)
    items, seen = [], set()
    try:
        for path, params, category in requests:
            if reserve:
                await reserve()
            response = await client.get(BASE+path, params=dict(params, pagina=1, tamanhoPagina=50))
            if response.status_code == 429:
                raise PNCPRateLimited(retry_delay(response.headers.get('Retry-After')))
            response.raise_for_status()
            payload = response.json()
            if (not isinstance(payload, dict) or not isinstance(payload.get('resultado'), list)
                    or type(payload.get('totalPaginas')) is not int or payload['totalPaginas'] < 0):
                raise ValueError('Resposta Compras.gov.br inválida')
            for row in payload['resultado']:
                if not isinstance(row, dict):
                    raise ValueError('Registro inválido')
                if row.get('ataExcluido') or row.get('contratacaoExcluida'):
                    continue
                obj = row.get('objeto' if category == 'atas' else 'objetoCompra') or ''
                key = row.get('numeroControlePncpAta' if category == 'atas' else 'numeroControlePNCP')
                if key and (category, key) not in seen and normalize(term) in normalize(str(obj)):
                    seen.add((category, key))
                    link = official_link({'numeroControlePNCP': row.get('numeroControlePncpCompra')
                                          if category == 'atas' else key})
                    items.append({'kind': 'atas' if category == 'atas' else 'contratações', 'object': str(obj)[:220],
                        'org': str(row.get('nomeOrgao') or row.get('orgaoEntidadeRazaoSocial') or '')[:150],
                        'uasg': str(row.get('codigoUnidadeGerenciadora') or row.get('unidadeOrgaoCodigoUnidade') or '')[:20],
                        'link': link, 'date': str(row.get('dataVigenciaFinal') if category == 'atas'
                                                else row.get('dataPublicacaoPncp'))[:30]})
    finally:
        if own:
            await client.aclose()
    if kind == 'pesquisa':
        atas = [item for item in items if item['kind'] == 'atas']
        purchases = [item for item in items if item['kind'] != 'atas']
        selected_atas = atas[:2 if purchases else 5]
        items = purchases[:5-len(selected_atas)] + selected_atas
    return {'items': items[:5], 'pages': len(requests), 'start': start, 'end': end, 'kind': kind}


def format_compras(result):
    heading = (f"Compras.gov.br — busca amostral, não exaustiva. {result['pages']} páginas, "
        f"{result['start']} a {result['end']}. Contratações por publicação; atas por início de vigência. "
        'Filtro textual local; até 5 resultados. Atas não garantem vigência ou possibilidade de adesão.\n\n')
    return heading + ('\n\n'.join(
        f"• {x['kind']} — {x['org']} | UASG {x['uasg']}\n{x['object']}\n"
        f"{'Fim da vigência' if x['kind'] == 'atas' else 'Publicação'}: {x['date']}\n{x['link']}"
        for x in result['items']) or 'Nenhum resultado na amostra. Isso não comprova inexistência.')

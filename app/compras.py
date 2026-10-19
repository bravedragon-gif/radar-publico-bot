"""Bounded samples from the official Compras.gov.br OpenAPI."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import httpx
import json
from urllib.parse import urlencode
from decimal import Decimal, InvalidOperation
from app.core import PNCPRateLimited, normalize, official_link, retry_delay
from app.compras_filters import EXTRA_KINDS, parse_query

BASE = 'https://dadosabertos.compras.gov.br'


async def compras_search(term, kind='licitacoes', reserve=None, client=None, today=None):
    if kind not in ('licitacoes', 'atas', 'pesquisa', *EXTRA_KINDS):
        raise ValueError('Tipo inválido')
    today = today or datetime.now(ZoneInfo('America/Sao_Paulo')).date()
    term, options = parse_query(term, kind, today)
    start, end = (today-timedelta(days=options['dias']-1)).isoformat(), today.isoformat()
    if kind in EXTRA_KINDS:
        return await module_search(term, kind, options, start, end, reserve, client)
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
    for path, params, category in requests:
        if 'uasg' in options:
            params['codigoUnidadeGerenciadora' if category == 'atas' else 'unidadeOrgaoCodigoUnidade'] = options['uasg']
        if 'uf' in options:
            params['unidadeOrgaoUfSigla'] = options['uf']
        if 'orgao' in options:
            params['codigoOrgao'] = options['orgao']
    own = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5), follow_redirects=False)
    items, seen, pages = [], set(), 0
    try:
        for path, params, category in requests:
            rows, count = await fetch_pages(client, path, params, reserve)
            pages += count
            for row in rows:
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
    return {'items': items[:5], 'pages': pages, 'start': start, 'end': end, 'kind': kind, 'filters': options}


async def fetch_pages(client, path, params, reserve):
    rows, pages = [], 0
    for page in range(1, 3):
        if reserve:
            await reserve()
        response = await client.get(BASE+path, params=dict(params, pagina=page, tamanhoPagina=50))
        if response.status_code == 429:
            raise PNCPRateLimited(retry_delay(response.headers.get('Retry-After')))
        response.raise_for_status()
        payload = response.json()
        if (not isinstance(payload, dict) or not isinstance(payload.get('resultado'), list)
                or type(payload.get('totalPaginas')) is not int or payload['totalPaginas'] < 0
                or any(not isinstance(row, dict) for row in payload['resultado'])):
            raise ValueError('Resposta Compras.gov.br inválida')
        rows.extend(payload['resultado'])
        pages += 1
        if page >= payload['totalPaginas'] or not payload['resultado']:
            break
    return rows, pages


def money(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > Decimal('1e18'):
            raise ValueError()
        return 'R$ ' + f'{amount:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')
    except (InvalidOperation, ValueError, TypeError):
        return 'não informado'


async def module_search(term, kind, options, start, end, reserve, client):
    params = {}
    if kind == 'itens':
        path = '/modulo-contratacoes/2_consultarItensContratacoes_PNCP_14133'
        params.update(dataInclusaoPncpInicial=start, dataInclusaoPncpFinal=end)
    elif kind in ('materiais', 'servicos'):
        path = '/modulo-pesquisa-preco/' + ('1_consultarMaterial' if kind == 'materiais' else '3_consultarServico')
        params.update(dataCompraInicio=start, dataCompraFim=end)
        if kind == 'materiais':
            params.update(tipo='codigoItemCatalogo', codigo=term)
        else:
            params['codigoItemCatalogo'] = int(term)
        if 'uf' in options:
            params['estado'] = options['uf']
    elif kind == 'contratos':
        path = '/modulo-contratos/1_consultarContratos'
        params.update(codigoOrgao=options['orgao'], dataVigenciaInicialMin=start, dataVigenciaInicialMax=end)
    else:
        path = '/modulo-pgc/1_consultarPgcDetalhe'
        params.update(orgao=options['orgao'], anoPcaProjetoCompra=options['ano'])
    if 'uasg' in options:
        params[{'itens': 'unidadeOrgaoCodigoUnidade', 'contratos': 'codigoUnidadeGestora'}.get(kind, 'codigoUasg')] = options['uasg']
    own = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5), follow_redirects=False)
    try:
        rows, pages = await fetch_pages(client, path, params, reserve)
    finally:
        if own:
            await client.aclose()
    items, seen = [], set()
    for row in rows:
        if row.get('contratoExcluido') or row.get('dataHoraExclusao'):
            continue
        obj = (row.get('descricaoResumida') or row.get('descricaodetalhada') if kind == 'itens' else
               row.get('descricaoItem') if kind in ('materiais', 'servicos') else
               row.get('objeto') if kind == 'contratos' else
               ' '.join(str(row.get(key) or '') for key in ('descricaoObjetoDfd', 'descricaoItemCatalogo', 'tituloProjetoCompra')))
        if kind not in ('materiais', 'servicos') and normalize(term) not in normalize(str(obj or '')):
            continue
        if kind in ('materiais', 'servicos'):
            if str(row.get('codigoItemCatalogo')) != str(int(term)):
                continue
            if 'orgao' in options and str(row.get('codigoOrgao')) != options['orgao']:
                continue
        key = json.dumps(row, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        link = official_link({'numeroControlePNCP': row.get('numeroControlePNCPCompra') or row.get('numeroControlePncpCompra')})
        if link == 'https://pncp.gov.br/app/editais':
            link = BASE + path + '?' + urlencode(dict(params, pagina=1, tamanhoPagina=50))
        if kind in ('materiais', 'servicos'):
            detail = (f"Preço unitário registrado: {money(row.get('precoUnitario'))} | Quantidade: {str(row.get('quantidade', 'não informada'))[:40]}\n"
                      f"Unidade: {str(row.get('nomeUnidadeFornecimento') or row.get('nomeUnidadeMedida') or 'não informada')[:80]} | "
                      f"Capacidade: {str(row.get('capacidadeUnidadeFornecimento') or 'não informada')[:40]} {str(row.get('siglaUnidadeMedida') or '')[:20]}\n"
                      f"Fornecedor: {str(row.get('nomeFornecedor') or 'não informado')[:120]} | Compra: {str(row.get('idCompra') or '')[:60]}")
            date = row.get('dataCompra')
        elif kind == 'itens':
            estimated = 'sigiloso' if row.get('orcamentoSigiloso') else money(row.get('valorUnitarioEstimado'))
            detail = (f"Estimado unitário: {estimated}\n"
                      f"Resultado unitário: {money(row.get('valorUnitarioResultado'))} | Quantidade: {str(row.get('quantidadeResultado') or row.get('quantidade') or 'não informada')[:40]}\n"
                      f"Unidade: {str(row.get('unidadeMedida') or 'não informada')[:80]} | Situação: {str(row.get('situacaoCompraItemNome') or 'não informada')[:80]}\n"
                      f"Catálogo: {str(row.get('codItemCatalogo') or 'não informado')[:30]} ({str(row.get('materialOuServicoNome') or '')[:30]})\n"
                      f"Fornecedor: {str(row.get('nomeFornecedor') or 'não informado')[:120]} | Data resultado: {str(row.get('dataResultado') or 'não informada')[:30]}")
            date = row.get('dataInclusaoPncp')
        elif kind == 'contratos':
            detail = (f"Contrato: {str(row.get('numeroContrato') or '')[:50]} | Valor global: {money(row.get('valorGlobal'))}\n"
                      f"Fornecedor: {str(row.get('nomeRazaoSocialFornecedor') or 'não informado')[:120]}\n"
                      f"Vigência: {str(row.get('dataVigenciaInicial') or '?')[:30]} a {str(row.get('dataVigenciaFinal') or '?')[:30]}")
            date = row.get('dataVigenciaInicial')
        else:
            detail = (f"PCA: {options['ano']} | Quantidade: {str(row.get('quantidadeItem') or 'não informada')[:40]}\n"
                      f"Valor total previsto: {money(row.get('valorTotalItem'))} | Código catálogo: {str(row.get('codigoItemCatalogo') or '')[:30]}")
            date = row.get('dataPrevistaFormalizacaoDemanda')
        items.append({'kind': EXTRA_KINDS[kind], 'object': str(obj or '')[:220],
                      'org': str(row.get('nomeOrgao') or row.get('orgao') or row.get('orgaoEntidadeCnpj') or '')[:150],
                      'uasg': str(row.get('codigoUasg') or row.get('codigoUnidadeGestora') or row.get('unidadeOrgaoCodigoUnidade') or '')[:20],
                      'date': str(date or 'não informada')[:30], 'link': link, 'detail': detail})
        if len(items) == 5:
            break
    return {'items': items, 'pages': pages, 'start': start, 'end': end, 'kind': kind, 'filters': options}


def format_compras(result):
    filters = ', '.join(f'{key}={value}' for key, value in result.get('filters', {}).items() if key != 'dias')
    filter_heading = f'Filtros: {filters}.\n' if filters else ''
    if result['kind'] in EXTRA_KINDS:
        heading = (f"Compras.gov.br — {EXTRA_KINDS[result['kind']]}. Busca amostral, não exaustiva; {result['pages']} páginas.\n"
                   + (f"PCA {result.get('filters', {}).get('ano')}. Planejamento não garante publicação ou contratação.\n" if result['kind'] == 'planejamento' else
                      f"Período: {result['start']} a {result['end']}. "
                      + ('Contratos por início de vigência.\n' if result['kind'] == 'contratos' else 'Itens por inclusão; preços por data da compra.\n'))
                   + filter_heading + 'Valores exibidos são registros individuais, sem média ou equivalência automática. Confira descrição, unidade, quantidade e data.\n\n')
        return heading + ('\n\n'.join(f"• {x['object']}\n{x['org']} | UASG {x['uasg']}\n{x['detail']}\nData: {x['date']}\n{x['link']}" for x in result['items'])
                          or 'Nenhum resultado na amostra. Isso não comprova inexistência.')
    heading = (f"Compras.gov.br — busca amostral, não exaustiva. {result['pages']} páginas, "
        f"{result['start']} a {result['end']}. Contratações por publicação; atas por início de vigência. "
        'Filtro textual local; até 5 resultados. Atas não garantem vigência ou possibilidade de adesão.\n' + filter_heading + '\n')
    return heading + ('\n\n'.join(
        f"• {x['kind']} — {x['org']} | UASG {x['uasg']}\n{x['object']}\n"
        f"{'Fim da vigência' if x['kind'] == 'atas' else 'Publicação'}: {x['date']}\n{x['link']}"
        for x in result['items']) or 'Nenhum resultado na amostra. Isso não comprova inexistência.')

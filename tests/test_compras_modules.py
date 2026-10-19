import asyncio
from datetime import date
import httpx
import pytest
from app.compras import compras_search, format_compras, money
from app.compras_filters import parse_query
from app.core import PNCPRateLimited


@pytest.mark.parametrize('kind,text,path,expected,row', [
    ('itens', 'viaturas | dias=30 | uasg=123', '/modulo-contratacoes/2_consultarItensContratacoes_PNCP_14133',
     {'dataInclusaoPncpInicial': '2026-09-19', 'unidadeOrgaoCodigoUnidade': '123'},
     {'descricaoResumida': 'VIÁTURAS', 'valorUnitarioEstimado': 100, 'valorUnitarioResultado': 90, 'unidadeMedida': 'Unidade'}),
    ('materiais', '123 | dias=30 | uf=DF | orgao=12', '/modulo-pesquisa-preco/1_consultarMaterial',
     {'tipo': 'codigoItemCatalogo', 'codigo': '123', 'estado': 'DF', 'dataCompraInicio': '2026-09-19'},
     {'codigoItemCatalogo': 123, 'codigoOrgao': '12', 'descricaoItem': 'Material', 'precoUnitario': 10.25, 'quantidade': 50, 'nomeUnidadeFornecimento': 'Caixa', 'capacidadeUnidadeFornecimento': 10}),
    ('servicos', '1 | uasg=123', '/modulo-pesquisa-preco/3_consultarServico',
     {'codigoItemCatalogo': '1', 'codigoUasg': '123'},
     {'codigoItemCatalogo': 1, 'descricaoItem': 'Serviço', 'precoUnitario': 10, 'nomeUnidadeMedida': 'Hora'}),
    ('contratos', 'viaturas | orgao=123 | dias=90', '/modulo-contratos/1_consultarContratos',
     {'codigoOrgao': '123', 'dataVigenciaInicialMin': '2026-07-21'},
     {'objeto': 'Viaturas', 'numeroContrato': '1/2026', 'valorGlobal': 1000, 'nomeRazaoSocialFornecedor': 'Fornecedor', 'dataVigenciaFinal': '2027-01-01'}),
    ('planejamento', 'viaturas | orgao=123 | ano=2027', '/modulo-pgc/1_consultarPgcDetalhe',
     {'orgao': '123', 'anoPcaProjetoCompra': '2027'},
     {'descricaoObjetoDfd': 'Viaturas', 'codigoUasg': 123, 'valorTotalItem': 2000}),
])
def test_new_modules_use_official_parameters_and_preserve_details(kind, text, path, expected, row):
    calls, reservations = [], []
    async def reserve():
        reservations.append(1)
    def handler(req):
        calls.append(req)
        assert len(reservations) == len(calls)
        assert req.url.path == path
        assert all(req.url.params[key] == value for key, value in expected.items())
        # First page doesn't match; second page must actually be searched.
        return httpx.Response(200, json={'resultado': [row] if req.url.params['pagina'] == '2' else [{}], 'totalPaginas': 100})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await compras_search(text, kind, reserve, client, today=date(2026, 10, 18))
    result = asyncio.run(run())
    assert len(calls) == len(reservations) == result['pages'] == 2
    assert len(result['items']) == 1
    message = format_compras(result)
    assert 'não exaustiva' in message and 'R$' in message
    assert 'https://dadosabertos.compras.gov.br/' in message
    if kind == 'materiais':
        assert 'Caixa' in message and '50' in message and 'R$ 10,25' in message
    if kind == 'contratos':
        assert 'Fornecedor' in message and '2027-01-01' in message
    if kind == 'planejamento':
        assert 'PCA 2027' in message and 'não garante' in message


@pytest.mark.parametrize('kind,text', [
    ('contratos', 'viaturas'), ('planejamento', 'viaturas'),
    ('materiais', 'viaturas'), ('servicos', '0'), ('materiais', '1 | uf=ZZ'),
    ('licitacoes', 'viaturas | dias=91'), ('licitacoes', 'viaturas | dias=-1'),
    ('licitacoes', 'viaturas | dias=1 | dias=30'), ('licitacoes', 'viaturas | pagina=200'),
    ('atas', 'viaturas | uf=DF'), ('pesquisa', 'viaturas | orgao=123'),
    ('itens', 'viaturas | uf=DF'), ('itens', 'viaturas | orgao=123'),
    ('contratos', 'viaturas | orgao=abc'), ('licitacoes', 'viaturas | ano=2027'),
    ('planejamento', 'viaturas | orgao=123 | dias=30'),
    ('planejamento', 'viaturas | orgao=123 | ano=9999'),
])
def test_invalid_filters_do_not_access_api(kind, text):
    def handler(req):
        pytest.fail('Invalid input must not reach the API')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await compras_search(text, kind, client=client)
    with pytest.raises(ValueError):
        asyncio.run(run())


def test_filters_are_normalized_and_default_year_is_current():
    assert parse_query('viaturas | uf=df | dias=30', 'licitacoes')[1] == {'uf': 'DF', 'dias': 30}
    assert parse_query('viaturas | orgao=123', 'planejamento', date(2026, 10, 18))[1]['ano'] == 2026


def test_remote_filters_and_stop_on_last_page():
    calls = []
    def handler(req):
        calls.append(req)
        assert req.url.params['unidadeOrgaoUfSigla'] == 'DF'
        assert req.url.params['codigoOrgao'] == '123'
        assert req.url.params['unidadeOrgaoCodigoUnidade'] == '456'
        assert req.url.params['dataPublicacaoPncpInicial'] == '2026-09-19'
        return httpx.Response(200, json={'resultado': [], 'totalPaginas': 0})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await compras_search('viaturas | dias=30 | uf=DF | orgao=123 | uasg=456', client=client, today=date(2026, 10, 18))
    assert asyncio.run(run())['pages'] == len(calls) == 3


@pytest.mark.parametrize('status,payload,error', [
    (429, {}, PNCPRateLimited), (503, {}, httpx.HTTPStatusError),
    (200, {'resultado': [None], 'totalPaginas': 1}, ValueError),
    (200, {'resultado': [], 'totalPaginas': True}, ValueError),
])
def test_new_module_failures_stop_without_retry(status, payload, error):
    calls = []
    def handler(req):
        calls.append(req)
        return httpx.Response(status, json=payload)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await compras_search('1', 'materiais', client=client)
    with pytest.raises(error):
        asyncio.run(run())
    assert len(calls) == 1


def test_duplicates_excluded_contracts_and_limit():
    rows = [{'objeto': 'viaturas', 'numeroContrato': str(i), 'valorGlobal': i} for i in range(8)]
    rows.insert(0, {'objeto': 'viaturas', 'contratoExcluido': True})
    def handler(req):
        return httpx.Response(200, json={'resultado': rows, 'totalPaginas': 2})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await compras_search('viaturas | orgao=123', 'contratos', client=client)
    result = asyncio.run(run())
    assert len(result['items']) == 5
    assert len({x['detail'] for x in result['items']}) == 5


@pytest.mark.parametrize('value', [None, 'NaN', 'Infinity', -1, True, 'invalid'])
def test_invalid_prices_are_never_rendered_as_zero(value):
    assert money(value) == 'não informado'


def test_zero_price_is_preserved():
    assert money(0) == 'R$ 0,00'


def test_budget_denial_prevents_second_page():
    calls, attempts = [], []
    async def reserve():
        attempts.append(1)
        if len(attempts) == 2:
            raise RuntimeError('budget exhausted')
    def handler(req):
        calls.append(req)
        return httpx.Response(200, json={'resultado':[{'codigoItemCatalogo':1}], 'totalPaginas':100})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await compras_search('1', 'materiais', reserve, client)
    with pytest.raises(RuntimeError):
        asyncio.run(run())
    assert len(calls) == 1


def test_second_page_error_does_not_return_partial_results():
    calls = []
    def handler(req):
        calls.append(req)
        if len(calls) == 2:
            return httpx.Response(429)
        return httpx.Response(200, json={'resultado':[{'codigoItemCatalogo':1}], 'totalPaginas':100})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await compras_search('1', 'materiais', client=client)
    with pytest.raises(PNCPRateLimited):
        asyncio.run(run())
    assert len(calls) == 2


def test_price_orgao_filter_and_duplicate_pages():
    rows = [{'codigoItemCatalogo':1, 'codigoOrgao':12, 'precoUnitario':3},
            {'codigoItemCatalogo':1, 'codigoOrgao':99, 'precoUnitario':4}]
    def handler(req):
        return httpx.Response(200, json={'resultado':rows, 'totalPaginas':10})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await compras_search('1 | orgao=12', 'materiais', client=client)
    result = asyncio.run(run())
    assert len(result['items']) == 1 and 'R$ 3,00' in result['items'][0]['detail']


def test_confidential_estimate_is_not_displayed():
    def handler(req):
        return httpx.Response(200, json={'resultado':[{'descricaoResumida':'viaturas', 'orcamentoSigiloso':True, 'valorUnitarioEstimado':999}], 'totalPaginas':1})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await compras_search('viaturas', 'itens', client=client)
    message = format_compras(asyncio.run(run()))
    assert 'sigiloso' in message and '999' not in message

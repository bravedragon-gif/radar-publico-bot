import asyncio
from datetime import date

import httpx
import pytest
from app.core import PNCPRateLimited, retry_delay, format_pncp, official_link, pncp_search, telegram_send, validate_term


def run(coro):
    return asyncio.run(coro)


def test_empty_sample_disclaimer():
    assert 'amostra' in format_pncp([])


@pytest.mark.parametrize('term', ['', 'x', 'x'*121, '\x00a'])
def test_invalid_term(term):
    with pytest.raises(ValueError):
        validate_term(term)


def test_official_links():
    assert official_link({'numeroControlePNCP': '00394460000141-1-000023/2026'}) == 'https://pncp.gov.br/app/editais/00394460000141/2026/23'
    assert official_link({'numeroControlePNCP': 'https://evil.test'}) == 'https://pncp.gov.br/app/editais'


@pytest.mark.parametrize('kind,expected', [('pncp', 8), ('atas', 2)])
def test_pagination_parameters_and_limits(kind, expected):
    calls, reservations = [], []
    async def reserve():
        reservations.append(1)
    def handler(req):
        calls.append(req)
        q = req.url.params
        assert q['dataInicial'] == '20261011' and q['dataFinal'] == '20261017'
        assert q['tamanhoPagina'] == '50'
        assert q['pagina'] in ('1', '2')
        key = 'numeroControlePNCPAta' if kind == 'atas' else 'numeroControlePNCP'
        obj = 'objetoContratacao' if kind == 'atas' else 'objetoCompra'
        return httpx.Response(200, json={'data': [{key: str(len(calls)), obj: 'Aquisição de VIÁTURAS'}], 'totalPaginas': 20})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await pncp_search('viaturas', kind=kind, client=client, reserve=reserve, today=date(2026,10,17))
    result = run(scenario())
    assert len(calls) == len(reservations) == expected
    assert len(result['items']) <= 5
    assert 'não exaustiva' in format_pncp(result)
    if kind == 'atas':
        assert all(x.url.path.endswith('/atas/atualizacao') for x in calls)
        assert 'codigoModalidadeContratacao' not in calls[0].url.params


@pytest.mark.parametrize('status,payload', [(429, {}), (500, {}), (200, {'data': {}}), (200, {'data': [], 'totalPaginas': -1})])
def test_external_failures(status,payload):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(status,json=payload))) as client:
            return await pncp_search('viaturas',client=client)
    with pytest.raises((ValueError,httpx.HTTPError,PNCPRateLimited)):
        run(scenario())


@pytest.mark.parametrize('header,expected', [(None,300), ('invalid',300), ('120',120), ('0',60),
    ('Thu, 01 Jan 1970 00:10:00 GMT',500)])
def test_retry_after(header,expected):
    assert retry_delay(header,now=100) == expected


def test_429_stops_without_retry_or_partial_result():
    calls = []
    def handler(req):
        calls.append(req)
        return httpx.Response(429,headers={'Retry-After':'600'})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await pncp_search('viaturas',client=client)
    with pytest.raises(PNCPRateLimited) as exc:
        run(scenario())
    assert exc.value.retry_after == 600 and len(calls) == 1


def test_no_content():
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(204))) as client:
            return await pncp_search('viaturas',kind='atas',client=client)
    assert run(scenario())['items'] == []


def test_telegram_error_is_sanitized(monkeypatch):
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'never-print-this')
    class Broken:
        async def __aenter__(self):
            raise RuntimeError('https://api.telegram.org/botnever-print-this')
        async def __aexit__(self,*a):
            pass
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw: Broken())
    with pytest.raises(RuntimeError) as exc:
        run(telegram_send(1,'hello'))
    assert 'never-print-this' not in str(exc.value)

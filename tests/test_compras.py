import asyncio
from datetime import date
import httpx
import pytest
from app.compras import compras_search, format_compras
from app.core import PNCPRateLimited


@pytest.mark.parametrize('kind,count', [('licitacoes',3),('atas',1),('pesquisa',6)])
def test_official_parameters_and_sample(kind,count):
    calls,reservations=[],[]
    async def reserve():
        reservations.append(1)
    def handler(req):
        calls.append(req)
        assert req.url.host == 'dadosabertos.compras.gov.br'
        assert req.url.params['pagina'] == '1' and req.url.params['tamanhoPagina'] == '50'
        ata='/modulo-arp/' in req.url.path
        if not ata:
            assert int(req.url.params['codigoModalidade']) in ({3,4,5,6,7} if kind == 'pesquisa' else {3,4,5})
        assert req.url.params['dataVigenciaInicialMin' if ata else 'dataPublicacaoPncpInicial'] == '2026-10-12'
        assert req.url.params['dataVigenciaInicialMax' if ata else 'dataPublicacaoPncpFinal'] == '2026-10-18'
        row=({'objeto':'Aquisição de VIÁTURAS','numeroControlePncpAta':'ata1',
              'numeroControlePncpCompra':'00394460000141-1-000023/2026',
              'linkCompraPNCP':'https://evil.test'} if ata else
             {'objetoCompra':'Aquisição de VIÁTURAS',
              'numeroControlePNCP':f'00394460000141-1-00000{len(calls)}/2026'})
        return httpx.Response(200,json={'resultado':[row], 'totalPaginas':100})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await compras_search('viaturas',kind,reserve,c,today=date(2026,10,18))
    result=asyncio.run(run())
    assert len(calls) == len(reservations) == count
    assert len(result['items']) <= 5
    assert 'não exaustiva' in format_compras(result)
    assert 'evil.test' not in format_compras(result)


@pytest.mark.parametrize('status,payload,error', [
    (200,{'resultado':[], 'totalPaginas':0},None),
    (200,{'resultado':{}, 'totalPaginas':0},ValueError),
    (503,{},httpx.HTTPStatusError), (429,{},PNCPRateLimited)])
def test_failures_and_empty_results(status,payload,error):
    calls=[]
    def handler(req):
        calls.append(req)
        return httpx.Response(status,json=payload,headers={'Retry-After':'600'})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await compras_search('viaturas','pesquisa',client=c)
    if error:
        with pytest.raises(error):
            asyncio.run(run())
        assert len(calls) == 1
    else:
        assert asyncio.run(run())['items'] == []

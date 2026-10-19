from datetime import datetime, timezone
import httpx
import asyncio
import pytest
from app import news_sources as ns

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)


def test_rdf_feed_dates_and_namespaces():
    xml = b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/"><item><title>Compras publicas</title><link>https://www.gov.br/compras/pt-br/noticias/item</link><dc:date>2026-10-16T12:00:00Z</dc:date></item></rdf:RDF>'
    assert len(ns.parse_feed(xml, NOW)) == 1


@pytest.mark.parametrize('title', ['Solicitações de opção pelo Simples Nacional',
    'Defesa de Mestrado sobre Contratações Públicas', 'Pagamentos do Bolsa Família', 'Contratação de um funcionário pelo MEI'])
def test_irrelevant_titles_do_not_match_contract_or_finance_terms(title):
    assert ns.classification(title) is None


@pytest.mark.parametrize('title', ['TCU examina licitações de engenharia', 'Fiscalização de contratos de frota',
    'Auditoria avalia governança e transparência', 'Controles de segurança cibernética', 'Resultado do Tesouro Nacional'])
def test_operational_topics_are_selected(title):
    assert ns.classification(title)


def test_gov_page_title_description_and_brazilian_publication_date():
    html = '<h1>Contrato público</h1><p class="documentDescription">Texto <strong>oficial</strong>.</p><span property="rnews:datePublished">16/10/2026 12h30</span>'
    item = ns.verify_article(html.encode(), {'title': 'Contrato público', 'url': 'https://www.gov.br/compras/pt-br/item'}, 'Compras', NOW)
    assert item['excerpt'] == 'Texto oficial .'
    assert item['published'] == '2026-10-16T15:30:00+00:00'


def test_jsonld_publication_date_not_modification_date():
    page = b'<h1>Auditoria de governanca</h1><script type="application/ld+json">{"datePublished":"2020-01-01T12:00:00Z","dateModified":"2026-10-19T12:00:00Z"}</script>'
    assert ns.verify_article(page, {'url':'https://portal.tcu.gov.br/imprensa/noticias/audit'}, 'TCU', NOW) is None


def test_listing_rejects_navigation_and_external_links():
    page = b'<a href="https://evil.test/x">fake</a><a href="/fazenda/pt-br/assuntos/noticias/2026">folder</a><a href="/fazenda/pt-br/assuntos/noticias/2026/outubro/contratos">news</a>'
    items = ns.listing_links(page, 'https://www.gov.br/fazenda/pt-br/assuntos/noticias/2026')
    assert len(items) == 1 and items[0]['url'].endswith('/contratos')
    with pytest.raises(ValueError):
        ns.listing_links(b'<h1>Login</h1>', 'https://www.gov.br/fazenda/pt-br/assuntos/noticias/2026')


def test_title_must_match_feed_and_date_must_exist():
    with pytest.raises(ValueError):
        ns.verify_article(b'<h1>Login</h1>', {'title':'Contrato', 'published':NOW.isoformat()}, 'Compras', NOW)
    with pytest.raises(ValueError):
        ns.verify_article(b'<h1>Contrato</h1>', {'url':'https://www.gov.br/compras/pt-br/x'}, 'Compras', NOW)


@pytest.mark.parametrize('url', ['http://www.gov.br/compras/pt-br/x', 'https://www.gov.br.evil.test/compras/pt-br/x',
    'https://user@www.gov.br/compras/pt-br/x', 'https://www.gov.br:443/compras/pt-br/x',
    'https://www.gov.br/compras/pt-br/x?token=abc'])
def test_only_allowlisted_urls(url):
    assert not ns.official_url(url)


def test_canonical_id_ignores_tracking_and_trailing_slash():
    assert ns.article_id('https://www.gov.br/compras/pt-br/x/?utm_source=feed') == ns.article_id('https://www.gov.br/compras/pt-br/x')


def test_oversized_response_is_blocked(monkeypatch):
    monkeypatch.setattr(ns, 'MAX_BYTES', 10)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=b'x'*11))) as c:
            return await ns.fetch(c, 'https://portal.tcu.gov.br/rss.xml')
    with pytest.raises(ValueError):
        asyncio.run(run())


@pytest.mark.parametrize('content', [b'<rss/>', b'<rss><channel><item><title>Contrato</title></item></channel></rss>'])
def test_broken_feed_is_not_an_empty_success(content):
    with pytest.raises(ValueError):
        ns.parse_feed(content, NOW)

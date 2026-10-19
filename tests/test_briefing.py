import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest
from app import briefing
from app.news_sources import article_id

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
FEED = 'https://www.gov.br/compras/pt-br/feed/RSS'


@pytest.fixture(autouse=True)
def one_source(monkeypatch):
    monkeypatch.setattr(briefing, 'SOURCES', (('Compras', FEED, 'rss'),))


def feed(count=5, when=NOW, host='www.gov.br'):
    return ('<rss><channel>' + ''.join(
        f'<item><title>Contrato público {i}</title><link>https://{host}/compras/pt-br/noticias/{i}</link>'
        f'<pubDate>{format_datetime(when)}</pubDate></item>' for i in range(count)) + '</channel></rss>').encode()


def generate(content=None, seen=None, handler=None):
    def default(req):
        if str(req.url) == FEED:
            return httpx.Response(200, content=content if content is not None else feed())
        i = req.url.path.rsplit('/', 1)[-1]
        return httpx.Response(200, text=f'<h1>Contrato público {i}</h1><p class="documentDescription">Resumo oficial do contrato {i}.</p>')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler or default)) as client:
            return await briefing.generate_briefing(client=client, now=NOW, seen=seen)
    return asyncio.run(run())


def save(tmp_path, draft):
    path = tmp_path / 'briefing.json'
    path.write_text(json.dumps(draft), encoding='utf-8')
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_verified_titles_excerpts_and_editorial_guidance():
    draft = generate()
    assert len(draft['items']) == 5
    assert len({x['url'] for x in draft['items']}) == 5
    assert all(len(x['page_sha256']) == 64 for x in draft['items'])
    text = briefing.render(draft)
    assert 'Trecho oficial: Resumo oficial' in text
    assert 'Ponto de atenção sugerido' in text and 'não criam obrigações' in text


def test_lookback_is_seven_days_and_never_uses_old_or_future_news():
    assert len(generate(feed(when=NOW-timedelta(days=6)))['items']) == 5
    assert generate(feed(when=NOW-timedelta(days=8)))['items'] == []
    assert generate(feed(when=NOW+timedelta(hours=1)))['items'] == []


def test_history_skips_sent_urls_before_page_fetch():
    seen = {article_id(f'https://www.gov.br/compras/pt-br/noticias/{i}') for i in range(5)}
    draft = generate(feed(7), seen=seen)
    assert [x['title'] for x in draft['items']] == ['Contrato público 5', 'Contrato público 6']


def test_all_seen_is_not_collection_failure():
    seen = {article_id(f'https://www.gov.br/compras/pt-br/noticias/{i}') for i in range(5)}
    draft = generate(seen=seen)
    assert draft['status'] == 'ok' and not draft['items']
    assert 'ainda não enviada' in briefing.render(draft)


@pytest.mark.parametrize('content', [b'<html><body>Login</body></html>',
    b'<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///secret">]><rss>&x;</rss>'])
def test_login_and_unsafe_xml_are_source_failures(content):
    draft = generate(content)
    assert draft['status'] == 'unavailable'
    text = briefing.render(draft)
    assert 'Coleta indisponível' in text and 'não significa ausência' in text


def test_all_sources_down_yields_operational_warning():
    draft = generate(handler=lambda req: httpx.Response(503))
    assert draft['status'] == 'unavailable' and not draft['items']


def test_partial_failure_keeps_valid_source(monkeypatch):
    monkeypatch.setattr(briefing, 'SOURCES', (('Compras', FEED, 'rss'), ('TCU', 'https://portal.tcu.gov.br/rss.xml', 'rss')))
    def handler(req):
        if req.url.host == 'portal.tcu.gov.br':
            return httpx.Response(503)
        if str(req.url) == FEED:
            return httpx.Response(200, content=feed(1))
        return httpx.Response(200, text='<h1>Contrato público 0</h1>')
    draft = generate(handler=handler)
    assert draft['status'] == 'partial' and len(draft['items']) == 1
    assert 'TCU' in briefing.render(draft)


def test_page_failures_are_not_reported_as_no_news():
    def handler(req):
        return httpx.Response(200, content=feed()) if str(req.url) == FEED else httpx.Response(503)
    draft = generate(handler=handler)
    assert draft['status'] == 'partial'
    assert 'falha de coleta ou verificação' in briefing.render(draft)


def test_fewer_than_five_allowed():
    assert len(generate(feed(2))['items']) == 2


def test_publication_requires_enable_and_matching_digest(tmp_path, monkeypatch):
    path, digest = save(tmp_path, generate())
    monkeypatch.delenv('BRIEFING_PUBLICATION_ENABLED', raising=False)
    with pytest.raises(ValueError, match='bloqueada'):
        asyncio.run(briefing.publish(path, digest, now=NOW))
    monkeypatch.setenv('BRIEFING_PUBLICATION_ENABLED', 'true')
    with pytest.raises(ValueError, match='bloqueada'):
        asyncio.run(briefing.publish(path, '0'*64, now=NOW))


def test_daily_publication_claims_urls_before_send_and_confirms_after(tmp_path, monkeypatch):
    now = datetime(2026, 10, 20, 2, 59, tzinfo=timezone.utc)
    draft = generate(feed(1)); draft['generated_at'] = now.isoformat()
    path, digest = save(tmp_path, draft)
    monkeypatch.setenv('BRIEFING_PUBLICATION_ENABLED', 'true')
    events, days, urls = [], set(), set()
    def claim(day, sha, ids, stamp):
        if day in days or urls.intersection(ids):
            raise ValueError('claimed')
        days.add(day); urls.update(ids); events.append(('claim', day))
    async def send(channel, text):
        assert channel == '@logisticapmdf'
        events.append(('send', channel))
    monkeypatch.setattr(briefing.store, 'claim_news_publication', claim)
    monkeypatch.setattr(briefing.store, 'finish_news_publication', lambda day, sha: events.append(('sent', day)))
    monkeypatch.setattr(briefing, 'telegram_send', send)
    asyncio.run(briefing.publish(path, digest, now=now))
    assert [x[0] for x in events] == ['claim', 'send', 'sent']
    assert days == {'2026-10-19'}
    # Crossing Brazilian midnight does not allow yesterday's URLs to be repeated.
    with pytest.raises(ValueError, match='claimed'):
        asyncio.run(briefing.publish(path, digest, now=now+timedelta(minutes=2)))
    assert len(events) == 3


def test_telegram_failure_does_not_mark_sent_or_release_claim(tmp_path, monkeypatch):
    path, digest = save(tmp_path, generate(feed(1)))
    monkeypatch.setenv('BRIEFING_PUBLICATION_ENABLED', 'true')
    claims, finished = [], []
    monkeypatch.setattr(briefing.store, 'claim_news_publication', lambda *args: claims.append(args))
    monkeypatch.setattr(briefing.store, 'finish_news_publication', lambda *args: finished.append(args))
    async def fail(*args):
        raise RuntimeError('Telegram error')
    monkeypatch.setattr(briefing, 'telegram_send', fail)
    with pytest.raises(RuntimeError):
        asyncio.run(briefing.publish(path, digest, now=NOW))
    assert len(claims) == 1 and finished == []


@pytest.mark.parametrize('change', ['old', 'unofficial', 'duplicate', 'schema'])
def test_publish_rejects_bad_preview(tmp_path, monkeypatch, change):
    draft = generate(feed(1))
    if change == 'old': draft['items'][0]['published'] = (NOW-timedelta(days=8)).isoformat()
    if change == 'unofficial': draft['items'][0]['url'] = 'https://evil.test/news'
    if change == 'duplicate': draft['items'].append(draft['items'][0])
    if change == 'schema': draft['schema_version'] = 1
    path, digest = save(tmp_path, draft)
    monkeypatch.setenv('BRIEFING_PUBLICATION_ENABLED', 'true')
    with pytest.raises(ValueError):
        asyncio.run(briefing.publish(path, digest, now=NOW))


def test_history_read_failure_prevents_generation(monkeypatch):
    import sys
    monkeypatch.setattr(sys, 'argv', ['briefing', '--history'])
    def fail():
        raise RuntimeError('Storage unavailable')
    monkeypatch.setattr(briefing.store, 'news_history_get', fail)
    async def unexpected(**kwargs):
        pytest.fail('Collection must not run without publication history')
    monkeypatch.setattr(briefing, 'generate_briefing', unexpected)
    with pytest.raises(RuntimeError, match='Storage unavailable'):
        asyncio.run(briefing.main())


def test_live_reads_are_bounded_even_with_many_eligible_articles():
    calls = []
    def handler(req):
        calls.append(str(req.url))
        if str(req.url) == FEED:
            return httpx.Response(200, content=feed(50))
        index = req.url.path.rsplit('/', 1)[-1]
        return httpx.Response(200, text=f'<h1>Contrato público {index}</h1>')
    assert len(generate(handler=handler)['items']) == 5
    assert len(calls) <= 1 + briefing.MAX_CANDIDATES

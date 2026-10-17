import asyncio
import hashlib
import json
from datetime import datetime, timezone
from email.utils import format_datetime

import httpx
import pytest
from app import briefing

NOW=datetime(2026,10,17,12,tzinfo=timezone.utc)


def feed(count=5,age='fresh',host='www.gov.br'):
    date = NOW if age == 'fresh' else datetime(2020,1,1,tzinfo=timezone.utc)
    return ('<rss><channel>'+''.join(f'<item><title>Contrato público {i}</title><link>https://{host}/compras/pt-br/noticias/{i}</link><pubDate>{format_datetime(date)}</pubDate></item>' for i in range(count))+'</channel></rss>').encode()


def generate(content):
    def handler(req):
        if req.url.path.endswith('/RSS'):
            return httpx.Response(200,content=content)
        i=req.url.path.rsplit('/',1)[-1]
        return httpx.Response(200,text=f'<h1>Contrato público {i}</h1>')
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await briefing.generate_briefing(client=client,now=NOW)
    return asyncio.run(scenario())


def test_five_verified_original_titles():
    draft=generate(feed())
    assert len(draft['items']) == 5
    assert len({x['url'] for x in draft['items']}) == 5
    assert all(len(x['page_sha256'])==64 for x in draft['items'])
    assert 'sem IA' in briefing.render(draft)


@pytest.mark.parametrize('content',[feed(4),feed(age='old'),feed(host='evil.test')])
def test_missing_stale_or_unofficial_fails_closed(content):
    with pytest.raises(ValueError):
        generate(content)


def test_xml_entities_rejected():
    with pytest.raises(Exception):
        generate(b'<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///secret">]><rss>&x;</rss>')


def test_publication_requires_approval(tmp_path,monkeypatch):
    path=tmp_path/'draft.json'
    path.write_text(json.dumps(generate(feed())),encoding='utf-8')
    monkeypatch.delenv('BRIEFING_PUBLICATION_ENABLED',raising=False)
    with pytest.raises(ValueError,match='bloqueada'):
        asyncio.run(briefing.publish(path,hashlib.sha256(path.read_bytes()).hexdigest(),now=NOW))

def test_publish_claim_and_duplicate_block(tmp_path,monkeypatch):
    path=tmp_path/'draft.json'
    path.write_text(json.dumps(generate(feed())),encoding='utf-8')
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setenv('BRIEFING_PUBLICATION_ENABLED','true')
    claims=[]
    def claim(week,sha):
        if claims:
            raise ValueError('claimed')
        claims.append((week,sha))
    sent=[]
    async def send(channel,text):
        sent.append((channel,text))
    monkeypatch.setattr(briefing.store,'claim_publication',claim)
    monkeypatch.setattr(briefing,'telegram_send',send)
    asyncio.run(briefing.publish(path,digest,now=NOW))
    with pytest.raises(ValueError):
        asyncio.run(briefing.publish(path,digest,now=NOW))
    assert len(sent)==1 and sent[0][0]=='@logisticapmdf'
    assert claims==[('2026-W42',digest)]


def test_publish_rejects_wrong_digest(tmp_path,monkeypatch):
    path=tmp_path/'draft.json'
    path.write_text(json.dumps(generate(feed())),encoding='utf-8')
    monkeypatch.setenv('BRIEFING_PUBLICATION_ENABLED','true')
    with pytest.raises(ValueError):
        asyncio.run(briefing.publish(path,'0'*64,now=NOW))

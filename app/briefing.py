"""Deterministic official-news digest. Preview by default; never invent missing news."""
import argparse
import asyncio
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import urlparse

import httpx
from defusedxml import ElementTree
from app.core import normalize, telegram_send
from app.rate_limit import store

FEEDS = (
    'https://www.gov.br/gestao/pt-br/assuntos/noticias/RSS',
    'https://www.gov.br/compras/pt-br/acesso-a-informacao/noticias/RSS',
)
TOPICS = ('licitac', 'contrat', 'logistic', 'compras', 'orcament', 'financas', 'fiscal', 'tesouro', 'registro de precos')
MAX_BYTES = 2_000_000


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
    def handle_data(self, data):
        self.parts.append(data)


def official_url(url):
    p = urlparse(url)
    return p.scheme == 'https' and p.netloc == 'www.gov.br' and p.path.startswith(('/gestao/', '/compras/')) and not p.query and not p.fragment


async def fetch(client, url):
    async with client.stream('GET', url) as response:
        response.raise_for_status()
        content = bytearray()
        async for chunk in response.aiter_bytes():
            content.extend(chunk)
            if len(content) > MAX_BYTES:
                raise ValueError('Fonte excede tamanho permitido')
    return bytes(content)


def parse_feed(content, now):
    root = ElementTree.fromstring(content)
    items = []
    for entry in root.findall('.//item')[:50]:
        title = ' '.join(unescape(entry.findtext('title') or '').split())
        url = (entry.findtext('link') or '').strip()
        try:
            published = parsedate_to_datetime(entry.findtext('pubDate') or '')
            if published.tzinfo is None:
                continue
        except (ValueError, TypeError):
            continue
        if (official_url(url) and now-timedelta(days=7) <= published <= now
                and any(topic in normalize(title) for topic in TOPICS)):
            items.append({'title': title[:300], 'url': url, 'published': published.isoformat()})
    return items


async def generate_briefing(client=None, now=None):
    now = now or datetime.now(timezone.utc)
    own = client is None
    client = client or httpx.AsyncClient(timeout=10, follow_redirects=False)
    try:
        candidates = {}
        for feed in FEEDS:
            for item in parse_feed(await fetch(client, feed), now):
                candidates[item['url']] = item
        selected, titles = [], set()
        for item in sorted(candidates.values(), key=lambda x:x['published'], reverse=True)[:15]:
            if normalize(item['title']) in titles:
                continue
            page = await fetch(client, item['url'])
            parser = PageText()
            parser.feed(page.decode('utf-8'))
            if normalize(item['title']) not in normalize(' '.join(' '.join(parser.parts).split())):
                continue
            titles.add(normalize(item['title']))
            selected.append(dict(item, page_sha256=hashlib.sha256(page).hexdigest()))
            if len(selected) == 5:
                break
        if len(selected) != 5:
            raise ValueError(f'Briefing bloqueado: apenas {len(selected)} notícias recentes verificadas; exigidas 5.')
        return {'generated_at': now.isoformat(), 'sources': list(FEEDS), 'items': selected}
    finally:
        if own:
            await client.aclose()


def render(draft):
    return 'Radar Público — briefing semanal\nSeleção de fontes oficiais; títulos originais, sem IA.\n\n' + '\n\n'.join(
        f"{i}. {x['title']}\nPublicada em {x['published'][:10]}\n{x['url']}" for i,x in enumerate(draft['items'], 1))


async def publish(path, approved_sha, now=None):
    raw = Path(path).read_bytes()
    if os.getenv('BRIEFING_PUBLICATION_ENABLED') != 'true' or hashlib.sha256(raw).hexdigest() != approved_sha:
        raise ValueError('Publicação bloqueada: habilitação e SHA256 revisado obrigatórios')
    draft = json.loads(raw)
    now = now or datetime.now(timezone.utc)
    age = now-datetime.fromisoformat(draft['generated_at'])
    if not timedelta(0) <= age <= timedelta(hours=24) or len(draft['items']) != 5:
        raise ValueError('Prévia expirada ou inválida')
    if not all(official_url(x['url']) for x in draft['items']):
        raise ValueError('Fonte não permitida')
    week = now.astimezone(ZoneInfo('America/Sao_Paulo')).strftime('%G-W%V')
    await asyncio.to_thread(store.claim_publication, week, approved_sha)
    await telegram_send('@logisticapmdf', render(draft))


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='artifacts/briefing.json')
    parser.add_argument('--publish')
    parser.add_argument('--approved-sha')
    args = parser.parse_args()
    if args.publish:
        await publish(args.publish, args.approved_sha)
        return
    draft = await generate_briefing()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding='utf-8')
    path.with_suffix('.txt').write_text(render(draft), encoding='utf-8')
    print('Prévia gerada. SHA256:', hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception:
        raise SystemExit('Briefing bloqueado: geração ou publicação falhou. Revise as fontes e a prévia.') from None

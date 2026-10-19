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
    'https://www.gov.br/compras/pt-br/acesso-a-informacao/comunicados/comunicados-de-2026/RSS',
    'https://agenciabrasil.ebc.com.br/rss/economia/feed.xml',
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
    allowed = (p.netloc == 'www.gov.br' and p.path.startswith(('/gestao/', '/compras/')) or
               p.netloc == 'agenciabrasil.ebc.com.br' and p.path.startswith('/economia/noticia/'))
    return p.scheme == 'https' and allowed and not p.query and not p.fragment


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
    entries = root.findall('.//item') + root.findall('.//{http://purl.org/rss/1.0/}item')
    if root.tag not in ('rss', '{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF'):
        raise ValueError('Formato de feed inválido')
    for entry in entries[:50]:
        def field(name):
            return entry.findtext(name) or entry.findtext('{http://purl.org/rss/1.0/}'+name) or ''
        title = ' '.join(unescape(field('title')).split())
        url = field('link').strip()
        try:
            date = field('pubDate')
            published = (parsedate_to_datetime(date) if date else
                         datetime.fromisoformat(entry.findtext('{http://purl.org/dc/elements/1.1/}date') or ''))
            if published.tzinfo is None:
                continue
        except (ValueError, TypeError):
            continue
        if (official_url(url) and now-timedelta(hours=24) <= published <= now
                and any(topic in normalize(title) for topic in TOPICS)):
            items.append({'title': title[:300], 'url': url, 'published': published.isoformat()})
    return items


async def generate_briefing(client=None, now=None):
    now = now or datetime.now(timezone.utc)
    own = client is None
    client = client or httpx.AsyncClient(timeout=10, follow_redirects=False, headers={
        'User-Agent': 'RadarPublico/1.0 (+https://github.com/bravedragon-gif/radar-publico-bot)'})
    try:
        candidates = {}
        available, unavailable = [], []
        for feed in FEEDS:
            try:
                items = parse_feed(await fetch(client, feed), now)
            except (httpx.HTTPError, ValueError, ElementTree.ParseError):
                unavailable.append(feed)
                continue
            available.append(feed)
            for item in items:
                candidates[item['url']] = item
        if not available:
            raise ValueError('Nenhuma fonte disponível')
        selected, titles = [], set()
        for item in sorted(candidates.values(), key=lambda x:x['published'], reverse=True)[:15]:
            if normalize(item['title']) in titles:
                continue
            try:
                page = await fetch(client, item['url'])
            except httpx.HTTPError:
                continue
            parser = PageText()
            parser.feed(page.decode('utf-8'))
            if normalize(item['title']) not in normalize(' '.join(' '.join(parser.parts).split())):
                continue
            titles.add(normalize(item['title']))
            selected.append(dict(item, page_sha256=hashlib.sha256(page).hexdigest()))
            if len(selected) == 5:
                break
        if candidates and not selected:
            raise ValueError('Nenhuma notícia candidata pôde ser verificada')
        return {'generated_at': now.isoformat(), 'sources': available,
                'unavailable_sources': unavailable, 'items': selected}
    finally:
        if own:
            await client.aclose()


def render(draft):
    warning = ('Uma ou mais fontes ficaram indisponíveis; cobertura parcial.\n' if draft.get('unavailable_sources') else '')
    return 'Radar Público — briefing diário\nSeleção de fontes públicas; títulos originais, sem IA.\n' + warning + '\n' + ('\n\n'.join(
        f"{i}. {x['title']}\nPublicada em {x['published'][:10]}\n{x['url']}" for i,x in enumerate(draft['items'], 1))
        or 'Nenhuma notícia recente sobre os temas monitorados foi encontrada nas fontes disponíveis nas últimas 24 horas.')


async def publish(path, approved_sha, now=None):
    raw = Path(path).read_bytes()
    if os.getenv('BRIEFING_PUBLICATION_ENABLED') != 'true' or hashlib.sha256(raw).hexdigest() != approved_sha:
        raise ValueError('Publicação bloqueada: habilitação e SHA256 revisado obrigatórios')
    draft = json.loads(raw)
    now = now or datetime.now(timezone.utc)
    age = now-datetime.fromisoformat(draft['generated_at'])
    if not timedelta(0) <= age <= timedelta(hours=24) or not 0 <= len(draft['items']) <= 5 or not draft.get('sources'):
        raise ValueError('Prévia expirada ou inválida')
    if not all(official_url(x['url']) for x in draft['items']):
        raise ValueError('Fonte não permitida')
    day = now.astimezone(ZoneInfo('America/Sao_Paulo')).date().isoformat()
    await asyncio.to_thread(store.claim_publication, day, approved_sha)
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
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    print('Prévia gerada. SHA256:', digest)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception:
        raise SystemExit('Briefing bloqueado: geração ou publicação falhou. Revise as fontes e a prévia.') from None

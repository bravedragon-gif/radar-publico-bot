"""Daily official-news digest: seven-day discovery, bounded reads, no paid AI."""
import argparse
import asyncio
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from defusedxml.common import DefusedXmlException
from defusedxml import ElementTree
from app.core import normalize, telegram_send
from app.rate_limit import store
from app.news_sources import (SOURCES, BRASILIA, USER_AGENT, article_id, fetch, official_url,
                              parse_feed, listing_links, verify_article, published_date)

MAX_CANDIDATES = 32
SOURCE_ERRORS = (httpx.HTTPError, ValueError, UnicodeError, ElementTree.ParseError, DefusedXmlException)


async def generate_briefing(client=None, now=None, seen=None):
    now = now or datetime.now(timezone.utc)
    seen = set(seen or ())
    own = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5), follow_redirects=False,
                                        headers={'User-Agent': USER_AGENT})
    semaphore = asyncio.Semaphore(4)

    async def collect(source):
        name, template, kind = source
        url = template.format(year=now.astimezone(BRASILIA).year)
        try:
            async with semaphore:
                content = await fetch(client, url)
            items = parse_feed(content, now) if kind == 'rss' else listing_links(content, url)
            return name, items, None
        except SOURCE_ERRORS:
            return name, [], 'collection'

    async def verify(name, candidate):
        try:
            async with semaphore:
                content = await fetch(client, candidate['url'])
            return name, verify_article(content, candidate, name, now), None
        except SOURCE_ERRORS:
            return name, None, 'verification'

    try:
        collections = await asyncio.gather(*(collect(source) for source in SOURCES))
        available = [name for name, _, error in collections if not error]
        unavailable = {name for name, _, error in collections if error}
        # Round-robin sources before applying the cap so one source cannot crowd out others.
        pending, urls = [], set()
        for index in range(50):
            for name, items, _ in collections:
                if index >= len(items):
                    continue
                candidate = items[index]
                url = candidate['url']
                if url in urls or article_id(url) in seen:
                    continue
                urls.add(url)
                pending.append((name, candidate))
            if len(pending) >= MAX_CANDIDATES:
                break
        results = await asyncio.gather(*(verify(name, item) for name, item in pending[:MAX_CANDIDATES]))
        verified = []
        for name, item, error in results:
            if error:
                unavailable.add(name)
            elif item:
                verified.append(item)
        # Prioritize operational topics, then recency; stable URL breaks ties deterministically.
        verified.sort(key=lambda x: (-x['priority'], -published_date(x['published']).timestamp(), x['url']))
        selected, titles = [], set()
        for item in verified:
            key = normalize(item['title'])
            if key in titles:
                continue
            titles.add(key)
            selected.append(item)
            if len(selected) == 5:
                break
        status = 'unavailable' if not available else 'partial' if unavailable else 'ok'
        return {'schema_version': 2, 'generated_at': now.isoformat(), 'status': status,
                'sources': available, 'unavailable_sources': sorted(unavailable), 'items': selected}
    finally:
        if own:
            await client.aclose()


def render(draft):
    day = published_date(draft['generated_at']).astimezone(BRASILIA).strftime('%d/%m/%Y')
    header = f'Radar Público — briefing diário | {day}\nLogística e finanças públicas\n'
    if draft['status'] == 'unavailable':
        return header + '\nColeta indisponível: não foi possível consultar as fontes. Isso não significa ausência de notícias.'
    warning = ''
    if draft['unavailable_sources']:
        warning = '\nCobertura parcial. Fontes com falha de coleta ou verificação: ' + ', '.join(draft['unavailable_sources']) + '.\n'
    if not draft['items']:
        if draft['status'] == 'partial':
            return header + warning + '\nNão foi possível concluir a seleção de novidades por falhas de coleta ou verificação. Nenhum item verificado será publicado nesta execução.'
        return header + warning + '\nNenhuma novidade verificada ainda não enviada foi localizada na janela dos últimos sete dias nas fontes disponíveis.'
    sections = []
    for index, item in enumerate(draft['items'], 1):
        date = published_date(item['published']).astimezone(BRASILIA).strftime('%d/%m/%Y')
        text = f"{index}. {item['title']}\nFonte: {item['source']} | Publicada em {date}\nTema: {item['topic']}"
        if item['excerpt']:
            text += f"\nTrecho oficial: {item['excerpt']}"
        text += f"\nPonto de atenção sugerido: {item['guidance']}\n{item['url']}"
        sections.append(text)
    return (header + warning + '\n' + '\n\n'.join(sections) +
            '\n\nSeleção sem IA paga. Pontos de atenção são sugestões de conferência; não criam obrigações ou prazos. Consulte a fonte para detalhes e aplicabilidade.')


def validate_draft(draft, now):
    if draft.get('schema_version') != 2 or draft.get('status') not in ('ok', 'partial', 'unavailable'):
        raise ValueError('Formato de prévia inválido; gere uma nova prévia')
    age = now - published_date(draft['generated_at'])
    items = draft['items']
    if not timedelta(0) <= age <= timedelta(hours=24) or not isinstance(items, list) or len(items) > 5:
        raise ValueError('Prévia expirada ou inválida')
    names = {source[0] for source in SOURCES}
    if not isinstance(draft.get('sources'), list) or not isinstance(draft.get('unavailable_sources'), list):
        raise ValueError('Fontes inválidas')
    if not set(draft['sources'] + draft['unavailable_sources']) <= names:
        raise ValueError('Fonte não permitida')
    if draft['status'] != 'unavailable' and not draft['sources']:
        raise ValueError('Nenhuma fonte disponível')
    if draft['status'] == 'unavailable' and items:
        raise ValueError('Estado de coleta inválido')
    ids, titles = set(), set()
    for item in items:
        date = published_date(item['published'])
        if not official_url(item['url']) or item['source'] not in names or not now - timedelta(days=7) <= date <= now:
            raise ValueError('Notícia inválida, antiga ou fonte não permitida')
        if not isinstance(item.get('page_sha256'), str) or len(item['page_sha256']) != 64:
            raise ValueError('Página não verificada')
        identity = article_id(item['url'])
        title = normalize(item['title'])
        if identity in ids or title in titles:
            raise ValueError('Notícia duplicada na prévia')
        ids.add(identity)
        titles.add(title)
    return list(ids)


async def publish(path, approved_sha, now=None):
    raw = Path(path).read_bytes()
    if os.getenv('BRIEFING_PUBLICATION_ENABLED') != 'true' or hashlib.sha256(raw).hexdigest() != approved_sha:
        raise ValueError('Publicação bloqueada: habilitação e SHA256 obrigatórios')
    draft = json.loads(raw)
    now = now or datetime.now(timezone.utc)
    ids = validate_draft(draft, now)
    day = now.astimezone(BRASILIA).date().isoformat()
    # Claim date and URLs together before sending: uncertain outcomes never auto-resend.
    await asyncio.to_thread(store.claim_news_publication, day, approved_sha, ids, int(now.timestamp()))
    await telegram_send('@logisticapmdf', render(draft))
    await asyncio.to_thread(store.finish_news_publication, day, approved_sha)
    print('Briefing enviado ao canal; histórico registrado.')


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='artifacts/briefing.json')
    parser.add_argument('--publish')
    parser.add_argument('--approved-sha')
    parser.add_argument('--history', action='store_true', help='Excluir URLs já publicadas no Firestore')
    args = parser.parse_args()
    if args.publish:
        await publish(args.publish, args.approved_sha)
        return
    seen = await asyncio.to_thread(store.news_history_get) if args.history else set()
    draft = await generate_briefing(seen=seen)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding='utf-8')
    path.with_suffix('.txt').write_text(render(draft), encoding='utf-8')
    print('Prévia gerada. Estado:', draft['status'], '| Itens:', len(draft['items']))
    print('SHA256:', hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception:
        raise SystemExit('Briefing bloqueado: geração ou publicação falhou. Revise as fontes, o histórico e a prévia.') from None

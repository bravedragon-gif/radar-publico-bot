"""Bounded collectors for official public news. Never execute page scripts."""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urlunparse
from zoneinfo import ZoneInfo

from defusedxml import ElementTree
from app.core import normalize

MAX_BYTES = 2_000_000
USER_AGENT = 'RadarPublico/1.0 (+https://github.com/bravedragon-gif/radar-publico-bot)'
BRASILIA = ZoneInfo('America/Sao_Paulo')

# Templates roll forward without a source-code change in January.
SOURCES = (
    ('TCU', 'https://portal.tcu.gov.br/rss.xml', 'rss'),
    ('Compras', 'https://www.gov.br/compras/pt-br/acesso-a-informacao/comunicados/comunicados-de-{year}/RSS', 'rss'),
    ('PNCP', 'https://www.gov.br/pncp/pt-br/central-de-conteudo/noticias/RSS', 'rss'),
    ('Tesouro Nacional', 'https://www.gov.br/tesouronacional/pt-br', 'html'),
    ('Fazenda', 'https://www.gov.br/fazenda/pt-br/assuntos/noticias/{year}', 'html'),
    ('Gestão', 'https://www.gov.br/gestao/pt-br/assuntos/noticias/RSS', 'rss'),
    ('Agência Brasil', 'https://agenciabrasil.ebc.com.br/rss/economia/feed.xml', 'rss'),
)

# The guidance is an editorial checklist, never a claim about a legal obligation.
TOPICS = (
    ('Frota e logística', ('viatura', 'frota', 'veiculo', 'logistic'), 5,
     'Conferir efeitos sobre manutenção, abastecimento e controles da frota.'),
    ('Contratações', ('licitac', 'contrato', 'compras publicas', 'compras.gov', 'registro de precos',
                      'habilitacao tecnica', 'parcelamento do objeto', 'contratacoes publicas',
                      'contratacao publica', 'contratacao de servicos', 'contratacao de obras'), 5,
     'Conferir efeitos sobre planejamento, edital e fiscalização dos contratos.'),
    ('Patrimônio e controles', ('patrimon', 'estoque', 'governanca', 'transparencia financeira', 'controle interno'), 4,
     'Avaliar conciliação de bens, estoques e evidências dos controles internos.'),
    ('Finanças públicas', ('orcament', 'politica fiscal', 'prisma fiscal', 'gestao fiscal', 'resultado fiscal',
                           'responsabilidade fiscal', 'incentivo fiscal', 'beneficio fiscal', 'lrf',
                           'financas publicas', 'tesouro', 'contabil', 'empenho', 'divida publica',
                           'contas publicas', 'execucao financeira', 'arrecad'), 4,
     'Conferir reflexos no orçamento, na execução financeira e na prestação de contas.'),
    ('Segurança da informação', ('seguranca cibernetica', 'seguranca da informacao', 'ciberseguranca'), 3,
     'Avaliar acessos, cópias de segurança e continuidade dos sistemas administrativos.'),
)


def clean(text):
    return ' '.join(unescape(str(text or '')).split())


def canonical_url(url):
    p = urlparse(url.strip())
    # Do not silently turn an insecure URL into a trusted HTTPS URL.
    return urlunparse((p.scheme, p.netloc.lower(), p.path.rstrip('/'), '', '', ''))


def official_url(url):
    p = urlparse(url)
    if p.scheme != 'https' or p.query or p.fragment or p.params or p.username or p.password:
        return False
    if p.netloc == 'portal.tcu.gov.br':
        return p.path.startswith('/imprensa/noticias/') and len(p.path.split('/')) >= 4
    if p.netloc == 'agenciabrasil.ebc.com.br':
        return p.path.startswith('/economia/noticia/')
    if p.netloc != 'www.gov.br':
        return False
    return p.path.startswith((
        '/compras/pt-br/', '/pncp/pt-br/central-de-conteudo/noticias/',
        '/gestao/pt-br/assuntos/noticias/', '/fazenda/pt-br/assuntos/noticias/',
        '/tesouronacional/pt-br/noticias/',
    ))


def article_id(url):
    return hashlib.sha256(canonical_url(url).encode()).hexdigest()


def published_date(value):
    value = clean(value)
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
        except (ValueError, TypeError):
            # Gov.br dates without an offset are Brazilian local time.
            date = datetime.strptime(value, '%d/%m/%Y %Hh%M').replace(tzinfo=BRASILIA)
    if date.tzinfo is None:
        raise ValueError('Data sem fuso')
    return date.astimezone(timezone.utc)


def recent(value, now):
    date = published_date(value)
    return now - timedelta(days=7) <= date <= now


def classification(title, description=''):
    text = normalize(title + ' ' + description[:600])
    # Operational news takes precedence over institutional events and academic notices.
    if any(term in normalize(title) for term in ('defesa de mestrado', 'defesa de tcc', 'lanca livros',
                                                 'lanca dois livros', 'inscricoes abertas para o premio')):
        return None
    for label, terms, priority, guidance in TOPICS:
        if any(re.search(r'\b' + re.escape(term), text) for term in terms):
            return label, priority, guidance
    return None


class Page(HTMLParser):
    """Read metadata and visible title/description, ignoring scripts and navigation."""
    def __init__(self):
        super().__init__()
        self.meta, self.links, self.headings, self.descriptions, self.dates = {}, [], [], [], []
        self.stack, self.captures = [], []
        self.ignored = 0
        self.json_scripts = []
        self.json_buffer = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta':
            key = attrs.get('property') or attrs.get('name') or attrs.get('itemprop')
            if key:
                self.meta[key.lower()] = attrs.get('content', '')
        if tag == 'a' and attrs.get('href'):
            self.links.append(attrs['href'])
        if tag in ('script', 'style', 'nav', 'footer'):
            self.ignored += 1
        if tag == 'script' and attrs.get('type') == 'application/ld+json':
            self.json_buffer = []
        if tag in ('meta', 'link', 'img', 'input', 'br', 'hr', 'source', 'wbr', 'area', 'base', 'embed', 'param', 'track'):
            return
        self.stack.append(tag)
        kind = None
        classes = attrs.get('class', '').split()
        if not self.ignored:
            if tag == 'h1':
                kind = 'headings'
            elif 'documentDescription' in classes:
                kind = 'descriptions'
            elif attrs.get('property') == 'rnews:datePublished' or attrs.get('itemprop') == 'datePublished':
                self.dates.append(attrs.get('content') or attrs.get('datetime') or '')
                kind = 'dates'
            elif tag == 'time' and attrs.get('datetime'):
                self.dates.append(attrs['datetime'])
        if kind:
            self.captures.append([len(self.stack), kind, []])

    def handle_endtag(self, tag):
        if tag == 'script' and self.json_buffer is not None:
            self.json_scripts.append(''.join(self.json_buffer))
            self.json_buffer = None
        if tag in ('script', 'style', 'nav', 'footer'):
            self.ignored = max(0, self.ignored - 1)
        if tag not in self.stack:
            return
        depth = len(self.stack) - self.stack[::-1].index(tag)
        for capture in self.captures[:]:
            if capture[0] >= depth:
                getattr(self, capture[1]).append(clean(' '.join(capture[2])))
                self.captures.remove(capture)
        del self.stack[depth-1:]

    def handle_data(self, data):
        if self.json_buffer is not None:
            self.json_buffer.append(data)
        if not self.ignored:
            for capture in self.captures:
                capture[2].append(data)

    def metadata(self):
        dates = [self.meta.get(k, '') for k in ('article:published_time', 'datepublished', 'dc.date.issued')]
        dates.extend(self.dates)
        for script in self.json_scripts:
            try:
                value = json.loads(script)
            except (ValueError, RecursionError):
                continue
            objects = value if isinstance(value, list) else [value]
            for obj in objects[:20]:
                if isinstance(obj, dict):
                    dates.append(obj.get('datePublished', ''))
        return {
            'title': clean(self.headings[0] if self.headings else self.meta.get('og:title', '')),
            'description': clean(next((x for x in self.descriptions if x), '') or
                                 self.meta.get('og:description') or self.meta.get('description', '')),
            'dates': [x for x in dates if x],
        }


def parse_page(content):
    page = Page()
    page.feed(content.decode('utf-8'))
    return page


def plain_excerpt(value):
    # Feed descriptions can contain markup; a separate parser strips it.
    class Text(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []
        def handle_data(self, data):
            self.parts.append(data)
    parser = Text()
    parser.feed(value)
    return clean(' '.join(parser.parts))


def parse_feed(content, now):
    root = ElementTree.fromstring(content)
    if root.tag not in ('rss', '{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF'):
        raise ValueError('Formato de feed inválido')
    if root.tag == 'rss' and root.find('channel') is None:
        raise ValueError('Feed sem canal')
    entries = root.findall('.//item') + root.findall('.//{http://purl.org/rss/1.0/}item')
    items, dated = [], 0
    for entry in entries[:50]:
        def field(name):
            return entry.findtext(name) or entry.findtext('{http://purl.org/rss/1.0/}'+name) or ''
        title, url = clean(field('title')), canonical_url(field('link'))
        value = field('pubDate') or entry.findtext('{http://purl.org/dc/elements/1.1/}date') or ''
        description = plain_excerpt(field('description'))
        try:
            valid = recent(value, now)
        except (ValueError, TypeError, OverflowError):
            continue
        dated += 1
        if valid and official_url(url) and title and classification(title, description):
            items.append({'title': title, 'url': url, 'published': published_date(value).isoformat(),
                          'feed_description': description})
    if entries and not dated:
        raise ValueError('Feed sem datas de publicação verificáveis')
    return items


def listing_links(content, base):
    page = parse_page(content)
    links = []
    for href in page.links:
        # Only actual news articles from this listing's host and institution.
        url = canonical_url(urljoin(base, href))
        if not official_url(url) or url in links:
            continue
        if base.startswith('https://www.gov.br/fazenda/'):
            allowed = re.fullmatch(r'/fazenda/pt-br/assuntos/noticias/\d{4}/[^/]+/[^/]+', urlparse(url).path)
        else:
            allowed = re.fullmatch(r'/tesouronacional/pt-br/noticias/[^/]+', urlparse(url).path)
        if allowed:
            links.append(url)
    if not links:
        raise ValueError('Listagem sem links reconhecidos; não comprova ausência de notícias')
    return [{'url': url} for url in links[:8]]


async def fetch(client, url):
    async with client.stream('GET', url) as response:
        response.raise_for_status()
        content = bytearray()
        async for chunk in response.aiter_bytes():
            content.extend(chunk)
            if len(content) > MAX_BYTES:
                raise ValueError('Fonte excede tamanho permitido')
    return bytes(content)


def verify_article(content, candidate, source, now):
    metadata = parse_page(content).metadata()
    title = metadata['title']
    if not title or len(title) > 400:
        raise ValueError('Título ausente ou inválido')
    if candidate.get('title') and normalize(clean(candidate['title'])) != normalize(title):
        raise ValueError('Título não confirmado na página')
    dates = metadata['dates'] or [candidate.get('published', '')]
    date = next((published_date(x) for x in dates if x), None)
    if date is None:
        raise ValueError('Data de publicação ausente')
    if not recent(date.isoformat(), now):
        return None
    description = metadata['description']
    topic = classification(title, description)
    if not topic:
        return None
    label, priority, guidance = topic
    excerpt = description if len(description) <= 320 else description[:317].rsplit(' ', 1)[0] + '…'
    return {'title': title, 'url': candidate['url'], 'published': date.isoformat(),
            'source': source, 'excerpt': excerpt, 'topic': label, 'priority': priority + (2 if source == 'TCU' else 0),
            'guidance': guidance, 'page_sha256': hashlib.sha256(content).hexdigest()}

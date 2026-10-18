"""Explicit reply-keyboard choices; no free-text intent guessing."""
SOURCES = {'pncp': 'PNCP', 'compras': 'Compras.gov.br'}
KINDS = {'licitacoes': 'Licitações', 'atas': 'Atas', 'pesquisa': 'Pesquisa'}
CHOICES = {f'{label} · {title}': (source, kind)
           for source, label in SOURCES.items() for kind, title in KINDS.items()}


def keyboard(source):
    return {'keyboard': [[{'text': f'{SOURCES[source]} · {title}'}] for title in KINDS.values()]
            + [[{'text': '/cancelar'}]], 'resize_keyboard': True, 'one_time_keyboard': True}


def prompt(source, kind):
    return (f'{SOURCES[source]} — {KINDS[kind]}. Digite o que deseja buscar, por exemplo: viaturas. '
            'A seleção vale por 10 minutos. /cancelar encerra. '
            + ('Pesquisa consulta contratações e atas; não compara preços.' if kind == 'pesquisa' else ''))

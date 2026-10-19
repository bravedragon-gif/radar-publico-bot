"""Explicit reply-keyboard choices; no free-text intent guessing."""
SOURCES = {'pncp': 'PNCP', 'compras': 'Compras.gov.br'}
KINDS = {'licitacoes': 'Licitações', 'atas': 'Atas', 'pesquisa': 'Pesquisa'}
CHOICES = {f'{label} · {title}': (source, kind)
           for source, label in SOURCES.items() for kind, title in KINDS.items()}
MENU = '🏠 Menu principal'
HELP_BUTTON = '❓ Ajuda'
CANCEL = '❌ Cancelar'
BACK = {source: f'⬅️ Voltar ao {label}' for source, label in SOURCES.items()}
NAVIGATION = {label: '/'+source for source, label in SOURCES.items()}
NAVIGATION.update({label: '/'+source for source, label in BACK.items()})
NAVIGATION.update({MENU: '/menu', HELP_BUTTON: '/ajuda', CANCEL: '/cancelar'})


def reply_keyboard(rows):
    return {'keyboard': [[{'text': label} for label in row] for row in rows],
            'resize_keyboard': True, 'one_time_keyboard': False, 'is_persistent': True}


def home_keyboard():
    return reply_keyboard([list(SOURCES.values()), [HELP_BUTTON]])


def search_keyboard(source):
    return reply_keyboard([[BACK[source]], [MENU, CANCEL], [HELP_BUTTON]])


def keyboard(source):
    return reply_keyboard([[f'{SOURCES[source]} · {title}'] for title in KINDS.values()]
                          + [[MENU, CANCEL], [HELP_BUTTON]])


def prompt(source, kind):
    return (f'{SOURCES[source]} — {KINDS[kind]}. Digite o que deseja buscar, por exemplo: viaturas. '
            'Você pode enviar outros termos nesta consulta por 10 minutos. '
            'Use os botões para voltar, trocar de fonte ou cancelar. '
            + ('Pesquisa consulta contratações e atas; não compara preços.' if kind == 'pesquisa' else ''))

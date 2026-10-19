"""Explicit reply-keyboard choices; no free-text intent guessing."""
from app.compras_filters import EXTRA_KINDS
SOURCES = {'pncp': 'PNCP', 'compras': 'Compras.gov.br'}
KINDS = {'licitacoes': 'Licitações', 'atas': 'Atas', 'pesquisa': 'Pesquisa'}
SOURCE_KINDS = {'pncp': tuple(KINDS), 'compras': (*KINDS, *EXTRA_KINDS)}
KINDS.update(EXTRA_KINDS)
CHOICES = {f'{label} · {title}': (source, kind)
           for source, label in SOURCES.items() for kind, title in KINDS.items() if kind in SOURCE_KINDS[source]}
MENU = '🏠 Menu principal'
HELP_BUTTON = '❓ Ajuda'
CANCEL = '❌ Cancelar'
BACK = {source: f'⬅️ Voltar ao {label}' for source, label in SOURCES.items()}
NAVIGATION = {label: '/'+source for source, label in SOURCES.items()}
NAVIGATION.update({label: '/'+source for source, label in BACK.items()})
NAVIGATION.update({MENU: '/menu', HELP_BUTTON: '/ajuda', CANCEL: '/cancelar'})
FILTERS = '⚙️ Como filtrar'
NAVIGATION[FILTERS] = '/filtros'
FILTER_HELP = ('Filtros do Compras.gov.br: envie o termo e acrescente filtros separados por |.\n'
               'Licitações: viaturas | dias=30 | uf=DF | orgao=CODIGO | uasg=CODIGO\n'
               'Atas, Pesquisa e Itens: viaturas | dias=30 | uasg=CODIGO\n'
               'Contratos: viaturas | orgao=CODIGO | dias=90\n'
               'Planejamento: viaturas | orgao=CODIGO | ano=2027\n'
               'Preços: CODIGO_CATALOGO | dias=90 | uf=DF | orgao=CODIGO | uasg=CODIGO\n'
               'Substitua CODIGO pelo código numérico oficial, não pelo nome ou CNPJ. '
               'Preços usam CATMAT para materiais e CATSER para serviços. '
               'Período padrão: 7 dias; máximo: 90. PCA usa ano, padrão atual. '
               'Filtros valem só para a mensagem enviada. '
               'Até 2 páginas por chamada; não é uma busca exaustiva. '
               'Órgão em Preços é filtrado localmente na amostra. '
               'UF não está disponível nos demais módulos. '
               'Os filtros desta tela não se aplicam ao PNCP.')


def reply_keyboard(rows):
    return {'keyboard': [[{'text': label} for label in row] for row in rows],
            'resize_keyboard': True, 'one_time_keyboard': False, 'is_persistent': True}


def home_keyboard():
    return reply_keyboard([list(SOURCES.values()), [HELP_BUTTON]])


def search_keyboard(source):
    return reply_keyboard(([[FILTERS]] if source == 'compras' else []) + [[BACK[source]], [MENU, CANCEL], [HELP_BUTTON]])


def keyboard(source):
    return reply_keyboard([[f'{SOURCES[source]} · {KINDS[kind]}'] for kind in SOURCE_KINDS[source]]
                          + [[MENU, CANCEL], [HELP_BUTTON]])


def prompt(source, kind):
    if source == 'compras' and kind in EXTRA_KINDS:
        instruction = ('Envie o código CATMAT do material.' if kind == 'materiais' else
                       'Envie o código CATSER do serviço.' if kind == 'servicos' else
                       'Envie: termo | orgao=CODIGO | ano=AAAA. Ano padrão: atual.' if kind == 'planejamento' else
                       'Envie: termo | orgao=CODIGO. Consulta por início de vigência.' if kind == 'contratos' else
                       'Digite a descrição do item. Valores estimados e resultados são identificados separadamente.')
        return f'{SOURCES[source]} — {KINDS[kind]}. {instruction} Use Como filtrar para ver as opções. Seleção válida por 10 minutos.'
    return (f'{SOURCES[source]} — {KINDS[kind]}. Digite o que deseja buscar, por exemplo: viaturas. '
            + ('Use Como filtrar para período, órgão, UF ou UASG disponíveis no módulo. ' if source == 'compras' else '') +
            'Você pode enviar outros termos nesta consulta por 10 minutos. '
            'Use os botões para voltar, trocar de fonte ou cancelar. '
            + ('Pesquisa consulta contratações e atas; não compara preços.' if kind == 'pesquisa' else ''))

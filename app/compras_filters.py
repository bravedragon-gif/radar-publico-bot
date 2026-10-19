"""Strict query options, validated before consuming query quota or accessing APIs."""
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from app.core import validate_term

EXTRA_KINDS = {'itens': 'Itens e resultados', 'materiais': 'Preços de materiais',
               'servicos': 'Preços de serviços', 'contratos': 'Contratos', 'planejamento': 'Planejamento'}
UFS = set('AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO'.split())


def parse_query(text, kind, today=None):
    if not isinstance(text, str) or len(text) > 400:
        raise ValueError('Envie um termo com filtros, com até 400 caracteres no total.')
    parts = [part.strip() for part in text.split('|')]
    term = parts[0]
    if kind in ('materiais', 'servicos'):
        if not re.fullmatch(r'[1-9][0-9]{0,8}', term):
            raise ValueError('Informe o código CATMAT (material) ou CATSER (serviço), por exemplo: 1.')
    else:
        term = validate_term(term)
    opts = {}
    for part in parts[1:]:
        key, sep, value = part.partition('=')
        key, value = key.strip().lower(), value.strip()
        if not sep or key not in ('dias', 'uf', 'orgao', 'ano', 'uasg') or key in opts:
            raise ValueError('Filtros: dias=30 | uf=DF | orgao=CODIGO | uasg=CODIGO | ano=2027. Não repita filtros.')
        opts[key] = value
    for key in ('dias', 'ano', 'orgao', 'uasg'):
        if key in opts and not re.fullmatch(r'[0-9]{1,9}', opts[key]):
            raise ValueError(f'O filtro {key} deve ser numérico.')
    days = int(opts.get('dias', 7))
    if not 1 <= days <= 90:
        raise ValueError('O período deve ter entre 1 e 90 dias.')
    opts['dias'] = days
    if 'uf' in opts:
        opts['uf'] = opts['uf'].upper()
        if opts['uf'] not in UFS:
            raise ValueError('Informe uma UF brasileira válida, por exemplo uf=DF.')
        if kind not in ('licitacoes', 'materiais', 'servicos'):
            raise ValueError('UF está disponível em Licitações e Preços de materiais/serviços. Escolha uma dessas opções.')
    if 'orgao' in opts and kind in ('atas', 'pesquisa', 'itens'):
        raise ValueError('Este módulo não aceita código de órgão. Use uasg=CODIGO para filtrar a unidade.')
    if kind in ('contratos', 'planejamento') and 'orgao' not in opts:
        raise ValueError('Este módulo exige código do órgão: termo | orgao=CODIGO. Não use o CNPJ.')
    if 'ano' in opts and kind != 'planejamento':
        raise ValueError('O filtro ano está disponível apenas em Planejamento.')
    if kind == 'planejamento':
        if 'dias' in [part.partition('=')[0].strip().lower() for part in parts[1:]]:
            raise ValueError('Planejamento usa ano=AAAA, não o filtro dias.')
        year = (today or datetime.now(ZoneInfo('America/Sao_Paulo')).date()).year
        opts['ano'] = int(opts.get('ano', year))
        if not 2020 <= opts['ano'] <= year+2:
            raise ValueError('Ano do planejamento fora do intervalo permitido (2020 até o ano atual + 2).')
    return term, opts

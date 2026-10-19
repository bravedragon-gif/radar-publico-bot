import time
import json
import httpx
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from app import main
from app.rate_limit import LimitReached


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv('TELEGRAM_WEBHOOK_SECRET','test-secret')
    monkeypatch.setenv('QUERIES_ENABLED','true')
    main.paused_until = 0
    calls = []
    monkeypatch.setattr(main,'telegram_send',AsyncMock(side_effect=lambda cid,text,**kwargs: calls.append(text)))
    monkeypatch.setattr(main.store,'menu_get',lambda uid:None)
    monkeypatch.setattr(main.store,'menu_set',lambda *args:None)
    monkeypatch.setattr(main.store,'admit',lambda *args: True)
    monkeypatch.setattr(main.store,'cache_get',lambda key: None)
    monkeypatch.setattr(main.store,'cache_set',lambda *args: None)
    monkeypatch.setattr(main.store,'reserve',lambda: None)
    result = {'items': [], 'pages': 1,'kind':'pncp','start':'20261011','end':'20261017'}
    search = AsyncMock(return_value=result)
    monkeypatch.setattr(main,'pncp_search',search)
    return TestClient(main.app),calls,search


def post(client,text='/pncp viaturas',**overrides):
    data = {'update_id':1,'message':{'chat':{'id':123,'type':'private'},'from':{'id':999999,'is_bot':False},'text':text}}
    data.update(overrides)
    return client.post('/telegram/webhook',json=data,headers={'X-Telegram-Bot-Api-Secret-Token':'test-secret'})


@pytest.mark.parametrize('command',['/start','/ajuda','/pncp viaturas','/licitacoes viaturas','/atas viaturas','/pncp@Log_pmdf_bot\tviaturas'])
def test_public_commands(env,command):
    client,calls,search=env
    assert post(client,command).status_code == 200
    assert len(calls) == 1
    assert search.await_count == (0 if command in ('/start','/ajuda') else 1)


@pytest.mark.parametrize('source',['pncp','compras'])
def test_menu_keyboard_and_choice(env,monkeypatch,source):
    client,calls,search=env
    admissions=[]
    monkeypatch.setattr(main.store,'admit',lambda uid,update,query: admissions.append(query) or True)
    saved=[]
    monkeypatch.setattr(main.store,'menu_set',lambda *args:saved.append(args))
    post(client,'/'+source)
    markup=main.telegram_send.call_args.kwargs['reply_markup']
    assert len(markup['keyboard']) == 5
    assert [r[0]['text'].split(' · ')[-1] for r in markup['keyboard'][:3]] == ['Licitações','Atas','Pesquisa']
    post(client,markup['keyboard'][1][0]['text'])
    assert saved[-1] == (999999,source,'atas')
    assert 'Digite' in calls[-1] and not search.called
    assert admissions == [False,False]


def test_plain_term_uses_selected_source(env,monkeypatch):
    client,calls,search=env
    monkeypatch.setattr(main.store,'menu_get',lambda uid:{'source':'pncp','kind':'atas'})
    post(client,'viaturas')
    assert search.call_args.args == ('viaturas',)
    assert search.call_args.kwargs['kind'] == 'atas'


def test_compras_does_not_call_pncp(env,monkeypatch):
    client,calls,search=env
    result={'items':[],'pages':1,'start':'2026-10-12','end':'2026-10-18','kind':'atas'}
    purchases=AsyncMock(return_value=result)
    monkeypatch.setattr(main,'compras_search',purchases)
    monkeypatch.setattr(main.store,'menu_get',lambda uid:{'source':'compras','kind':'atas'})
    keys=[]
    monkeypatch.setattr(main.store,'cache_get',lambda key:keys.append(key) or None)
    post(client,'viaturas')
    assert purchases.await_count == 1 and not search.called
    assert 'Compras.gov.br' in calls[-1]
    assert keys == [main.cache_key('compras_atas','viaturas',main.datetime.now(main.ZoneInfo('America/Sao_Paulo')).date().isoformat())]


def test_no_context_explains_and_cancel_clears(env,monkeypatch):
    client,calls,search=env
    post(client,'viaturas')
    assert 'expira' in calls[-1] and not search.called
    saved=[]
    monkeypatch.setattr(main.store,'menu_set',lambda *args:saved.append(args))
    post(client,'/cancelar')
    assert saved == [(999999,)] and 'encerrada' in calls[-1]


def test_general_pncp_fetches_both_categories(env,monkeypatch):
    client,calls,search=env
    monkeypatch.setattr(main.store,'menu_get',lambda uid:{'source':'pncp','kind':'pesquisa'})
    post(client,'viaturas')
    assert [call.kwargs['kind'] for call in search.call_args_list] == ['pncp','atas']


def test_session_read_failure_never_fetches(env,monkeypatch):
    client,calls,search=env
    def broken(uid):
        raise RuntimeError('private-session')
    monkeypatch.setattr(main.store,'menu_get',broken)
    assert post(client,'viaturas').status_code == 200
    assert not search.called and not calls


def test_menu_query_obeys_same_user_limit(env,monkeypatch):
    client,calls,search=env
    monkeypatch.setattr(main.store,'menu_get',lambda uid:{'source':'pncp','kind':'licitacoes'})
    def denied(uid,update,query):
        assert query is True
        raise LimitReached('user')
    monkeypatch.setattr(main.store,'admit',denied)
    post(client,'viaturas')
    assert not search.called and '10 consultas' in calls[-1]


def test_auth_and_bad_input(env):
    client,calls,_=env
    assert client.post('/telegram/webhook',json={}).status_code == 403
    assert client.post('/telegram/webhook',content='[]',headers={'X-Telegram-Bot-Api-Secret-Token':'test-secret'}).status_code == 400
    assert client.post('/telegram/webhook',content='x'*17000,headers={'X-Telegram-Bot-Api-Secret-Token':'test-secret'}).status_code == 413
    assert not calls


def test_cache_hit_still_requires_admission(env,monkeypatch):
    client,calls,search=env
    monkeypatch.setattr(main.store,'cache_get',lambda key: {'items': [], 'pages':1,'kind':'pncp','start':'a','end':'b'})
    post(client)
    assert calls and not search.called
    monkeypatch.setattr(main.store,'admit',lambda *args: False)
    post(client)
    assert len(calls) == 1


@pytest.mark.parametrize('reason',['user','global','external','suspended'])
def test_limit_fail_closed(env,monkeypatch,reason):
    client,calls,search=env
    def denied(*args):
        raise LimitReached(reason)
    monkeypatch.setattr(main.store,'admit',denied)
    post(client)
    assert not search.called and len(calls) == 1


def test_store_failure_is_closed(env,monkeypatch):
    client,calls,search=env
    def broken(*args):
        raise RuntimeError('secret')
    monkeypatch.setattr(main.store,'admit',broken)
    post(client)
    assert not search.called and not calls and main.paused_until > time.monotonic()


def test_search_failure_never_caches(env,monkeypatch):
    client,calls,search=env
    search.side_effect = TimeoutError()
    cache = AsyncMock()
    monkeypatch.setattr(main.store,'cache_set',cache)
    post(client)
    assert not cache.called


def test_pncp_429_persists_cooldown_and_explains_limit(env,monkeypatch):
    client,calls,search=env
    search.side_effect=main.PNCPRateLimited(600)
    deferred=[]
    monkeypatch.setattr(main.store,'defer_pncp',lambda seconds:deferred.append(seconds))
    assert post(client).status_code == 200
    assert deferred == [600] and 'HTTP 429' in calls[0]
    assert main.paused_until == 0


def test_persisted_pncp_cooldown_answers_without_fetch(env):
    client,calls,search=env
    async def limited(*args,**kwargs):
        await kwargs['reserve']()
    def denied():
        raise LimitReached('pncp')
    search.side_effect=limited
    from unittest.mock import patch
    with patch.object(main.store,'reserve',denied):
        post(client)
    assert 'HTTP 429' in calls[0] and main.paused_until == 0


@pytest.mark.parametrize('failure,category,status', [
    (httpx.ReadTimeout('sensitive-url'), 'timeout', None),
    (httpx.ConnectError('sensitive-url'), 'network', None),
    (ValueError('sensitive-payload'), 'invalid_response', None),
    (httpx.HTTPStatusError('sensitive-url', request=httpx.Request('GET','https://example.test'),
                          response=httpx.Response(503)), 'http_status', 503),
])
def test_pncp_failure_logs_only_safe_details(env,caplog,failure,category,status):
    client,calls,search = env
    search.side_effect = failure
    post(client)
    entry = next(json.loads(r.message) for r in caplog.records if 'dependency_failure' in r.message)
    assert entry['stage'] == 'pncp'
    assert entry['category'] == category
    assert entry.get('status') == status
    assert 'sensitive' not in caplog.text
    assert len(calls) == 1 and 'indisponível' in calls[0]


def test_kill_switch(env,monkeypatch):
    client,calls,search=env
    monkeypatch.setenv('QUERIES_ENABLED','false')
    post(client)
    assert not calls and not search.called


def test_groups_and_bots_ignored(env):
    client,calls,_=env
    post(client,message={'chat':{'id':1,'type':'group'},'from':{'id':1},'text':'/start'})
    post(client,message={'chat':{'id':1,'type':'private'},'from':{'id':1,'is_bot':True},'text':'/start'})
    assert not calls


@pytest.mark.parametrize('source', ['pncp', 'compras'])
@pytest.mark.parametrize('kind', ['licitacoes', 'atas', 'pesquisa'])
def test_button_only_flow(env, monkeypatch, source, kind):
    client, calls, search = env
    from app.menus import MENU, CANCEL, BACK, HELP_BUTTON
    session = {}
    admissions = []
    def save(uid, source=None, kind=None):
        session.clear()
        if source:
            session.update(source=source, kind=kind)
    monkeypatch.setattr(main.store, 'menu_set', save)
    monkeypatch.setattr(main.store, 'menu_get', lambda uid: session.copy() or None)
    monkeypatch.setattr(main.store, 'admit', lambda uid, update, query: admissions.append(query) or True)
    purchases = AsyncMock(return_value={'items': [], 'pages': 1, 'start': 'a', 'end': 'b', 'kind': kind})
    monkeypatch.setattr(main, 'compras_search', purchases)
    def buttons():
        markup = main.telegram_send.call_args.kwargs['reply_markup']
        assert markup['is_persistent'] and not markup['one_time_keyboard']
        return [button['text'] for row in markup['keyboard'] for button in row]
    post(client, '/start')
    label = main.SOURCES[source]
    assert label in buttons()
    post(client, label)
    choice = f'{label} · {main.KINDS[kind]}'
    assert choice in buttons()
    post(client, choice)
    assert session == {'source': source, 'kind': kind}
    assert BACK[source] in buttons() and CANCEL in buttons()
    post(client, 'viaturas')
    expected = purchases if source == 'compras' else search
    assert expected.called and not (search if source == 'compras' else purchases).called
    assert BACK[source] in buttons()
    post(client, HELP_BUTTON)
    assert session == {'source': source, 'kind': kind}
    assert label in buttons()
    post(client, BACK[source])
    assert not session and choice in buttons()
    post(client, choice)
    post(client, CANCEL)
    assert not session and label in buttons()
    post(client, label)
    post(client, choice)
    post(client, MENU)
    assert not session and label in buttons()
    assert admissions.count(True) == 1


@pytest.mark.parametrize('entry', ['/start', '/menu', '🏠 Menu principal'])
def test_home_clears_previous_selection(env, monkeypatch, entry):
    client, calls, search = env
    saved = []
    monkeypatch.setattr(main.store, 'menu_set', lambda *args: saved.append(args))
    post(client, entry)
    assert saved == [(999999,)] and not search.called
    assert main.telegram_send.call_args.kwargs['reply_markup'] == main.home_keyboard()


def test_expired_session_and_invalid_term_offer_buttons(env, monkeypatch):
    client, calls, search = env
    post(client, 'viaturas')
    assert main.telegram_send.call_args.kwargs['reply_markup'] == main.home_keyboard()
    monkeypatch.setattr(main.store, 'menu_get', lambda uid: {'source': 'compras', 'kind': 'atas'})
    post(client, 'x')
    assert '2 a 120' in calls[-1] and not search.called
    assert main.telegram_send.call_args.kwargs['reply_markup'] == main.search_keyboard('compras')


def test_duplicate_button_does_not_change_session(env, monkeypatch):
    client, calls, search = env
    saved = []
    monkeypatch.setattr(main.store, 'admit', lambda *args: False)
    monkeypatch.setattr(main.store, 'menu_set', lambda *args: saved.append(args))
    post(client, 'PNCP')
    assert not calls and not saved and not search.called

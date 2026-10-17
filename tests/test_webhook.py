import time
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
    monkeypatch.setattr(main,'telegram_send',AsyncMock(side_effect=lambda cid,text: calls.append(text)))
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

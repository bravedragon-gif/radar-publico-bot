import pytest
from app import rate_limit as rl


class Snap:
    def __init__(self, data):
        self.data=data
    def to_dict(self):
        return self.data


class Ref:
    def __init__(self, db, name):
        self.db,self.name=db,name
    def get(self,transaction=None,**kwargs):
        return Snap(self.db.data.get(self.name))
    def set(self,data,**kwargs):
        if kwargs.get('merge'):
            self.db.data[self.name]=dict(self.db.data.get(self.name) or {}, **data)
        else:
            self.db.data[self.name]=data


class DB:
    def __init__(self):
        self.data={}
    def document(self,name):
        return Ref(self,name)
    def transaction(self,**kwargs):
        return self
    def set(self,ref,data):
        ref.set(data)


@pytest.fixture
def db(monkeypatch):
    db=DB()
    monkeypatch.setattr(rl,'client',lambda: db)
    monkeypatch.setattr(rl.firestore,'transactional',lambda f:f)
    return db


def test_rolling_window_and_duplicate(db):
    store=rl.Store()
    for i in range(10):
        assert store.admit(1,i,True,10000+i)
    assert not store.admit(1,9,True,10020)
    with pytest.raises(rl.LimitReached,match='user'):
        store.admit(1,10,True,10020)
    assert store.admit(2,10,True,10020)
    assert store.admit(1,11,True,13600)
    with pytest.raises(rl.LimitReached):
        store.admit(1,12,True,13600)


def test_global_daily_reset_and_suspend(db,monkeypatch):
    monkeypatch.setenv('GLOBAL_DAILY_UPDATES','2')
    store=rl.Store()
    store.admit(1,1,False,100)
    store.admit(2,2,False,101)
    with pytest.raises(rl.LimitReached,match='global'):
        store.admit(3,3,False,102)
    assert store.admit(3,4,False,86400)
    db.data['radar_publico_ops/control']={'suspended':True}
    with pytest.raises(rl.LimitReached,match='suspended'):
        store.admit(4,5,False,86401)


def test_external_cap(db,monkeypatch):
    monkeypatch.setenv('GLOBAL_DAILY_EXTERNAL','2')
    store=rl.Store()
    store.reserve();store.reserve()
    with pytest.raises(rl.LimitReached,match='external'):
        store.reserve()


def test_pncp_cooldown_survives_new_store_and_daily_reset(db,monkeypatch):
    monkeypatch.setattr(rl.time,'time',lambda:86350)
    store=rl.Store()
    store.defer_pncp(300)
    store.defer_pncp(60)
    assert db.data['radar_publico_ops/budget']['pncp_retry_at'] == 86650
    # Help/admission still works across midnight and preserves the cooldown.
    store.admit(1,1,False,86410)
    monkeypatch.setattr(rl.time,'time',lambda:86410)
    with pytest.raises(rl.LimitReached,match='pncp'):
        rl.Store().reserve()
    monkeypatch.setattr(rl.time,'time',lambda:86650)
    rl.Store().reserve()


def test_cache_expiry(db,monkeypatch):
    store=rl.Store()
    store.cache_set('abc123',{'items':[]})
    assert store.cache_get('abc123') == {'items':[]}
    monkeypatch.setattr(rl.time,'time',lambda:10**12)
    assert store.cache_get('abc123') is None


def test_menu_survives_admission_and_expires(db,monkeypatch):
    monkeypatch.setattr(rl.time,'time',lambda:1000)
    store=rl.Store()
    store.menu_set(1,'compras','pesquisa')
    store.admit(1,1,False,1001)
    assert rl.Store().menu_get(1)['source'] == 'compras'
    assert rl.Store().menu_get(2) is None
    monkeypatch.setattr(rl.time,'time',lambda:1600)
    assert store.menu_get(1) is None
    store.menu_set(1)
    assert store.menu_get(1) is None


def test_source_cooldowns_are_independent(db,monkeypatch):
    monkeypatch.setattr(rl.time,'time',lambda:86350)
    store=rl.Store()
    store.defer_pncp(300,'compras')
    store.reserve('pncp')
    store.admit(1,1,False,86401)
    monkeypatch.setattr(rl.time,'time',lambda:86401)
    with pytest.raises(rl.LimitReached,match='compras'):
        store.reserve('compras')

def test_wrong_cache_key_never_returns_other_query(db):
    store=rl.Store()
    store.cache_set('00000000a',{'items':['one']})
    assert store.cache_get('00000000b') is None


def test_user_rejection_counts_global_budget(db):
    store=rl.Store()
    for i in range(10):
        store.admit(1,i,True,10000+i)
    with pytest.raises(rl.LimitReached):
        store.admit(1,11,True,10020)
    assert db.data['radar_publico_ops/budget']['updates']==11


def test_news_claim_protects_day_and_urls_across_days(db):
    store = rl.Store()
    store.claim_news_publication('2026-10-19', 'digest', ['url1'], 10000000)
    assert store.news_history_get(10000000) == {'url1'}
    with pytest.raises(ValueError, match='diária'):
        store.claim_news_publication('2026-10-19', 'digest2', ['url2'], 10000001)
    with pytest.raises(ValueError, match='Notícia'):
        store.claim_news_publication('2026-10-20', 'digest2', ['url1'], 10086400)
    assert 'radar_publico_publications/2026-10-20' not in db.data
    store.claim_news_publication('2026-10-20', 'digest2', ['url2'], 10086400)
    store.finish_news_publication('2026-10-20', 'digest2')
    assert db.data['radar_publico_publications/2026-10-20']['status'] == 'sent'


def test_news_history_prunes_old_items_and_does_not_overwrite_uncertain_claim(db):
    store = rl.Store()
    db.data['radar_publico_ops/news_history'] = {'items': {'old': 0, 'recent': 9999999}}
    db.data['radar_publico_publications/2026-10-19'] = {'sha256': 'old', 'status': 'claimed'}
    assert store.news_history_get(10000000) == {'recent'}
    with pytest.raises(ValueError):
        store.claim_news_publication('2026-10-19', 'new', ['new'], 10000000)
    assert db.data['radar_publico_publications/2026-10-19']['sha256'] == 'old'
    store.claim_news_publication('2026-10-20', 'new', ['new'], 10000000)
    assert db.data['radar_publico_ops/news_history']['items'] == {'recent': 9999999, 'new': 10000000}


def test_news_history_full_fails_without_writes(db):
    store = rl.Store()
    db.data['radar_publico_ops/news_history'] = {'items': {str(i): 10000000 for i in range(400)}}
    with pytest.raises(ValueError, match='limite'):
        store.claim_news_publication('2026-10-19', 'digest', ['new'], 10000001)
    assert 'radar_publico_publications/2026-10-19' not in db.data


def test_news_confirmation_requires_matching_claim(db):
    db.data['radar_publico_publications/2026-10-19'] = {'sha256': 'digest', 'status': 'claimed'}
    with pytest.raises(ValueError):
        rl.Store().finish_news_publication('2026-10-19', 'wrong')
    assert db.data['radar_publico_publications/2026-10-19']['status'] == 'claimed'

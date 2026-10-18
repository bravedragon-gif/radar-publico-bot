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

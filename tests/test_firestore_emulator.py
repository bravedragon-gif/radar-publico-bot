"""Opt-in concurrency test. Refuses real Firestore and non-local emulator hosts."""
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from app import rate_limit as rl


@pytest.mark.skipif(not os.getenv('FIRESTORE_EMULATOR_HOST'), reason='Local Firestore emulator not configured')
def test_firestore_atomic_quota_under_concurrency(monkeypatch):
    host=os.environ['FIRESTORE_EMULATOR_HOST']
    assert host.startswith(('127.0.0.1:', 'localhost:')), 'Only a local emulator is allowed'
    assert os.environ.get('GOOGLE_CLOUD_PROJECT') == 'radar-publico-test', 'Dedicated emulator project required'
    monkeypatch.setenv('GLOBAL_DAILY_UPDATES','1500')
    rl.client.cache_clear()
    db=rl.client()
    # Use fresh document namespaces so an emulator can be shared with other local runs.
    prefix='test_'+uuid4().hex
    class Namespaced:
        def document(self,path):
            collection,key=path.split('/',1)
            return db.document(f'{prefix}_{collection}/{key}')
        def transaction(self,**kwargs):
            return db.transaction(**kwargs)
    monkeypatch.setattr(rl,'client',lambda: Namespaced())
    def attempt(i):
        try:
            return rl.Store().admit(123,i,True,10000)
        except rl.LimitReached:
            return False
        except Exception:
            # Contention can exhaust retries; this must never turn into an admission.
            return False
    with ThreadPoolExecutor(max_workers=20) as pool:
        admitted=sum(pool.map(attempt,range(20)))
    assert 1 <= admitted <= 10
    for i in range(20,40):
        admitted+=bool(attempt(i))
    assert admitted == 10
    record=db.document(f'{prefix}_radar_publico_users/123').get().to_dict()
    assert len(record['timestamps']) == 10

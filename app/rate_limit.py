"""Firestore transactions: rolling user quota, UTC daily budgets and update claims."""
import asyncio
import hashlib
import os
import time
from functools import lru_cache

from google.cloud import firestore


class LimitReached(Exception):
    pass


@lru_cache(maxsize=1)
def client():
    return firestore.Client(project=os.environ.get('GOOGLE_CLOUD_PROJECT', 'dodfpmdfbot'), database='(default)')


def transition(record, now, query, user_limit=10):
    timestamps = [t for t in record.get('timestamps', []) if now-3600 < t <= now]
    if query and len(timestamps) >= user_limit:
        raise LimitReached('user')
    return {'timestamps': timestamps + ([now] if query else [])}


class Store:
    def admit(self, user_id, update_id, query, now=None):
        now = int(time.time()) if now is None else now
        db = client()
        control = db.document('radar_publico_ops/control')
        global_doc = db.document('radar_publico_ops/budget')
        # One bounded document per user, containing recent update IDs and timestamps.
        user = db.document(f'radar_publico_users/{user_id}')

        @firestore.transactional
        def apply(tx):
            config = control.get(transaction=tx, retry=None, timeout=5).to_dict() or {}
            budget = global_doc.get(transaction=tx, retry=None, timeout=5).to_dict() or {}
            record = user.get(transaction=tx, retry=None, timeout=5).to_dict() or {}
            if config.get('suspended', False):
                raise LimitReached('suspended')
            if budget.get('day') != now//86400:
                budget = {'day': now//86400, 'updates': 0, 'external': 0,
                          'pncp_retry_at': budget.get('pncp_retry_at', 0),
                          'compras_retry_at': budget.get('compras_retry_at', 0)}
            recent = {k:v for k,v in record.get('updates', {}).items() if now-86400 < v <= now}
            if str(update_id) in recent:
                return False
            if budget.get('updates', 0) >= int(os.getenv('GLOBAL_DAILY_UPDATES', '1500')):
                raise LimitReached('global')
            denied = False
            try:
                state = transition(record, now, query)
            except LimitReached:
                denied = True
                state = transition(record, now, False)
            # At most 32 IDs; Telegram retries are normally near the original delivery.
            recent[str(update_id)] = now
            state['updates'] = dict(sorted(recent.items(), key=lambda x:x[1])[-32:])
            if 'menu' in record:
                state['menu'] = record['menu']
            tx.set(user, state)
            tx.set(global_doc, dict(budget, updates=budget.get('updates', 0)+1))
            return 'user' if denied else True
        result = apply(db.transaction(max_attempts=3))
        if result == 'user':
            raise LimitReached('user')
        return result

    def menu_get(self, user_id):
        data = client().document(f'radar_publico_users/{user_id}').get(retry=None, timeout=5).to_dict() or {}
        menu = data.get('menu') or {}
        return menu if menu.get('expires', 0) > time.time() else None

    def menu_set(self, user_id, source=None, kind=None):
        client().document(f'radar_publico_users/{user_id}').set(
            {'menu': {'source': source, 'kind': kind, 'expires': int(time.time())+600} if source else {}},
            merge=True, retry=None, timeout=5)

    def reserve(self, source='pncp'):
        db = client()
        ref = db.document('radar_publico_ops/budget')
        @firestore.transactional
        def apply(tx):
            data = ref.get(transaction=tx, retry=None, timeout=5).to_dict() or {}
            now = int(time.time())
            if data.get(source+'_retry_at', 0) > now:
                raise LimitReached(source)
            if data.get('day') != now//86400:
                data = dict(data, day=now//86400, updates=0, external=0)
            if data.get('external', 0) >= int(os.getenv('GLOBAL_DAILY_EXTERNAL', '400')):
                raise LimitReached('external')
            tx.set(ref, dict(data, external=data.get('external', 0)+1))
        apply(db.transaction(max_attempts=3))

    def defer_pncp(self, seconds, source='pncp'):
        db = client()
        ref = db.document('radar_publico_ops/budget')
        @firestore.transactional
        def apply(tx):
            data = ref.get(transaction=tx, retry=None, timeout=5).to_dict() or {}
            data[source+'_retry_at'] = max(data.get(source+'_retry_at', 0), int(time.time()) + seconds)
            tx.set(ref, data)
        apply(db.transaction(max_attempts=3))

    def claim_publication(self, week, digest):
        # create is atomic; an existing or uncertain claim requires operator reconciliation.
        client().document(f'radar_publico_publications/{week}').create(
            {'sha256': digest, 'claimed_at': int(time.time()), 'status': 'claimed'},
            retry=None, timeout=5)

    def cache_get(self, key):
        slot = int(key[:8], 16) % 256
        data = client().document(f'radar_publico_cache/{slot}').get(retry=None, timeout=5).to_dict() or {}
        return data.get('result') if data.get('key') == key and data.get('expires', 0) > time.time() else None

    def cache_set(self, key, result):
        slot = int(key[:8], 16) % 256
        client().document(f'radar_publico_cache/{slot}').set({'key': key, 'expires': int(time.time())+1800, 'result': result}, retry=None, timeout=5)


store = Store()


def cache_key(kind, term, day):
    return hashlib.sha256(f'v2:{kind}:{term}:{day}'.encode()).hexdigest()


async def consume(user_id):
    return await asyncio.to_thread(store.admit, user_id, time.time_ns(), True)

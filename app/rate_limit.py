"""Distributed per-user rate limit backed by Firestore transactions.

The Firestore database must exist. Fail closed when unavailable.
"""
import asyncio
import os
import time
from google.cloud import firestore

LIMIT = 10
WINDOW_SECONDS = 3600

def _consume(user_id: int, now: int) -> bool:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT_ID")
    database = os.environ.get("FIRESTORE_DATABASE", "(default)")
    client = firestore.Client(project=project or None, database=database)
    doc = client.collection("radar_publico_rate_limits").document(str(user_id))
    transaction = client.transaction()

    @firestore.transactional
    def apply(tx):
        snap = doc.get(transaction=tx)
        record = snap.to_dict() if snap.exists else {}
        start = int(record.get("window_start", now))
        count = int(record.get("count", 0))
        if now < start or now - start >= WINDOW_SECONDS:
            start, count = now, 0
        if count >= LIMIT:
            return False
        tx.set(doc, {"window_start": start, "count": count + 1})
        return True

    return apply(transaction)

async def consume(user_id: int) -> bool:
    return await asyncio.to_thread(_consume, user_id, int(time.time()))

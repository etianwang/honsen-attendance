import uuid

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import IdempotencyKey


def claim_idempotency_key(db: Session, key: uuid.UUID) -> bool:
    """Atomically claims a client-generated request UUID.

    Returns True the first time this key is seen (caller should do the real
    write and commit the same transaction). Returns False if it was already
    processed before — a retried request from a flaky network — so the caller
    can just return success without redoing (or duplicating) the write.
    """
    # rowcount is unreliable for INSERT ... ON CONFLICT DO NOTHING under psycopg3
    # (it can report -1 even on a successful insert), so use RETURNING instead:
    # a row comes back only if this key was actually new.
    stmt = pg_insert(IdempotencyKey).values(key=key).on_conflict_do_nothing().returning(IdempotencyKey.key)
    result = db.execute(stmt)
    claimed = result.first() is not None
    return claimed

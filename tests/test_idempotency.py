import uuid

from app.services.idempotency import claim_idempotency_key


def test_idempotency_key_rolls_back_with_the_request(db):
    key = uuid.uuid4()

    assert claim_idempotency_key(db, key)
    db.rollback()

    assert claim_idempotency_key(db, key)
    db.commit()
    assert not claim_idempotency_key(db, key)

import json

import pytest

from app.analytics import compute_stats, export_stats
from app.db import DB


@pytest.fixture
def db(tmp_path):
    return DB(str(tmp_path / "t.sqlite"))


def test_welcome_bonus_once(db):
    assert db.ensure_user(1, "u", "tgads_a", 500)
    assert not db.ensure_user(1, "u", "x", 500)
    assert db.balance(1) == 500


def test_charge_and_insufficient(db):
    db.ensure_user(1, "u", None, 40)
    job = db.create_job(1, "f", {})
    assert db.charge(1, 30, job) == 10
    with pytest.raises(ValueError):
        db.charge(1, 30, job)
    assert db.balance(1) == 10


def test_claim_once(db):
    db.ensure_user(1, "u", None, 500)
    job = db.create_job(1, "f", {})
    assert db.claim_job(job, 1)
    assert not db.claim_job(job, 1)
    assert not db.claim_job(job, 2)


def test_stats(db, tmp_path):
    import time
    db.ensure_user(1, "a", None, 500)
    db.ensure_user(2, "b", None, 500)
    job = db.create_job(1, "f", {})
    db.charge(1, 30, job)
    db.update_job(job, status="done", finished_at=int(time.time()))
    s = export_stats(db, str(tmp_path / "stats.json"))
    assert s["unique_users"] == 2 and s["generations_today"] == 1 and s["spent_r_month"] == 30
    assert json.loads((tmp_path / "stats.json").read_text())["spent_r_today"] == 30


def test_admins(db):
    db.add_admin(42, "felixnamba")
    db.add_admin(42, "felixnamba")
    assert db.admin_chats() == [42]


def test_drop_user_gets_bonus_again(db):
    db.ensure_user(7, "Tester", None, 500)
    db.charge(7, 39, db.create_job(7, "f", {}))
    assert db.drop_user("@tester") == 7 and db.drop_user("tester") is None
    assert db.ensure_user(7, "Tester", None, 500) and db.balance(7) == 500

"""Candidate intake must be repeatable and must never promote community claims."""

from contextlib import closing
import json
import sqlite3

import pytest

from gradmatch.storage import DEFAULT_DATABASE
from scripts.import_csgrad_candidates import import_candidates


COMMIT = "a" * 40


@pytest.fixture
def tracker_file(tmp_path):
    document = {"generated": "2026-10-25", "cycle": "Fall 2027", "rows": [{
        "id": "fixture-mscs", "name": "mscs@fixture", "schoolFull": "Fixture University",
        "official": "Fixture MS", "tier": "SSS", "halt": False, "fee": 125,
        "rounds": [{"date": "2026-12-08", "label": "fixture round"}],
        "lang": {"toefl_old": {"cell": "100*", "kind": "recommended"}},
    }]}
    path = tmp_path / "tracker.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_reimport_is_idempotent_and_claims_remain_unverified(tracker_file, tmp_path):
    target = tmp_path / "candidates.db"
    import_candidates(tracker_file, target, COMMIT, expected_count=1)
    report = import_candidates(tracker_file, target, COMMIT, expected_count=1)
    assert report["imported_rows"] == 1
    assert report["recommendation_eligible"] == 0
    with closing(sqlite3.connect(target)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM candidate_programs").fetchone()[0] == 1
        status, source_tier, attributes = connection.execute(
            "SELECT verification_status, source_tier, attributes_json FROM candidate_programs"
        ).fetchone()
        assert status == "community_unverified" and source_tier == "SSS"
        details = json.loads(attributes)
        assert details["tuition_total_usd"] is None
        assert details["application_fee_raw"] == 125
        assert details["personalized_tier"] is None
        assert details["reported_language"]["toefl_old"]["kind"] == "recommended"


def test_duplicate_ids_fail_before_creating_a_database(tracker_file, tmp_path):
    document = json.loads(tracker_file.read_text(encoding="utf-8"))
    document["rows"].append(document["rows"][0])
    tracker_file.write_text(json.dumps(document), encoding="utf-8")
    target = tmp_path / "candidates.db"
    with pytest.raises(ValueError, match="Duplicate source id"):
        import_candidates(tracker_file, target, COMMIT, expected_count=2)
    assert not target.exists()


def test_candidate_import_cannot_target_the_app_catalog(tracker_file):
    with pytest.raises(ValueError, match="separate candidate database"):
        import_candidates(tracker_file, DEFAULT_DATABASE, COMMIT, expected_count=1)


def test_wrong_count_is_rejected_before_creating_a_database(tracker_file, tmp_path):
    target = tmp_path / "candidates.db"
    with pytest.raises(ValueError, match="Expected 83 tracker rows"):
        import_candidates(tracker_file, target, COMMIT)
    assert not target.exists()

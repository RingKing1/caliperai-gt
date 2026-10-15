"""Unit tests for pure helpers in the efficiency domain."""
from uuid import UUID

from app.services.efficiency.common import generate_alias


def test_generate_alias_is_deterministic():
    uid = UUID("12345678-1234-5678-1234-567812345678")
    assert generate_alias(uid) == generate_alias(uid)
    assert generate_alias(uid).startswith("Annotator ")


def test_generate_alias_range_is_1_to_100():
    # index derives from the first 4 id bytes modulo 100
    for hex_prefix in ("00000000", "00000063", "00000064", "ffffffff"):
        uid = UUID(f"{hex_prefix}-0000-0000-0000-000000000000")
        number = int(generate_alias(uid).split()[-1])
        assert 1 <= number <= 100


def test_generate_alias_seed_is_accepted_but_stable():
    uid = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    assert generate_alias(uid, seed=5) == generate_alias(uid, seed=5)

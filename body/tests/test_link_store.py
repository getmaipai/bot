"""G4's own acceptance: the sealed pairing file, fail-soft and atomic."""

from __future__ import annotations

import stat

from maipai_body.link.store import HubPairing, PairingStore


def _pairing(**overrides) -> HubPairing:
    defaults = dict(
        base_url="http://192.0.2.10:80",
        device_token="a-real-device-token",
        hub_instance_id="hub-abc123",
        fingerprint="hub-abc123",
    )
    defaults.update(overrides)
    return HubPairing(**defaults)


def test_load_returns_none_when_no_file_exists(tmp_path):
    store = PairingStore(tmp_path / "pairing.json")

    assert store.load() is None


def test_save_then_load_round_trips(tmp_path):
    store = PairingStore(tmp_path / "pairing.json")
    pairing = _pairing()

    store.save(pairing)

    assert store.load() == pairing


def test_saved_file_is_0o600(tmp_path):
    path = tmp_path / "pairing.json"
    store = PairingStore(path)

    store.save(_pairing())

    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600


def test_save_replaces_atomically_leaving_no_tmp_file(tmp_path):
    path = tmp_path / "pairing.json"
    store = PairingStore(path)

    store.save(_pairing())
    store.save(_pairing(device_token="a-different-token"))

    assert not (tmp_path / "pairing.json.tmp").exists()
    assert store.load().device_token == "a-different-token"


def test_a_corrupt_file_reads_as_unpaired_not_a_crash(tmp_path):
    path = tmp_path / "pairing.json"
    path.write_text("not valid json at all {{{", encoding="utf-8")
    store = PairingStore(path)

    assert store.load() is None


def test_a_file_missing_a_required_field_reads_as_unpaired(tmp_path):
    path = tmp_path / "pairing.json"
    path.write_text('{"base_url": "http://x"}', encoding="utf-8")
    store = PairingStore(path)

    assert store.load() is None


def test_clear_removes_the_file(tmp_path):
    path = tmp_path / "pairing.json"
    store = PairingStore(path)
    store.save(_pairing())

    store.clear()

    assert not path.exists()
    assert store.load() is None


def test_clear_is_safe_when_nothing_is_paired(tmp_path):
    store = PairingStore(tmp_path / "pairing.json")

    store.clear()  # must not raise

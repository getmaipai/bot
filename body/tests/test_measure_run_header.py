"""Every recorded run carries the header dev.md section 11 asks for and never
a hostname or a household recording (docs/dev/measurements.md's own rule)."""

from __future__ import annotations

import json

import pytest

from maipai_body.measure.run_header import (
    new_run_header,
    upsert_markdown_section,
    write_run,
)


def test_header_carries_mode_daemon_version_profile_and_date():
    header = new_run_header(
        row="M-R2", mode="sim", profile_id="reachy_mini", daemon_version="1.11.0", date="2026-10-05"
    )
    assert header == {
        "row": "M-R2",
        "mode": "sim",
        "profile": "reachy_mini",
        "daemon_version": "1.11.0",
        "image_release": None,
        "date": "2026-10-05",
    }


def test_header_takes_the_image_release_when_the_unit_reports_one():
    header = new_run_header(
        row="M-R1",
        mode="unit",
        profile_id="reachy_mini",
        daemon_version="1.11.0",
        image_release="2026.09",
        date="2026-10-05",
    )
    assert header["image_release"] == "2026.09"


def test_a_mode_other_than_sim_or_unit_is_refused():
    with pytest.raises(ValueError):
        new_run_header(row="M-R2", mode="bench", profile_id="reachy_mini", daemon_version="1")


def test_header_never_contains_a_hostname_key():
    header = new_run_header(row="M-R1", mode="sim", profile_id="p", daemon_version="1")
    assert not {"host", "hostname", "node"} & set(header)


def test_write_run_writes_header_and_rows_as_json_and_returns_the_path(tmp_path):
    header = new_run_header(
        row="M-R5", mode="sim", profile_id="reachy_mini", daemon_version="1.11.0", date="2026-10-05"
    )
    path = write_run(tmp_path, header, [{"a": 1}])
    assert path.parent == tmp_path
    assert path.name == "M-R5-sim-2026-10-05.json"
    assert json.loads(path.read_text()) == {"header": header, "rows": [{"a": 1}]}


def test_write_run_refuses_a_row_that_smuggles_in_a_hostname(tmp_path):
    header = new_run_header(row="M-R5", mode="sim", profile_id="p", daemon_version="1")
    with pytest.raises(ValueError):
        write_run(tmp_path, header, [{"hostname": "reachy-1234"}])


def test_upsert_replaces_only_the_named_section_and_keeps_the_rest(tmp_path):
    path = tmp_path / "measurements.md"
    path.write_text("# Bench\n\n## M-R2: a (sim), 2026-09-27\n\nold\n\n## M-R9: other\n\nkeep\n")
    upsert_markdown_section(path, "## M-R2:", "## M-R2: a (sim), 2026-10-05\n\nnew\n")
    text = path.read_text()
    assert "old" not in text
    assert "new" in text
    assert "keep" in text
    assert text.count("## M-R2:") == 1


def test_upsert_appends_when_the_section_is_new(tmp_path):
    path = tmp_path / "measurements.md"
    path.write_text("# Bench\n")
    upsert_markdown_section(path, "## M-R5:", "## M-R5: link (sim), 2026-10-05\n\nrows\n")
    assert path.read_text().endswith("rows\n")
    assert "# Bench" in path.read_text()

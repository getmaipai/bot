"""The measurement scripts import, document themselves, and refuse unsafe or
incomplete invocations before they touch a daemon, a hub or a radio.

These are characterization tests of the scripts' own guards: nothing here
needs a daemon, so they run everywhere.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent / "scripts"
ALL = (
    "measure_expr01.py",
    "measure_mr1_budget.py",
    "measure_mr2_cue_motion.py",
    "measure_mr3_wake_doa.py",
    "measure_mr4_battery.py",
    "measure_mr5_link.py",
    "measure_rm07_egress.py",
)


def _run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.parametrize("script", ALL)
def test_every_script_imports_and_prints_its_usage(script):
    result = _run(script, "--help")
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout


@pytest.mark.parametrize(
    "script",
    [s for s in ALL if s != "measure_expr01.py"],
)
def test_every_new_script_documents_the_exact_command_to_run_on_the_unit(script):
    """The unit runs the installed wheel in the daemon's apps venv (scripts/install-reachy.sh);
    `uv run` cannot resolve there, because the lockfile is scoped to the dev Mac."""
    text = (SCRIPTS / script).read_text()
    assert "/venvs/apps_venv/bin/python scripts/" + script in text


def test_mr2_refuses_a_held_head_run_on_the_simulator():
    result = _run("measure_mr2_cue_motion.py", "--mode", "sim", "--hold", "hand")
    assert result.returncode == 2
    assert "needs the unit" in result.stderr


def test_mr1_refuses_to_record_a_stand_in_rehearsal():
    result = _run(
        "measure_mr1_budget.py",
        "--config",
        "pod",
        "--stand-in-hub",
        "--record",
        "--utterance-wav",
        "x.wav",
    )
    assert result.returncode == 2
    assert "never record" in result.stderr


def test_mr1_robot_config_needs_the_local_speech_services():
    result = _run("measure_mr1_budget.py", "--config", "robot", "--utterance-wav", "x.wav")
    assert result.returncode == 2
    assert "--stt-base-url" in result.stderr


def test_mr1_daemon_alone_refuses_turns():
    result = _run("measure_mr1_budget.py", "--config", "daemon", "--utterance-wav", "x.wav")
    assert result.returncode == 2
    assert "--turn-interval-s 0" in result.stderr


def test_mr3_needs_the_wake_models():
    result = _run("measure_mr3_wake_doa.py", "recall", "--condition", "quiet_1m")
    assert result.returncode == 2
    assert "--models-dir" in result.stderr


def test_mr4_conversation_workload_needs_an_utterance():
    result = _run("measure_mr4_battery.py", "run", "--workload", "conversation", "--charging", "no")
    assert result.returncode != 0
    assert "--utterance-wav" in result.stderr


def test_mr5_wifi_trials_need_the_unit_the_hub_and_both_radio_commands():
    result = _run("measure_mr5_link.py", "--mode", "sim", "--wifi-trials", "1")
    assert result.returncode == 2
    assert "--mode unit" in result.stderr
    result = _run(
        "measure_mr5_link.py", "--mode", "unit", "--wifi-trials", "1", "--hub-url", "http://h"
    )
    assert result.returncode == 2
    assert "--wifi-off" in result.stderr

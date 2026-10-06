"""Release preparation and SSH plan stay local and reviewable."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SCRIPTS = ROOT / "scripts"


def test_install_dry_run_prints_the_full_plan_without_syncing_or_ssh(tmp_path):
    env, sync_calls = _uv_sync_stub(tmp_path)
    result = subprocess.run(
        [str(SCRIPTS / "install-reachy.sh"), "--dry-run", "example-host", "/tmp/future.whl"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert not sync_calls.exists()
    assert "scp /tmp/future.whl" in result.stdout
    assert "pollen@example-host:/tmp/" in result.stdout
    assert "onnxruntime-1.30.0" in result.stdout
    assert "startup-app" in result.stdout
    assert "REMOVE_VENDOR_APPS" in result.stdout
    assert "systemctl restart reachy-mini-daemon" in result.stdout
    assert "rm\\ -f\\ \\'/tmp/future.whl\\'" in result.stdout


def test_release_builder_stages_wheel_and_sha256_without_publishing(tmp_path):
    stage = ROOT / "dist/bot-release/v0.1.0"
    try:
        subprocess.run(
            [str(SCRIPTS / "prepare-bot-release.sh"), "v0.1.0"],
            check=True,
            env={**os.environ, "MAIPAI_SKIP_WHEELHOUSE": "1"},
        )
        wheel = stage / "maipai_bot-0.1.0-py3-none-any.whl"
        checksum = stage / f"{wheel.name}.sha256"
        assert wheel.is_file()
        assert checksum.read_text().split()[0] == hashlib.sha256(wheel.read_bytes()).hexdigest()
        assert "never creates" in (SCRIPTS / "prepare-bot-release.sh").read_text()
    finally:
        if stage.exists():
            for path in stage.iterdir():
                path.unlink()
            stage.rmdir()


def test_aarch64_voice_resolution_pins_onnxruntime_and_base_avoids_mujoco(tmp_path):
    results = {}
    for label, extra in (("base", []), ("voice", ["--extra", "voice"])):
        out = tmp_path / f"{label}.txt"
        result = subprocess.run(
            [
                "uv",
                "pip",
                "compile",
                "--python-platform",
                "aarch64-unknown-linux-gnu",
                "pyproject.toml",
                *extra,
                "-o",
                str(out),
            ],
            cwd=ROOT / "body",
            capture_output=True,
            text=True,
        )
        # The full resolver currently cannot build the transitive pygobject
        # dependency on macOS without cairo/pkg-config. Preserve a clear
        # skip so Linux CI can establish this acceptance fully.
        if result.returncode:
            assert "pygobject" in result.stderr.lower()
            pytest.skip("full aarch64 resolution needs Linux-compatible pygobject build metadata")
        results[label] = out.read_text()
    assert "mujoco==" not in results["base"]
    assert "onnxruntime==1.30.0" in results["voice"]


EYES_SETUP = SCRIPTS / "udev/reachy-eyes-setup.sh"


def _uv_sync_stub(tmp_path):
    """Make any accidental uv sync in installer dry-runs harmless and visible."""
    bin_dir = tmp_path / "uv-stub"
    bin_dir.mkdir(parents=True, exist_ok=True)
    calls = tmp_path / "uv-calls.log"
    stub = bin_dir / "uv"
    stub.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{calls}"\nexit 99\n')
    stub.chmod(0o755)
    return {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "MAIPAI_REACHY_HUB_ADDRESS": "192.168.1.10",
        "MAIPAI_REACHY_ROUTER_ADDRESS": "192.168.1.1",
        "MAIPAI_REACHY_SUBNET": "192.168.1.0/24",
    }, calls


def _stub_bin(tmp_path, unit_user):
    """A PATH of stubs that log what the setup script asks of the host."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    members = tmp_path / "members"
    members.write_text("")
    (bin_dir / "systemctl").write_text(f'#!/bin/sh\necho "{unit_user}"\n')
    (bin_dir / "id").write_text(f'#!/bin/sh\ncat "{members}"\n')
    (bin_dir / "usermod").write_text(
        f'#!/bin/sh\necho "usermod $*" >> "{log}"\necho "dialout" > "{members}"\n'
    )
    (bin_dir / "udevadm").write_text(f'#!/bin/sh\necho "udevadm $*" >> "{log}"\n')
    for stub in bin_dir.iterdir():
        stub.chmod(0o755)
    return bin_dir, log


def _run_eyes_setup(tmp_path, bin_dir, *args):
    rules = tmp_path / "rules.d"
    rules.mkdir(exist_ok=True)
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "MAIPAI_UDEV_RULES_DIR": str(rules),
    }
    return subprocess.run(
        ["bash", str(EYES_SETUP), *args], env=env, capture_output=True, text=True
    ), rules / "99-maipai-eyes.rules"


def test_eyes_setup_installs_only_the_fixed_eyes_rule_and_group_idempotently(tmp_path):
    bin_dir, log = _stub_bin(tmp_path, "reachy")
    first, rule = _run_eyes_setup(tmp_path, bin_dir)
    assert first.returncode == 0, first.stderr
    text = rule.read_text().strip()
    assert text.splitlines() == [
        "# Managed by MaiPai Bot's install step. Reachy Eyes serial port.",
        'SUBSYSTEM=="tty", ATTRS{idVendor}=="2e8a", ATTRS{idProduct}=="10fc", '
        'MODE="0660", GROUP="dialout", SYMLINK+="maipai-eyes", '
        'ENV{ID_MM_DEVICE_IGNORE}="1"',
    ]
    assert "usermod -aG dialout reachy" in log.read_text()
    assert "udevadm control --reload-rules" in log.read_text()

    log.write_text("")
    second, _ = _run_eyes_setup(tmp_path, bin_dir)
    assert second.returncode == 0, second.stderr
    assert log.read_text() == ""
    assert rule.read_text().strip() == text


def test_eyes_setup_skips_group_when_the_daemon_runs_as_root(tmp_path):
    bin_dir, log = _stub_bin(tmp_path, "")
    result, rule = _run_eyes_setup(tmp_path, bin_dir)
    assert result.returncode == 0, result.stderr
    assert rule.is_file()
    assert "usermod" not in log.read_text()


def test_eyes_setup_refuses_missing_or_malformed_usb_ids(tmp_path):
    bin_dir, log = _stub_bin(tmp_path, "reachy")
    invalid_pairs = (
        ("0x2e8a",),
        ("zzzz", "10fc"),
        ("2e8a", "0003"),
        ("1234", "5678"),
        ('2e8a"', "10fc"),
    )
    for args in invalid_pairs:
        result, rule = _run_eyes_setup(tmp_path, bin_dir, *args)
        assert result.returncode != 0
        assert not rule.exists()
    assert not log.exists() or log.read_text() == ""


def test_install_dry_run_plans_fixed_eyes_setup_without_syncing(tmp_path):
    # A failing uv stub makes this test independent of uv sync and the
    # platform-specific lockfile; the install dry-run must not resolve it.
    env, sync_calls = _uv_sync_stub(tmp_path)
    base = [str(SCRIPTS / "install-reachy.sh"), "--dry-run", "example-host", "/tmp/future.whl"]
    plain = subprocess.run(base, check=True, capture_output=True, text=True, env=env)
    assert not sync_calls.exists()
    assert "reachy-eyes-setup.sh" in plain.stdout
    assert "2e8a" not in plain.stdout and "10fc" not in plain.stdout
    assert "uf2" not in plain.stdout.lower()
    assert "reachy_eyes" not in plain.stdout


def test_pyserial_is_declared_directly_and_the_installer_never_ships_vendor_eyes_code():
    pyproject = (ROOT / "body/pyproject.toml").read_text()
    assert '"pyserial>=3.5,<4"' in pyproject
    for path in (SCRIPTS / "install-reachy.sh", EYES_SETUP):
        if path.exists():
            text = path.read_text().lower()
            assert "eyes.uf2" not in text
            assert "pip install reachy_eyes" not in text
            assert "reachy-eyes " not in text
    assert "pyserial" in (ROOT / "NOTICE").read_text().lower()


def test_daemon_install_dry_run_uses_hardened_offline_plan(tmp_path):
    env, sync_calls = _uv_sync_stub(tmp_path)
    env.update(
        MAIPAI_REACHY_HUB_ADDRESS="192.168.1.10",
        MAIPAI_REACHY_ROUTER_ADDRESS="192.168.1.1",
        MAIPAI_REACHY_SUBNET="192.168.1.0/24",
    )
    result = subprocess.run(
        [str(SCRIPTS / "install-reachy.sh"), "--dry-run", "example-host", "/tmp/future.whl"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert not sync_calls.exists()
    plan = result.stdout.lower()
    for required in (
        "--dataset-update-interval 0",
        "--no-preload-datasets",
        "--fastapi-host 127.0.0.1",
        "hf_hub_offline=1",
        "malloc_arena_max=2",
        "nftables",
        "systemd-timesyncd",
        "apt-daily.timer",
        "apt-daily-upgrade.timer",
        "delete /api/hf-auth/token",
        "reachy-mini==1.11.0",
        "127.0.0.1:8042",
    ):
        assert required in plan
    assert "--no-media" not in plan
    assert "pypi" not in plan
    assert plan.count("daemon pin: reachy-mini==1.11.0") == 1
    assert plan.count("daemon config: turn_enabled=false") == 1
    assert plan.count("delete /api/hf-auth/token") == 1
    assert plan.count("firewall: nftables hub-only egress") == 1
    assert plan.count("hub-only ssh") == 1
    assert plan.count("masked timers:") == 1
    assert plan.count("settings app: http://127.0.0.1:8042") == 1


def test_daemon_drop_in_sets_offline_mode_and_all_required_flags():
    configure = (SCRIPTS / "robot-conf/configure.sh").read_text()
    assert (
        "reachy-mini-daemon --dataset-update-interval 0 --no-preload-datasets "
        "--fastapi-host 127.0.0.1"
    ) in configure
    assert "Environment=HF_HUB_OFFLINE=1" in configure
    assert (
        "UnsetEnvironment=HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy"
    ) in configure
    assert 'MAIPAI_TAILNET_ENABLED" = 1' in configure
    assert (
        "systemctl mask --now systemd-timesyncd.service apt-daily.timer apt-daily-upgrade.timer"
    ) in configure


def test_token_removal_precedes_daemon_restart_in_installer():
    installer = (SCRIPTS / "install-reachy.sh").read_text()
    token_delete = installer.index("DELETE http://127.0.0.1:$DAEMON_PORT/api/hf-auth/token")
    daemon_restart = installer.index('"== restarting reachy-mini-daemon"')
    assert token_delete < daemon_restart


def test_daemon_hardening_assets_encode_hub_only_egress_and_loopback_settings():
    conf = SCRIPTS / "robot-conf"
    assert (conf / "configure.sh").is_file()
    nft = (conf / "maipai.nft").read_text()
    assert "policy drop" in nft
    assert "224.0.0.251" in nft
    assert "dhcp" in nft.lower()
    assert "tailnet" in nft.lower()
    app = (ROOT / "body/maipai_body/app.py").read_text()
    assert 'SETTINGS_APP_URL = "http://127.0.0.1:8042"' in app

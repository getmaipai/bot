"""BOT-SELF-TEST-02: the command line that runs the robot's checks from a
terminal. A fake opener and a fake runner cover the client and the argument
handling without a socket; one real ThreadingHTTPServer on port 0 in a
thread implements both service routes and is used for the end to end
tests, including the Origin header the service's same-origin check needs."""

from __future__ import annotations

import http.server
import io
import json
import threading
import urllib.error
from collections.abc import Callable
from typing import Any

import pytest

import maipai_body.selftest.__main__ as selftest_main
from maipai_body.selftest import CheckResult, Status, format_report
from maipai_body.selftest.client import (
    SelfTestServerError,
    SelfTestUnreachable,
    fetch_checks,
    results_from_json,
    results_to_json,
    run_remote,
)

CHECKS = [
    {"name": "led", "title": "LED looks"},
    {"name": "movement", "title": "Head movement"},
]


def server_results(only: list[str] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for check in CHECKS:
        if only is not None and check["name"] not in only:
            continue
        rows.append(
            {
                "name": check["name"],
                "status": "pass",
                "detail": f"{check['name']} ok from the wire",
                "fix": "",
                "seconds": 0.25,
            }
        )
    return rows


def make_server() -> http.server.ThreadingHTTPServer:
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def _send(self, code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/selftest/checks":
                self._send(200, {"checks": CHECKS})
            else:
                self._send(404, {"error": "no such route"})

        def do_POST(self) -> None:
            if self.path != "/selftest/run":
                self._send(404, {"error": "no such route"})
                return
            origin = self.headers.get("Origin")
            self.server.origin_seen = origin
            self.server.content_type_seen = self.headers.get("Content-Type")
            if origin != f"http://127.0.0.1:{self.server.server_port}":
                self._send(400, {"error": "cross-origin request"})
                return
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            only = body.get("only")
            self.server.only_seen = only
            names = {check["name"] for check in CHECKS}
            if only is not None and any(name not in names for name in only):
                unknown = ", ".join(sorted(name for name in only if name not in names))
                self._send(400, {"error": f"unknown check name(s): {unknown}"})
                return
            self._send(200, {"results": server_results(only)})

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.origin_seen = None
    server.content_type_seen = None
    server.only_seen = None
    return server


@pytest.fixture
def server():
    httpd = make_server()
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        thread.join(timeout=2)


def base_url(httpd: http.server.ThreadingHTTPServer) -> str:
    return f"http://127.0.0.1:{httpd.server_port}"


def make_opener(
    payload: dict[str, Any] | None, calls: list, *, error: Exception | None = None
) -> Callable:
    class Response:
        def __init__(self, payload: dict[str, Any]) -> None:
            self._data = json.dumps(payload).encode()

        def read(self) -> bytes:
            return self._data

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

    def opener(request, timeout=None):
        calls.append((request, timeout))
        if error is not None:
            raise error
        return Response(payload or {})

    return opener


def recording_runner(results: list[CheckResult], calls: list) -> Callable:
    def runner(base: str, only: list[str] | None = None) -> list[CheckResult]:
        calls.append((base, only))
        return results

    return runner


def test_results_json_round_trip() -> None:
    results = [
        CheckResult(name="led", status=Status.PASS, detail="Showed 5 looks", seconds=1.5),
        CheckResult(
            name="movement",
            status=Status.FAIL,
            detail="did not move",
            fix="Check the cable.",
            seconds=0.25,
        ),
        CheckResult(name="camera", status=Status.SKIP, detail="no camera", fix="Not available."),
    ]
    payload = results_to_json(results)
    assert payload == {
        "results": [
            {
                "name": "led",
                "status": "pass",
                "detail": "Showed 5 looks",
                "fix": "",
                "seconds": 1.5,
            },
            {
                "name": "movement",
                "status": "fail",
                "detail": "did not move",
                "fix": "Check the cable.",
                "seconds": 0.25,
            },
            {
                "name": "camera",
                "status": "skip",
                "detail": "no camera",
                "fix": "Not available.",
                "seconds": 0.0,
            },
        ]
    }
    assert results_from_json(payload) == results


def test_results_from_json_defaults_missing_fields() -> None:
    results = results_from_json({"results": [{"name": "led", "status": "pass"}]})
    assert results == [CheckResult(name="led", status=Status.PASS, detail="", fix="", seconds=0.0)]


def test_results_from_json_unknown_status_raises_plain_sentence() -> None:
    with pytest.raises(ValueError, match="Unknown status") as excinfo:
        results_from_json({"results": [{"name": "led", "status": "meh"}]})
    assert "meh" in str(excinfo.value)
    assert "led" in str(excinfo.value)


def test_results_from_json_rejects_bad_shape() -> None:
    with pytest.raises(ValueError):
        results_from_json({"nope": 1})
    with pytest.raises(ValueError):
        results_from_json({"results": "not a list"})
    with pytest.raises(ValueError):
        results_from_json({"results": [{}]})


def test_fetch_checks_gets_checks_route_and_sends_origin() -> None:
    calls: list = []
    payload = {"checks": CHECKS}
    checks = fetch_checks("http://127.0.0.1:8767", opener=make_opener(payload, calls))
    assert checks == CHECKS
    request, timeout = calls[0]
    assert request.full_url == "http://127.0.0.1:8767/selftest/checks"
    assert request.get_method() == "GET"
    headers = dict(request.header_items())
    assert headers["Origin"] == "http://127.0.0.1:8767"
    assert timeout == 10


def test_fetch_checks_unreachable_raises_plain_sentence() -> None:
    calls: list = []
    error = urllib.error.URLError("connection refused")
    with pytest.raises(SelfTestUnreachable) as excinfo:
        fetch_checks("http://127.0.0.1:9", opener=make_opener(None, calls, error=error))
    assert str(excinfo.value) == (
        "The robot service did not answer at http://127.0.0.1:9/selftest/checks. "
        "Start the Bot, or pass --url with its address."
    )


def test_run_remote_posts_only_and_origin_as_json() -> None:
    calls: list = []
    payload = {"results": [{"name": "led", "status": "pass", "detail": "ok"}]}
    results = run_remote(
        "http://127.0.0.1:8767", ["led", "movement"], opener=make_opener(payload, calls)
    )
    assert results == [CheckResult(name="led", status=Status.PASS, detail="ok")]
    request, timeout = calls[0]
    assert request.full_url == "http://127.0.0.1:8767/selftest/run"
    assert request.get_method() == "POST"
    headers = dict(request.header_items())
    assert headers["Content-type"] == "application/json"
    assert headers["Origin"] == "http://127.0.0.1:8767"
    assert json.loads(request.data) == {"only": ["led", "movement"]}
    assert timeout == 120


def test_run_remote_without_only_sends_empty_body() -> None:
    calls: list = []
    payload = {"results": []}
    assert run_remote("http://127.0.0.1:8767", opener=make_opener(payload, calls)) == []
    request, _ = calls[0]
    assert json.loads(request.data) == {}


def test_run_remote_unreachable_raises_plain_sentence() -> None:
    calls: list = []
    error = urllib.error.URLError("connection refused")
    with pytest.raises(SelfTestUnreachable) as excinfo:
        run_remote("http://127.0.0.1:9", opener=make_opener(None, calls, error=error))
    assert str(excinfo.value) == (
        "The robot service did not answer at http://127.0.0.1:9/selftest/run. "
        "Start the Bot, or pass --url with its address."
    )


def test_run_remote_400_with_error_json_raises_server_error() -> None:
    calls: list = []
    http_error = urllib.error.HTTPError(
        "http://127.0.0.1:8767/selftest/run",
        400,
        "Bad Request",
        {},
        io.BytesIO(json.dumps({"error": "unknown check name(s): zzz"}).encode()),
    )
    with pytest.raises(SelfTestServerError) as excinfo:
        run_remote(
            "http://127.0.0.1:8767", ["zzz"], opener=make_opener(None, calls, error=http_error)
        )
    assert str(excinfo.value) == "unknown check name(s): zzz"


def test_run_remote_400_without_error_json_is_unreachable() -> None:
    calls: list = []
    http_error = urllib.error.HTTPError(
        "http://127.0.0.1:9/selftest/run", 400, "Bad Request", {}, io.BytesIO(b"no json here")
    )
    with pytest.raises(SelfTestUnreachable) as excinfo:
        run_remote("http://127.0.0.1:9", opener=make_opener(None, calls, error=http_error))
    assert str(excinfo.value) == (
        "The robot service did not answer at http://127.0.0.1:9/selftest/run. "
        "Start the Bot, or pass --url with its address."
    )


def test_main_prints_report_and_returns_zero_when_all_pass() -> None:
    calls: list = []
    results = [CheckResult(name="led", status=Status.PASS, detail="led ok")]
    out = io.StringIO()
    rc = selftest_main.main(
        ["--url", "http://127.0.0.1:1234"], stdout=out, runner=recording_runner(results, calls)
    )
    assert rc == 0
    assert out.getvalue() == format_report(results) + "\n"
    assert calls == [("http://127.0.0.1:1234", None)]


def test_main_returns_one_when_a_check_failed() -> None:
    calls: list = []
    results = [
        CheckResult(name="led", status=Status.PASS, detail="ok"),
        CheckResult(name="movement", status=Status.FAIL, detail="no", fix="fix it"),
    ]
    out = io.StringIO()
    rc = selftest_main.main([], stdout=out, runner=recording_runner(results, calls))
    assert rc == 1
    assert out.getvalue() == format_report(results) + "\n"


def test_main_defaults_url_and_parses_the_comma_only_list() -> None:
    calls: list = []
    results = [CheckResult(name="led", status=Status.PASS, detail="ok")]
    out = io.StringIO()
    rc = selftest_main.main(
        ["--only", "led, movement"], stdout=out, runner=recording_runner(results, calls)
    )
    assert rc == 0
    assert calls == [("http://127.0.0.1:8767", ["led", "movement"])]


def test_main_unreachable_prints_sentence_to_stderr_and_returns_two(capsys) -> None:
    sentence = (
        "The robot service did not answer at http://127.0.0.1:8767/selftest/run. "
        "Start the Bot, or pass --url with its address."
    )

    def runner(base: str, only: list[str] | None = None) -> list[CheckResult]:
        raise SelfTestUnreachable(sentence)

    out = io.StringIO()
    rc = selftest_main.main([], stdout=out, runner=runner)
    assert rc == 2
    assert out.getvalue() == ""
    assert sentence in capsys.readouterr().err


def test_main_server_error_prints_the_servers_sentence_and_returns_two(capsys) -> None:
    def runner(base: str, only: list[str] | None = None) -> list[CheckResult]:
        raise SelfTestServerError("unknown check name(s): zzz; valid names: led, movement")

    rc = selftest_main.main(["--only", "zzz"], stdout=io.StringIO(), runner=runner)
    assert rc == 2
    assert "unknown check name(s): zzz; valid names: led, movement" in capsys.readouterr().err


def test_main_list_prints_names_and_titles(monkeypatch) -> None:
    def fake_fetch(base: str):
        return CHECKS

    monkeypatch.setattr(selftest_main, "fetch_checks", fake_fetch)
    out = io.StringIO()
    rc = selftest_main.main(["--list", "--url", "http://127.0.0.1:9"], stdout=out)
    assert rc == 0
    assert out.getvalue().splitlines() == ["led  LED looks", "movement  Head movement"]


def test_main_list_unreachable_returns_two(capsys, monkeypatch) -> None:
    def fake_fetch(base: str):
        raise SelfTestUnreachable(
            "The robot service did not answer at http://127.0.0.1:9/selftest/checks. "
            "Start the Bot, or pass --url with its address."
        )

    monkeypatch.setattr(selftest_main, "fetch_checks", fake_fetch)
    rc = selftest_main.main(["--list", "--url", "http://127.0.0.1:9"], stdout=io.StringIO())
    assert rc == 2
    assert "did not answer at http://127.0.0.1:9/selftest/checks" in capsys.readouterr().err


def test_real_server_round_trip_sends_origin_and_json(server) -> None:
    base = base_url(server)
    out = io.StringIO()
    rc = selftest_main.main(["--url", base], stdout=out, runner=run_remote)
    assert rc == 0
    assert server.origin_seen == base
    assert server.content_type_seen == "application/json"
    assert server.only_seen is None
    expected = format_report(results_from_json({"results": server_results(None)}))
    assert out.getvalue() == expected + "\n"


def test_real_server_only_filter_is_sent_and_respected(server) -> None:
    base = base_url(server)
    out = io.StringIO()
    rc = selftest_main.main(["--url", base, "--only", "led"], stdout=out, runner=run_remote)
    assert rc == 0
    assert server.only_seen == ["led"]
    lines = out.getvalue().splitlines()
    assert "led" in lines[0]
    assert "movement" not in "\n".join(lines[:-1])
    assert lines[-1] == "1 passed, 0 failed, 0 skipped"


def test_real_server_unknown_only_returns_two_with_the_servers_error(server, capsys) -> None:
    base = base_url(server)
    rc = selftest_main.main(
        ["--url", base, "--only", "zzz"], stdout=io.StringIO(), runner=run_remote
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "unknown check name(s): zzz" in err


def test_report_contains_only_what_the_server_returned(server) -> None:
    base = base_url(server)
    out = io.StringIO()
    selftest_main.main(["--url", base], stdout=out, runner=run_remote)
    report = out.getvalue()
    # The titles exist only in the /selftest/checks reply, never in the run
    # reply, so they must not leak into the report either.
    assert "LED looks" not in report
    assert "Head movement" not in report
    expected = format_report(results_from_json({"results": server_results(None)}))
    assert report == expected + "\n"


def test_run_remote_against_a_closed_port_is_unreachable() -> None:
    httpd = make_server()
    port = httpd.server_port
    httpd.server_close()
    with pytest.raises(SelfTestUnreachable) as excinfo:
        run_remote(f"http://127.0.0.1:{port}")
    assert str(excinfo.value) == (
        f"The robot service did not answer at http://127.0.0.1:{port}/selftest/run. "
        "Start the Bot, or pass --url with its address."
    )

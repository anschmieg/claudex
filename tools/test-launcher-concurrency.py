#!/usr/bin/env python3
"""Native four-platform Claudex session smoke; synthetic auth, zero inference."""
import os, platform, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error
from pathlib import Path

root = Path(__file__).resolve().parent.parent
target = {
    ("Darwin", "arm64"): "darwin-arm64",
    ("Darwin", "x86_64"): "darwin-x86_64",
    ("Linux", "aarch64"): "linux-arm64",
    ("Linux", "arm64"): "linux-arm64",
    ("Linux", "x86_64"): "linux-x86_64",
}.get((platform.system(), platform.machine().lower()))
if not target:
    sys.exit("Unsupported native target")
shunt = root / "bin" / target / "shunt"
transport = root / "bin" / target / "claudex-transport"
app = root / "claudex"
if any(not p.is_file() or not os.access(p, os.X_OK) for p in (shunt, transport, app)):
    sys.exit("Missing native binaries (build pinned sources first)")

def port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

def status(port_number, token=None):
    headers = {} if token is None else {"Authorization": "Bearer " + token}
    req = urllib.request.Request(f"http://127.0.0.1:{port_number}/v1/models", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except urllib.error.URLError:
        return 0

def wait(predicate, label):
    for _ in range(160):
        if predicate():
            return
        time.sleep(.08)
    raise AssertionError("Timeout: " + label)

def run(app, env, *args, success=True):
    result = subprocess.run([str(app), *args], env=env, cwd=root,
                            text=True, capture_output=True, timeout=25)
    if (result.returncode == 0) != success:
        raise AssertionError(f"{args}: exit={result.returncode} {result.stderr[-900:]}")
    return result

with tempfile.TemporaryDirectory(prefix=f"claudex-native-{target}-") as td:
    temp = Path(td)
    home = temp / "home"
    bindir = home / ".local" / "bin"
    bindir.mkdir(parents=True)
    cfg, state, data = temp / "config", temp / "state", temp / "data"
    cfg.mkdir()
    (cfg / "native-siwc-enabled").touch()
    helper = temp / "fake-siwc.mjs"
    helper.write_text("""#!/usr/bin/env node
if (process.argv[2] === "token") {
  console.log(JSON.stringify({access_token:"SYNTHETIC_ONLY",expires_at:Date.now()+3600000}));
} else if (process.argv[2] === "logout") {
  console.log(JSON.stringify({status:"disconnected"}));
} else process.exit(1);
""")
    claude = bindir / "claude"
    claude.write_text(r"""#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == "--version" ]]; then echo "2.1.294 (synthetic Claude)"; exit 0; fi
touch "$CLAUDEX_TEST_STARTED"
for ((i=0; i<160; i++)); do
  [[ -f "$CLAUDEX_TEST_RELEASE" ]] && break
  sleep .08
done
[[ -f "$CLAUDEX_TEST_RELEASE" ]]
code="$(curl --max-time 4 -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $ANTHROPIC_AUTH_TOKEN" "$ANTHROPIC_BASE_URL/v1/models")"
[[ "$code" == 200 ]]
echo SYNTHETIC_CLIENT_CONNECTED=PASS
""")
    claude.chmod(0o700)
    gateway_port, transport_port = port(), port()
    while gateway_port == transport_port:
        transport_port = port()
    env = dict(os.environ, HOME=str(home),
      PATH=str(bindir)+os.pathsep+os.environ.get("PATH", ""),
      CLAUDEX_CONFIG_HOME=str(cfg), CLAUDEX_STATE_HOME=str(state),
      CLAUDEX_DATA_HOME=str(data), CLAUDEX_SHUNT_BIN=str(shunt),
      CLAUDEX_TRANSPORT_BIN=str(transport), CLAUDEX_SIWC_HELPER=str(helper),
      CLAUDEX_PORT=str(gateway_port), CLAUDEX_TRANSPORT_PORT=str(transport_port),
      CLAUDEX_AUTH_MODE="siwc", HTTP_PROXY="http://127.0.0.1:1",
      HTTPS_PROXY="http://127.0.0.1:1", ALL_PROXY="http://127.0.0.1:1",
      NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
    processes, releases, logs = [], [], []
    def launch(name, released=False):
        started = temp / (name + ".started")
        release = temp / (name + ".release")
        if released:
            release.touch()
        f = (temp / (name + ".log")).open("w+")
        process = subprocess.Popen([str(app), "luna", "--", "-p", "synthetic"],
              env={**env, "CLAUDEX_TEST_STARTED": str(started),
                   "CLAUDEX_TEST_RELEASE": str(release)},
              cwd=root, stdout=f, stderr=subprocess.STDOUT)
        processes.append(process)
        releases.append(release)
        logs.append(f)
        wait(lambda: started.exists() or process.poll() is not None, name+" startup")
        if not started.exists():
            f.seek(0)
            raise AssertionError(f"{name} launch failed: {f.read()[-1000:]}")
        return process, release
    try:
        version = run(app, env, "--version").stdout
        assert "2.1.294" in version and not state.exists()
        print("T3_VERSION_COMPAT=PASS")
        updater = run(app, env, "update", success=False)
        assert "disabled in the 0.6 preview" in updater.stderr
        assert not state.exists() or not (state / "private" / "client-token").exists()
        print("UNPINNED_UPDATE_REQUIRES_EXPLICIT_OPT_IN=PASS")
        # Simulate a SIGKILL/crash that left both otherwise-valid bearer files
        # on disk but no surviving runtime. New sessions must not reuse them.
        private = state / "private"
        private.mkdir(parents=True)
        orphan_client, orphan_transport = "ab" * 32, "cd" * 32
        for name, value in (("client-token", orphan_client),
                            ("transport-token", orphan_transport)):
            stale = private / name
            stale.write_text(value)
            stale.chmod(0o600)
        first, first_release = launch("first")
        second, second_release = launch("second")
        token_file = state / "private" / "client-token"
        assert len(list((state / "sessions").glob("*"))) == 2
        token = token_file.read_text().strip()
        assert token != orphan_client
        assert (private / "transport-token").read_text().strip() != orphan_transport
        print("CRASH_ORPHANED_BEARERS_ROTATED=PASS")
        assert status(gateway_port, token) == 200
        assert status(gateway_port) == 401
        print("TWO_SESSIONS_AUTHENTICATED=PASS")
        run(app, env, "stop", success=False)
        run(app, env, "uninstall", success=False)
        first_release.touch()
        assert first.wait(timeout=20) == 0
        assert token_file.is_file() and status(gateway_port, token) == 200
        print("FIRST_EXIT_PRESERVES_SECOND=PASS")
        second_release.touch()
        assert second.wait(timeout=20) == 0
        wait(lambda: not token_file.exists(), "ephemeral token cleanup")
        wait(lambda: status(gateway_port, token) == 0, "ephemeral proxy shutdown")
        print("FINAL_EXIT_REVOKES_TOKENS=PASS")
        # Persistent launches must independently revoke orphaned credentials.
        for name, value in (("client-token", orphan_client),
                            ("transport-token", orphan_transport)):
            stale = private / name
            stale.write_text(value)
            stale.chmod(0o600)
        run(app, env, "start")
        assert token_file.read_text().strip() != orphan_client
        assert (private / "transport-token").read_text().strip() != orphan_transport
        print("CRASH_PERSISTENT_RESTART_ROTATES=PASS")
        assert (state / "persistent-runtime").is_file()
        third, _ = launch("persistent", released=True)
        assert third.wait(timeout=20) == 0
        assert token_file.exists()
        # An unexpected disappearance of a PID file must not make stop()
        # falsely revoke local credentials while transport is still serving.
        transport_pid_path = state / "transport.pid"
        withheld_pid_path = state / "transport.pid.synthetic-withheld"
        assert transport_pid_path.is_file()
        transport_pid_path.rename(withheld_pid_path)
        try:
            run(app, env, "stop", success=False)
            assert token_file.is_file()
            with urllib.request.urlopen(
                f"http://127.0.0.1:{transport_port}/readyz", timeout=3
            ) as alive:
                assert alive.status == 200
        finally:
            if withheld_pid_path.is_file():
                withheld_pid_path.rename(transport_pid_path)
        print("MISSING_PID_RETAINS_TOKENS_UNTIL_STOPPED=PASS")
        run(app, env, "stop")
        assert not token_file.exists()
        print(f"NATIVE_LAUNCHER_SMOKE=PASS target={target} model_requests=0")
    finally:
        for release in releases:
            release.touch()
        for p in processes:
            try:
                p.wait(timeout=4)
            except subprocess.TimeoutExpired:
                p.terminate()
                try: p.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(timeout=3)
        try:
            run(app, env, "stop")
        except Exception:
            pass
        for f in logs:
            f.close()

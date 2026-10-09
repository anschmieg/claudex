#!/usr/bin/env python3
"""Fresh user installation, setup, authenticated runtime and safe uninstall.

Native macOS/Linux ARM64/x86-64 synthetic test. No real SIWC authorization or
GPT inference, and no operations on the user's installed Claudex.
"""
import os
import platform
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = {
    ("Darwin", "arm64"): "darwin-arm64",
    ("Darwin", "x86_64"): "darwin-x86_64",
    ("Linux", "aarch64"): "linux-arm64",
    ("Linux", "arm64"): "linux-arm64",
    ("Linux", "x86_64"): "linux-x86_64",
}.get((platform.system(), platform.machine().lower()))
if not TARGET:
    raise SystemExit("Unsupported native platform for fresh-user regression")
for exe in ("shunt", "claudex-transport"):
    path = ROOT / "bin" / TARGET / exe
    if not path.is_file() or not os.access(path, os.X_OK):
        raise SystemExit(f"Native build missing: {path}")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def request(port, route, token=None):
    headers = {} if token is None else {"Authorization": "Bearer " + token}
    req = urllib.request.Request(f"http://127.0.0.1:{port}{route}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except urllib.error.URLError:
        return 0


def invoke(args, env, expected=0, timeout=25):
    p = subprocess.run(args, env=env, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    if (p.returncode == 0) != (expected == 0):
        raise AssertionError(f"Unexpected exit {p.returncode} for {args}: {p.stderr[-1200:]}")
    if expected != 0 and p.returncode != expected:
        raise AssertionError(f"Unexpected error code {p.returncode} for {args}: {p.stderr[-1200:]}")
    return p


with tempfile.TemporaryDirectory(prefix="claudex-fresh-user-") as folder:
    work = Path(folder)
    home = work / "home"
    fake_bin = home / ".local" / "bin"
    fake_bin.mkdir(parents=True)
    config = work / "config"
    state = work / "state"
    data = work / "package-files"
    binroot = work / "command-bin"
    app = binroot / "claudex"
    fake_claude = fake_bin / "claude"
    fake_claude.write_text("""#!/usr/bin/env python3
import sys
if sys.argv[1:] == ["--version"]:
    print("2.1.294 (synthetic Claude Code)")
else:
    raise SystemExit(3)
""")
    fake_claude.chmod(0o700)
    saved_siwc_dir = work / "preexisting-siwc"
    saved_siwc_dir.mkdir()
    saved_profile = saved_siwc_dir / "chatgpt-auth.json"
    saved_profile.write_text("SYNTHETIC_ENCRYPTED_PROFILE_REUSE_FIXTURE")
    saved_profile.chmod(0o600)
    # Linux CI may not have libsecret-tools; this dummy only confirms the
    # installer checks for its presence. No helper ever invokes this shim.
    if platform.system() == "Linux":
        tool = fake_bin / "secret-tool"
        tool.write_text("#!/bin/sh\nexit 99\n")
        tool.chmod(0o700)
    fake_siwc = work / "fake-siwc.mjs"
    fake_siwc.write_text("""#!/usr/bin/env node
if (process.argv[2] === "token") {
  console.log(JSON.stringify({
    access_token: "SYNTHETIC_ONLY_NOT_AN_OAUTH_TOKEN",
    expires_at: Date.now() + 3600000
  }));
} else if (process.argv[2] === "status") {
  console.log(JSON.stringify({status:"connected"}));
} else {
  process.exit(1);
}
""")
    port1 = free_port()
    port2 = free_port()
    while port1 == port2:
        port2 = free_port()
    env = dict(
        os.environ,
        HOME=str(home),
        PATH=str(fake_bin) + os.pathsep + os.environ.get("PATH", ""),
        CLAUDEX_BIN_HOME=str(binroot),
        CLAUDEX_DATA_HOME=str(data),
        CLAUDEX_CONFIG_HOME=str(config),
        CLAUDEX_STATE_HOME=str(state),
        CLAUDEX_PORT=str(port1),
        CLAUDEX_TRANSPORT_PORT=str(port2),
        CLAUDEX_SIWC_HELPER=str(fake_siwc),
        CLAUDEX_SIWC_DIR=str(saved_siwc_dir),
        CLAUDEX_AUTH_MODE="siwc",
        HTTP_PROXY="http://127.0.0.1:1",
        HTTPS_PROXY="http://127.0.0.1:1",
        ALL_PROXY="http://127.0.0.1:1",
        NO_PROXY="127.0.0.1,localhost",
        no_proxy="127.0.0.1,localhost",
    )

    assert request(port1, "/v1/models") == 0
    assert request(port2, "/healthz") == 0
    config.mkdir(parents=True)
    services_started = False

    try:
        invoke(["bash", str(ROOT / "install.sh"), "--no-setup"], env)
        assert app.is_file() and os.access(app, os.X_OK)
        marker = config / "native-siwc-enabled"
        assert marker.is_file() and not marker.is_symlink()
        assert marker.stat().st_mode & 0o077 == 0
        assert saved_profile.read_text() == "SYNTHETIC_ENCRYPTED_PROFILE_REUSE_FIXTURE"
        print("NATIVE_EXISTING_SIWC_PROFILE_RESELECTED=PASS")
        assert (data / "launcher").is_file()
        assert (data / "shunt").is_file() and (data / "claudex-transport").is_file()
        assert "0.6.0-dev" in invoke([str(app), "version"], env).stdout
        assert "2.1.294" in invoke([str(app), "--version"], env).stdout
        print(f"NATIVE_FRESH_INSTALL=PASS target={TARGET}")

        invoke([str(app), "setup"], env)
        assert (config / "shunt.toml").is_file()
        assert (config / "claude-settings-sol.json").is_file()
        assert (home / ".claude" / "agents" / "gpt-core.md").is_file()
        print("NATIVE_FRESH_SIWC_ONLY_SETUP=PASS")

        invoke([str(app), "start"], env)
        services_started = True
        token = (state / "private" / "client-token").read_text().strip()
        assert len(token) == 64
        assert request(port1, "/v1/models", token) == 200
        assert request(port1, "/v1/models") == 401
        assert request(port1, "/v1/models", "a" * 64) == 401
        assert request(port2, "/healthz") == 200
        doctor = subprocess.run([str(app), "doctor"], env=env, cwd=ROOT,
                                capture_output=True, text=True, timeout=25)
        if doctor.returncode != 0:
            raise AssertionError(
                "Native doctor returned an error (full synthetic diagnostic):\n"
                + doctor.stdout[-2500:] + doctor.stderr[-800:])
        assert "0.6.0-dev" in doctor.stdout
        print("NATIVE_FRESH_AUTH_AND_DOCTOR=PASS")

        # No installer may replace images of a live managed runtime.
        invoke(["bash", str(ROOT / "install.sh"), "--no-setup"], env, expected=3)
        assert request(port1, "/v1/models", token) == 200
        print("NATIVE_INSTALL_REFUSES_RUNNING_SERVICES=PASS")

        invoke([str(app), "stop"], env)
        services_started = False
        assert not (state / "private" / "client-token").exists()
        assert not (state / "private" / "transport-token").exists()
        assert request(port1, "/v1/models") == 0
        assert request(port2, "/healthz") == 0

        # Users may store unrelated files and customize generated agents.
        note = data / "USER_NOTES.txt"
        note.write_text("USER_OWNED_DO_NOT_REMOVE")
        encrypted_profile = config / "chatgpt" / "chatgpt-auth.json"
        encrypted_profile.parent.mkdir(parents=True)
        encrypted_profile.write_text("SYNTHETIC_ENCRYPTED_PROFILE_ONLY")
        customized = home / ".claude" / "agents" / "gpt-core.md"
        customized.write_text(customized.read_text() + "\nUSER_EDIT_KEEP\n")
        invoke([str(app), "uninstall"], env)
        assert not app.exists()
        assert note.read_text() == "USER_OWNED_DO_NOT_REMOVE"
        assert encrypted_profile.read_text() == "SYNTHETIC_ENCRYPTED_PROFILE_ONLY"
        assert "USER_EDIT_KEEP" in customized.read_text()
        assert not (home / ".claude" / "agents" / "gpt-expert.md").exists()
        print("NATIVE_FRESH_UNINSTALL_PRESERVATION=PASS")
        # Refuse an installation whose native preference marker is a symlink;
        # no installed package file may be touched in the rejected target.
        unsafe_cfg = work / "unsafe-cfg"
        unsafe_cfg.mkdir()
        innocent = work / "preserve-me.txt"
        innocent.write_text("KEEP_ME_UNCHANGED")
        (unsafe_cfg / "native-siwc-enabled").symlink_to(innocent)
        unsafe_data = work / "unsafe-data"
        denied = dict(env, CLAUDEX_CONFIG_HOME=str(unsafe_cfg),
                      CLAUDEX_DATA_HOME=str(unsafe_data),
                      CLAUDEX_BIN_HOME=str(work / "unsafe-bin"),
                      CLAUDEX_STATE_HOME=str(work / "unsafe-state"))
        invoke(["bash", str(ROOT / "install.sh"), "--no-setup"], denied, expected=5)
        assert innocent.read_text() == "KEEP_ME_UNCHANGED"
        assert not unsafe_data.exists()
        print("NATIVE_SYMLINK_PREFERENCE_INSTALL_REFUSED=PASS")
        unsafe_package_dir = work / "unsafe-package-dir"
        unsafe_package_dir.mkdir()
        protected_file = work / "owner-managed-script.txt"
        protected_file.write_text("UNRELATED_OWNER_DATA")
        (unsafe_package_dir / "launcher").symlink_to(protected_file)
        blocked = dict(env, CLAUDEX_CONFIG_HOME=str(config),
                       CLAUDEX_DATA_HOME=str(unsafe_package_dir),
                       CLAUDEX_BIN_HOME=str(work / "package-unsafe-bin"),
                       CLAUDEX_STATE_HOME=str(work / "package-unsafe-state"))
        invoke(["bash", str(ROOT / "install.sh"), "--no-setup"], blocked, expected=5)
        assert protected_file.read_text() == "UNRELATED_OWNER_DATA"
        assert not (work / "package-unsafe-bin").exists()
        print("NATIVE_SYMLINK_MANAGED_FILE_REFUSED=PASS")
        print(f"NATIVE_INSTALL_E2E=PASS target={TARGET} model_requests=0")
    finally:
        if services_started and app.is_file():
            try:
                invoke([str(app), "stop"], env, timeout=10)
            except Exception:
                print("WARNING: test-owned services need manual inspection", flush=True)

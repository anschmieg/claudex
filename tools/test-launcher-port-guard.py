#!/usr/bin/env python3
"""Build-free, synthetic regression for untracked localhost listeners."""
import os
import socket
import subprocess
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parent.parent
app = root / "claudex"
with tempfile.TemporaryDirectory(prefix="claudex-fast-guard-") as scratch:
    temp = Path(scratch)
    home = temp / "home"
    bindir = home / ".local" / "bin"
    bindir.mkdir(parents=True)
    fake = bindir / "claude"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o700)
    shunt = temp / "shunt"
    transport = temp / "transport"
    for binary in (shunt, transport):
        binary.write_text("#!/bin/sh\nexit 0\n")
        binary.chmod(0o700)
    config = temp / "config"
    config.mkdir()
    (config / "native-siwc-enabled").touch()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(2)
        port = listener.getsockname()[1]
        # Exercise the transport-port path independently of the gateway port.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as spare:
            spare.bind(("127.0.0.1", 0))
            gateway_port = spare.getsockname()[1]
        env = {**os.environ,
               "HOME": str(home),
               "PATH": str(bindir) + os.pathsep + os.environ.get("PATH", ""),
               "CLAUDEX_CONFIG_HOME": str(config),
               "CLAUDEX_STATE_HOME": str(temp / "state"),
               "CLAUDEX_DATA_HOME": str(temp / "data"),
               "CLAUDEX_SHUNT_BIN": str(shunt),
               "CLAUDEX_TRANSPORT_BIN": str(transport),
               "CLAUDEX_PORT": str(gateway_port),
               "CLAUDEX_TRANSPORT_PORT": str(port),
               "CLAUDEX_AUTH_MODE": "siwc"}
        for command in ("setup", "start"):
            result = subprocess.run([str(app), command], env=env, cwd=root,
                                    capture_output=True, text=True, timeout=12)
            assert result.returncode != 0, (command, result.stdout, result.stderr)
            assert "listener" in result.stderr.lower() or "port" in result.stderr.lower(), result.stderr
            private = temp / "state" / "private"
            assert not (private / "client-token").exists()
            assert not (private / "transport-token").exists()
            print(f"FAST_UNTRACKED_LISTENER_{command.upper()}=PASS")
        # A stale/reused PID must not override the live TCP occupancy veto.
        state = temp / "state"
        state.mkdir(exist_ok=True)
        (state / "transport.pid").write_text(str(os.getpid()))
        result = subprocess.run([str(app), "setup"], env=env, cwd=root,
                                capture_output=True, text=True, timeout=12)
        assert result.returncode != 0, (result.stdout, result.stderr)
        assert ("port" in result.stderr.lower() or
                "active claudex runtime has missing or invalid tokens" in result.stderr.lower()), result.stderr
        assert not (state / "private" / "client-token").exists()
        print("FAST_STALE_PID_OCCUPIED_PORT_SETUP=PASS")
        # Even if the next invocation uses unrelated ports, the listener
        # associated with a previous runtime remains a credential veto.
        (state / "transport.pid").unlink()
        (state / "private").mkdir(exist_ok=True)
        (state / "private" / "runtime-ports").write_text(f"{gateway_port} {port}\n")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as spare:
            spare.bind(("127.0.0.1", 0))
            new_port = spare.getsockname()[1]
        switched = {**env, "CLAUDEX_TRANSPORT_PORT": str(new_port)}
        result = subprocess.run([str(app), "setup"], env=switched,
                                cwd=root, capture_output=True, text=True, timeout=12)
        assert result.returncode != 0, (result.stdout, result.stderr)
        assert "port" in result.stderr.lower(), result.stderr
        print("FAST_PREVIOUS_PORT_PROVENANCE=PASS")

        # A previously tracked but temporarily non-listening daemon must not
        # lose its port provenance, even if a later invocation changes ports.
        # These ports are bound only long enough to choose distinct free ports;
        # no model server is started and no real credentials are accessed.
        reserved = []
        for _ in range(4):
            reserved_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            reserved_socket.bind(("127.0.0.1", 0))
            reserved.append(reserved_socket)
        previous_gateway, previous_transport, next_gateway, next_transport = (
            sock.getsockname()[1] for sock in reserved
        )
        for sock in reserved:
            sock.close()
        private = state / "private"
        recorded = private / "runtime-ports"
        old_record = f"{previous_gateway} {previous_transport}\n"
        recorded.write_text(old_record)
        client_token = private / "client-token"
        transport_token = private / "transport-token"
        old_client, old_transport = "ab" * 32, "cd" * 32
        client_token.write_text(old_client)
        transport_token.write_text(old_transport)
        client_token.chmod(0o600)
        transport_token.chmod(0o600)
        pid_record = state / "transport.pid"
        pid_record.write_text(str(os.getpid()))
        new_env = {**env, "CLAUDEX_PORT": str(next_gateway),
                   "CLAUDEX_TRANSPORT_PORT": str(next_transport)}
        for tracked in (True, False):
            if not tracked:
                pid_record.unlink()
            for action in ("setup", "start", "stop"):
                denied = subprocess.run(
                    [str(app), action], env=new_env, cwd=root,
                    capture_output=True, text=True, timeout=12
                )
                assert denied.returncode != 0, (tracked, action, denied.stderr)
                assert "port" in denied.stderr.lower() or "credential" in denied.stderr.lower(), denied.stderr
                assert recorded.read_text() == old_record
                assert client_token.read_text() == old_client
                assert transport_token.read_text() == old_transport
            print(f"FAST_SILENT_OLD_DAEMON_TRACKED_{tracked}=PASS")

        # Missing/corrupt provenance is never silently overwritten.
        recorded.write_text("invalid previous port record\n")
        corrupt = subprocess.run([str(app), "setup"], env=new_env, cwd=root,
                                 capture_output=True, text=True, timeout=12)
        assert corrupt.returncode != 0
        assert recorded.read_text() == "invalid previous port record\n"
        assert client_token.read_text() == old_client
        print("FAST_CORRUPT_PROVENANCE_BLOCKED=PASS")

        # Changing ports is permitted only after a clean credential/PID
        # teardown, and creates fresh bearer files under the new record.
        recorded.write_text(old_record)
        client_token.unlink()
        transport_token.unlink()
        migrated = subprocess.run([str(app), "setup"], env=new_env, cwd=root,
                                  capture_output=True, text=True, timeout=12)
        assert migrated.returncode == 0, migrated.stderr
        assert recorded.read_text() == f"{next_gateway} {next_transport}\n"
        assert len(client_token.read_text().strip()) == 64
        assert len(transport_token.read_text().strip()) == 64
        print("FAST_CLEAN_PORT_MIGRATION=PASS")

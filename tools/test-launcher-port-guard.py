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

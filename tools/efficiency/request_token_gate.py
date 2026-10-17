#!/usr/bin/env python3
"""Real Claude Code -> patched Shunt -> fake Responses token regression gate.

No provider inference. Scores first downstream request with o200k_base
(estimated input tokens, not an invoice); protects user/tool semantics.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_ESTIMATED_TOKENS = 19000
MIN_SAVINGS = 100
TOKEN = "qa-synthetic-client"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def capture(shunt, claude, rules, mode, home):
    upstream_port, gateway_port = free_port(), free_port()
    received, ready = [], threading.Event()

    class FakeBackend(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", "0"))
            if n > 3_000_000:
                self.send_error(413)
                return
            data = json.loads(self.rfile.read(n))
            if self.path.startswith("/v1/responses"):
                received.append(data)
            body = b'{"error":{"type":"invalid_request_error","message":"SYNTHETIC_ONLY"}}'
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            if self.path.startswith("/v1/responses"):
                ready.set()

        def log_message(self, *_args):
            pass

    config = home / "test-shunt.toml"
    config.write_text(
        f'[server]\nbind = "127.0.0.1:{gateway_port}"\n'
        'default_provider = "claudex-codex"\n'
        '[server.auth]\ntokens_env = "SHUNT_CLIENT_TOKENS"\n'
        '[providers.claudex-codex]\nkind = "responses"\n'
        f'base_url = "http://127.0.0.1:{upstream_port}/v1"\n'
        'auth = "api_key"\napi_key_env = "CLAUDEX_TRANSPORT_TOKEN"\n'
        'tool_search = false\nrequest_compression = false\n'
        'websocket = false\ncount_tokens = "tiktoken"\n'
        '[[routes]]\nmodel = "gpt-6.1-sol[1m]"\n'
        'provider = "claudex-codex"\nupstream_model = "gpt-6.1-sol"\n')
    settings = home / "settings.json"
    settings.write_text(json.dumps({
        "env": {"ANTHROPIC_BASE_URL": f"http://127.0.0.1:{gateway_port}",
                "ANTHROPIC_AUTH_TOKEN": TOKEN},
        "disableAllHooks": True, "idleCompaction": False,
    }))
    env = dict(os.environ)
    env.pop("CLAUDE_CODE_AUTO_COMPACT_WINDOW", None)
    env.update(SHUNT_CLIENT_TOKENS="qa:" + TOKEN,
               CLAUDEX_TRANSPORT_TOKEN="qa-synthetic-upstream",
               CLAUDEX_PROMPT_MODE=mode,
               CLAUDEX_PROMPT_RULES_DIR=str(rules),
               RUST_LOG="error", HOME=str(home),
               CLAUDE_CONFIG_DIR=str(home / "config"), TMPDIR=str(home),
               ANTHROPIC_BASE_URL=f"http://127.0.0.1:{gateway_port}",
               ANTHROPIC_AUTH_TOKEN=TOKEN, ANTHROPIC_API_KEY=TOKEN,
               CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
               DISABLE_TELEMETRY="1", DISABLE_ERROR_REPORTING="1",
               CI="1", TERM="dumb")
    with ThreadingHTTPServer(("127.0.0.1", upstream_port), FakeBackend) as server:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        shunt_log = home / "shunt-test.stderr"
        with shunt_log.open("wb") as error_stream:
            gateway = subprocess.Popen([str(shunt), "run", "--config", str(config)],
                                       cwd=home, env=env, stdout=subprocess.DEVNULL,
                                       stderr=error_stream)
        client = None
        try:
            for _ in range(120):
                if gateway.poll() is not None:
                    raise RuntimeError("synthetic Shunt exited before ready: "
                                       + shunt_log.read_text(errors="replace")[-600:])
                try:
                    with socket.create_connection(("127.0.0.1", gateway_port),
                                                  timeout=.4):
                        break
                except OSError:
                    time.sleep(.1)
            else:
                raise RuntimeError("synthetic Shunt did not start: "
                                   + shunt_log.read_text(errors="replace")[-600:])
            client = subprocess.Popen(
                [str(claude), "--settings", str(settings), "--model",
                 "gpt-6.1-sol[1m]", "-p", "Synthetic coding tool probe only.",
                 "--output-format", "stream-json", "--verbose",
                 "--no-session-persistence", "--strict-mcp-config"],
                cwd=home, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if not ready.wait(25):
                raise RuntimeError("Claude Code never reached synthetic backend")
        finally:
            for process in (client, gateway):
                if process is not None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
            server.shutdown()
    return received[0]


def invariant_fields(packet):
    value = copy.deepcopy(packet)
    value.pop("instructions", None)
    # Cache identities are session-specific, not user content or tool semantics.
    value.pop("prompt_cache_key", None)
    for tool in value.get("tools", []):
        tool.pop("description", None)
    return value


def check_rule_equivalence(off, selective):
    """Enforce only exact reviewed prompt-rule changes, never arbitrary removal."""
    import importlib.util
    source = Path(__file__).resolve().parents[1] / "test-prompt-rules.py"
    spec = importlib.util.spec_from_file_location("claudex_prompt_rules_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    expected, applied = module.transform(off, "selective")
    if expected.get("instructions") != selective.get("instructions"):
        raise AssertionError("unexpected change to system instructions")
    left = [t.get("description") for t in expected.get("tools", [])]
    right = [t.get("description") for t in selective.get("tools", [])]
    if left != right:
        raise AssertionError("unexpected change to tool descriptions")
    if not applied:
        raise AssertionError("no audited prompt rules applied")


def check_requests(off, selective, encoder):
    if off.get("model") != "gpt-6.1-sol":
        raise AssertionError("unexpected backend model route")
    if len(off.get("tools", [])) < 18:
        raise AssertionError("synthetic harness omitted required coding tools")
    if invariant_fields(off) != invariant_fields(selective):
        raise AssertionError("prompt optimization changed a user message or tool schema")
    def count(value):
        serialized = json.dumps(value, separators=(",", ":"), sort_keys=True,
                                ensure_ascii=False)
        return len(encoder.encode(serialized))
    baseline, optimized = count(off), count(selective)
    if max(baseline, optimized) > MAX_ESTIMATED_TOKENS:
        raise AssertionError(f"request exceeds absolute token budget: {baseline}/{optimized}")
    if baseline - optimized < MIN_SAVINGS:
        raise AssertionError(f"token regression: {baseline} -> {optimized}")
    return {"baseline_estimated_tokens": baseline,
            "selective_estimated_tokens": optimized,
            "estimated_savings": baseline - optimized,
            "absolute_budget": MAX_ESTIMATED_TOKENS,
            "tools": len(off.get("tools", [])),
            "tokenizer": "o200k_base",
            "note": "Synthetic first-request input estimate; not actual provider cost."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shunt", required=True, type=Path)
    parser.add_argument("--claude", required=True, type=Path)
    parser.add_argument("--rules", default="prompt-rules", type=Path)
    args = parser.parse_args()
    for file in (args.shunt, args.claude):
        if not file.is_file() or not os.access(file, os.X_OK):
            parser.error(f"missing executable: {file}")
    import tiktoken
    encoding = tiktoken.get_encoding("o200k_base")
    with tempfile.TemporaryDirectory(prefix="claudex-token-gate-") as temp:
        root = Path(temp)
        off = capture(args.shunt.resolve(), args.claude.resolve(),
                      args.rules.resolve(), "off", root)
        selective = capture(args.shunt.resolve(), args.claude.resolve(),
                            args.rules.resolve(), "selective", root)
    check_rule_equivalence(off, selective)
    print(json.dumps(check_requests(off, selective, encoding), sort_keys=True))


if __name__ == "__main__":
    main()

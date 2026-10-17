#!/usr/bin/env python3
"""Real Claude Code -> patched Shunt -> fake Responses token regression gate.

No provider inference. Scores first downstream request with o200k_base
(estimated input tokens, not an invoice); protects user/tool semantics.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

# The committed golden is deliberately maintained independently of Shunt.
GOLDEN = Path(__file__).resolve().parent / "baselines/claude-2.1.300-shunt.json"
MAX_ESTIMATED_TOKENS = 19000  # Backstop, not the reviewed baseline.
MIN_SAVINGS = 100
TOKEN = "qa-synthetic-client"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def synthetic_protocol_turns(first_request):
    """Fixed Anthropic tool-cycle conversations, independent of model output.

    These are intentionally three request *snapshots* of the same session,
    not an assertion that Claude Code executed the tools. Tool execution and
    real compaction must be checked by separate live-model tests.
    """
    names = ("Bash", "Read", "Edit", "Write")
    by_name = {tool.get("name"): tool for tool in first_request.get("tools", [])}
    if any(name not in by_name for name in names):
        raise AssertionError("cannot replay without essential coding tool schemas")
    tools = [
        {"name": name, "description": by_name[name]["description"],
         "input_schema": by_name[name].get("parameters", {"type": "object"})}
        for name in names
    ]
    user = {"role": "user", "content": [
        {"type": "text", "text": "Synthetic request: inspect QA fixture; no real execution."}
    ]}
    tool_use = {"role": "assistant", "content": [
        {"type": "tool_use", "id": "toolu_qa_1", "name": "Bash",
         "input": {"command": "printf QA_ONLY"}}
    ]}
    tool_result = {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_qa_1",
         "content": "QA_ONLY"}
    ]}
    final = {"role": "assistant", "content": [
        {"type": "text", "text": "The fixture responded. No real files were touched."}
    ]}
    followup = {"role": "user", "content": [
        {"type": "text", "text": "Summarize the fixture outcome and preserve prior context."}
    ]}
    for messages in ([user], [user, tool_use, tool_result],
                     [user, tool_use, tool_result, final, followup]):
        yield {
            "model": "gpt-6.1-sol[1m]", "max_tokens": 128, "stream": True,
            "system": [{"type": "text",
                        "text": "Synthetic deterministic evaluation. Remain read-only."}],
            "messages": messages, "tools": tools,
            "metadata": {"user_id": "claudex-qa-single-session"},
        }


def replay_turns(gateway_port, request, count):
    """Send deterministic Anthropic requests through the *same* Shunt."""
    for fixture in synthetic_protocol_turns(request):
        req = Request(
            f"http://127.0.0.1:{gateway_port}/v1/messages",
            data=json.dumps(fixture).encode(),
            headers={"Content-Type": "application/json",
                     "x-api-key": TOKEN, "Authorization": "Bearer " + TOKEN},
            method="POST",
        )
        try:
            with urlopen(req, timeout=12) as response:
                response.read()
        except HTTPError as exc:
            if exc.code != 400:
                raise RuntimeError(f"Shunt replay error: HTTP {exc.code}") from exc
        count += 1
    return count


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
        "autoCompactWindow": 256000,
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
                 "gpt-6.1-sol[1m]", "--autocompact", "256000", "-p", "Synthetic coding tool probe only.",
                 "--output-format", "stream-json", "--verbose",
                 "--no-session-persistence", "--strict-mcp-config"],
                cwd=home, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if not ready.wait(25):
                raise RuntimeError("Claude Code never reached synthetic backend")
            # Prevent native error retries from contaminating deterministic
            # snapshots; then replay three tool-history-bearing turns.
            client.terminate()
            try:
                client.wait(timeout=3)
            except subprocess.TimeoutExpired:
                client.kill()
                client.wait(timeout=3)
            client = None
            expected = replay_turns(gateway_port, received[0], 1)
            if len(received) != expected:
                raise AssertionError(f"unexpected synthetic request count: "
                                     f"{len(received)} != {expected}")
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
    return received


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


def check_audited_rules(rules_dir, baseline):
    expected = baseline["reviewed_prompt_rule_sha256"]
    actual_files = {path.name: path for path in Path(rules_dir).glob("*.json")}
    if set(actual_files) != set(expected):
        raise AssertionError("reviewed rule file inventory changed")
    for name, reviewed in expected.items():
        if hashlib.sha256(actual_files[name].read_bytes()).hexdigest() != reviewed:
            raise AssertionError(f"audited prompt rules changed: {name}")


def pinned_baseline():
    baseline = json.loads(GOLDEN.read_text())
    if baseline.get("schema_version") != 1 or baseline.get("tokenizer") != "o200k_base":
        raise AssertionError("unrecognized reviewed token baseline")
    return baseline


def capability_fingerprint(tool):
    protected = {key: value for key, value in tool.items() if key != "description"}
    canonical = json.dumps(protected, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def check_pinned_capabilities(packet, baseline):
    """Hard gate against dropping tools even when the request gets cheaper."""
    names = [tool.get("name") or tool.get("type") for tool in packet.get("tools", [])]
    expected = baseline["tool_names"]
    if names != expected:
        raise AssertionError(
            f"tool inventory drift: expected {expected}, got {names}; "
            "review the versioned baseline before changing capabilities"
        )
    by_name = dict(zip(names, packet["tools"]))
    for name, fingerprint in baseline["critical_schema_sha256"].items():
        if capability_fingerprint(by_name[name]) != fingerprint:
            raise AssertionError(f"critical tool schema drift: {name}")


def check_fixed_first_request_budget(report, baseline):
    """Independent budget; comparing to an inflated off mode is insufficient."""
    gates = baseline["first_request"]
    if report["model"] != gates["model"]:
        raise AssertionError("pinned model baseline changed")
    if report["baseline_estimated_tokens"] > gates["max_baseline_tokens"]:
        raise AssertionError("fixed unoptimized token baseline exceeded")
    if report["selective_estimated_tokens"] > gates["max_selective_tokens"]:
        raise AssertionError("fixed optimized token baseline exceeded")
    if report["estimated_savings"] < gates["minimum_savings_tokens"]:
        raise AssertionError("reviewed minimum token saving not met")


def request_tokens(packet, encoder):
    payload = json.dumps(packet, separators=(",", ":"), sort_keys=True,
                         ensure_ascii=False)
    return len(encoder.encode(payload))


def check_multi_turn(off, selective, encoder, baseline):
    """Independent 4-request and within-session cache identity regression."""
    limits = baseline["multi_turn"]
    expected_count = limits["request_count"]
    if len(off) != expected_count or len(selective) != expected_count:
        raise AssertionError("synthetic multi-turn request count changed")
    off_sizes, selective_sizes = [], []
    for trace, sizes in ((off, off_sizes), (selective, selective_sizes)):
        cache_keys = []
        for index, packet in enumerate(trace):
            sizes.append(request_tokens(packet, encoder))
            if index == 0:
                continue
            expected_types = limits["replay_input_types"][index - 1]
            types = [x.get("type") for x in packet.get("input", [])]
            if types != expected_types:
                raise AssertionError(f"synthetic turn {index} lost tool history: {types}")
            input_json = json.dumps(packet.get("input", []), ensure_ascii=False)
            for marker in limits["required_input_markers"][index - 1]:
                if marker not in input_json:
                    raise AssertionError(f"synthetic turn {index} lost required context")
            names = [t.get("name") for t in packet.get("tools", [])]
            if names != limits["replay_tool_names"]:
                raise AssertionError(f"synthetic turn {index} lost tool capabilities")
            if sizes[index] > limits["max_replay_turn_tokens"]:
                raise AssertionError(f"synthetic replay turn {index} exceeds token budget")
            cache_keys.append(packet.get("prompt_cache_key"))
        if not (sizes[1] < sizes[2] < sizes[3]):
            raise AssertionError("synthetic conversation context did not accumulate")
        if limits["require_stable_replay_cache_key"]:
            if not cache_keys[0] or len(set(cache_keys)) != 1:
                raise AssertionError("same-session prompt cache identity changed")
    for i in range(expected_count):
        if invariant_fields(off[i]) != invariant_fields(selective[i]):
            raise AssertionError(f"synthetic turn {i} changed protected request fields")
        if i:
            # No replay-specific rewrite rules are authorized; protect system
            # instructions and tool descriptions too, not just schemas.
            unkeyed_off = copy.deepcopy(off[i])
            unkeyed_on = copy.deepcopy(selective[i])
            unkeyed_off.pop("prompt_cache_key", None)
            unkeyed_on.pop("prompt_cache_key", None)
            if unkeyed_off != unkeyed_on:
                raise AssertionError(f"unreviewed synthetic replay edits on turn {i}")
    totals = sum(off_sizes), sum(selective_sizes)
    if totals[0] > limits["max_cumulative_baseline_tokens"]:
        raise AssertionError("fixed cumulative baseline token budget exceeded")
    if totals[1] > limits["max_cumulative_selective_tokens"]:
        raise AssertionError("fixed cumulative optimized token budget exceeded")
    if totals[0] - totals[1] < limits["minimum_cumulative_savings_tokens"]:
        raise AssertionError("insufficient cumulative token savings")
    return {
        "per_request_off": off_sizes,
        "per_request_selective": selective_sizes,
        "cumulative_baseline_estimated_tokens": totals[0],
        "cumulative_selective_estimated_tokens": totals[1],
        "cumulative_estimated_savings": totals[0] - totals[1],
        "replay_cache_identity_stable": True,
        "request_count": expected_count,
    }


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
    golden = pinned_baseline()
    check_audited_rules(args.rules.resolve(), golden)
    encoding = tiktoken.get_encoding("o200k_base")
    with tempfile.TemporaryDirectory(prefix="claudex-token-gate-") as temp:
        root = Path(temp)
        off = capture(args.shunt.resolve(), args.claude.resolve(),
                      args.rules.resolve(), "off", root)
        selective = capture(args.shunt.resolve(), args.claude.resolve(),
                            args.rules.resolve(), "selective", root)
    if len(off) != 4 or len(selective) != 4:
        raise AssertionError("expected native first request plus three replay turns")
    check_rule_equivalence(off[0], selective[0])
    check_pinned_capabilities(off[0], golden)
    check_pinned_capabilities(selective[0], golden)
    report = check_requests(off[0], selective[0], encoding)
    check_fixed_first_request_budget(report, golden)
    report.update(check_multi_turn(off, selective, encoding, golden))
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()

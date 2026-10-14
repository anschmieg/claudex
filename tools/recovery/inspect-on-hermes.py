#!/usr/bin/env python3
"""Read-only diagnostic of t3 recovery timer and old Claude Code cron metadata.

Run on Hermes via the existing operator's sudo privileges. Never prints
conversation messages, browser grant state, bearer tokens, or cron prompts.
"""
from __future__ import annotations
import json
import os
import pwd
from pathlib import Path
import re
import subprocess

TARGET_USER = os.environ.get("CLAUDEX_TARGET_USER", "t3")
T3_HOME = Path(pwd.getpwnam(TARGET_USER).pw_dir)
RECOVERY = T3_HOME / ".local/state/claudex-recovery"

def systemd_prop(unit: str, properties: str):
    run = subprocess.run(
        ["systemctl", "--machine=" + TARGET_USER + "@.host", "--user", "show", unit,
         "--property=" + properties, "--no-pager"],
        capture_output=True, text=True, timeout=8,
    )
    if run.returncode:
        print("SYSTEMD_CHECK_FAILED", unit, "exit", run.returncode)
        return
    for line in run.stdout.splitlines():
        if line.startswith(("ActiveState=", "UnitFileState=", "Result=", "ExecMainStatus=",
                            "NextElapseUSecRealtime=", "NextElapseUSecMonotonic=", "LastTriggerUSec=")):
            print("SYSTEMD", unit, line)

def cron_results():
    files = [
        p for p in (T3_HOME / ".claude/projects").rglob("*.jsonl")
        if not p.name.startswith("agent-")
    ]
    if not files:
        print("CRON_HISTORY_MISSING")
        return
    records = []
    for path in files:
        invoked = {}
        for line in path.open(errors="replace"):
            try:
                d = json.loads(line)
            except (ValueError, TypeError):
                continue
            msg = d.get("message", {})
            if not isinstance(msg, dict):
                continue
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue
            if d.get("type") == "assistant":
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    if block.get("name") in ("CronList", "CronCreate", "CronDelete"):
                        invoked[block.get("id")] = (d.get("timestamp", ""),
                            block["name"], block.get("input", {}))
            elif d.get("type") == "user":
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_result":
                        continue
                    info = invoked.get(block.get("tool_use_id"))
                    if not info:
                        continue
                    stamp, tool, args = info
                    val = block.get("content", "")
                    if isinstance(val, list):
                        raw = "\n".join(x.get("text", "") for x in val if isinstance(x, dict) and isinstance(x.get("text"), str))
                    else:
                        raw = val if isinstance(val, str) else json.dumps(val)
                    cron = args.get("cron") if isinstance(args, dict) else None
                    if tool == "CronCreate":
                        if cron != "*/5 * * * *":
                            continue
                    # Extract likely ID key/value pairs, never the cron prompt.
                    safe_ids = sorted(set(re.findall(
                        r'(?:jobId|job_id|id)\W{0,8}([a-zA-Z0-9_-]{5,80})',
                        raw, flags=re.IGNORECASE
                    )))
                    specs = ["*/5 * * * *"] if "*/5 * * * *" in raw else []
                    # Only the creation result and latest lists are relevant.
                    # Sanitize raw scheduler replies for inspection; redact
                    # any cron prompt, message text or credential-like strings.
                    safe_raw = re.sub(r'(?i)(["\\\'](?:prompt|message|text|authorization|token|secret)["\\\']\\s*[:=]\\s*)["\\\'][^"\\\']*["\\\']', r'\\1[REDACTED]', raw)
                    safe_raw = re.sub(r'(?i)(?:sk-|bearer\\s+)[a-zA-Z0-9_./=-]{15,}', '[REDACTED]', safe_raw)
                    records.append((stamp, tool, cron, len(raw), safe_ids[:5], specs[:5], safe_raw[:220]))
    print("CRON_RECORDS_MATCHING_FILTERS", len(records))
    for stamp, tool, cron, n, ids, specs, safe_raw in sorted(records)[-8:]:
        print("CRON_RESULT", stamp, tool, "requested_spec", cron,
              "bytes", n, "job_id_candidates", ids, "result_specs", specs,
              "safe_result_excerpt", repr(safe_raw))

def main():
    systemd_prop("claudex-recovery.timer",
                 "ActiveState,UnitFileState,Result,LastTriggerUSec,NextElapseUSecRealtime,NextElapseUSecMonotonic")
    systemd_prop("claudex-recovery.service",
                 "ActiveState,Result,ExecMainStatus")
    systemd_prop("t3code.service", "ActiveState,Result")
    config = RECOVERY / "config.json"
    print("RECOVERY_CONFIG_PRESENT", config.is_file())
    if config.is_file():
        data = json.loads(config.read_text())
        print("RECOVERY_CONFIG_ENABLED", data.get("enabled"),
              "ENROLLED_THREADS", len(data.get("goals", [])))
    ledger = RECOVERY / "ledger.json"
    print("RECOVERY_LEDGER_PRESENT", ledger.is_file())
    if ledger.is_file():
        data = json.loads(ledger.read_text())
        print("RECOVERY_TRACKED_THREADS", len(data.get("threads", {})))
        for item in data.get("threads", {}).values():
            print("RECOVERY_LEDGER_STATUS", "attempts", item.get("attempts", 0),
                  "action", item.get("last_action"), "pending_intent",
                  bool(item.get("intent")))
    cron_results()

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Discover per-model Codex CLI reasoning defaults without hardcoding model levels.

All subprocesses run under the caller's credentials. Only non-secret model
names/defaults are cached; ChatGPT tokens are never read or copied.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import sys
import tempfile
import time

CACHE_TTL_SECONDS = 6 * 3600
STALE_TTL_SECONDS = 7 * 86400
MODEL_LEVELS = {"low", "medium", "high", "xhigh", "max"}
KNOWN_LEVELS = MODEL_LEVELS | {"ultra", "none", "minimal"}
MODEL_SLUG_RE = re.compile(r"^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_-]+\])?$")
LABELS = {"low": "Low", "medium": "Medium", "high": "High", "xhigh": "Extra High", "max": "Max"}


def normalized_model(value: str) -> str:
    if not MODEL_SLUG_RE.fullmatch(value):
        raise ValueError("Invalid model slug")
    return value.split("[", 1)[0]


def parse_model(m: dict) -> tuple[str, dict] | None:
    model = m.get("model") or m.get("id")
    default = m.get("defaultReasoningEffort")
    if not isinstance(model, str) or not MODEL_SLUG_RE.fullmatch(model):
        return None
    if default not in KNOWN_LEVELS:
        return None
    options = [x.get("reasoningEffort") for x in m.get("supportedReasoningEfforts", []) if isinstance(x, dict)]
    supported = [x for x in options if x in KNOWN_LEVELS]
    if default not in supported:
        return None
    return model, {"default": default, "supported": supported, "displayName": m.get("displayName", model)}


def query_codex(executable: str, timeout: float = 8.0) -> dict[str, dict]:
    if not executable:
        return {}
    cmd = [executable, "app-server", "--listen", "stdio://"]
    process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, bufsize=0)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    buffer = b""
    answer: dict[int, dict] = {}
    next_id = 2
    deadline = time.monotonic() + timeout

    def write(data: dict) -> None:
        process.stdin.write((json.dumps(data, separators=(",", ":")) + "\n").encode())
        process.stdin.flush()

    def read_until(wanted_id: int) -> dict:
        nonlocal buffer
        while time.monotonic() < deadline:
            if wanted_id in answer:
                return answer.pop(wanted_id)
            for key, _ in selector.select(timeout=min(0.2, max(0, deadline - time.monotonic()))):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    raise RuntimeError("Codex app-server closed its output")
                buffer += chunk
                if len(buffer) > 8 * 1024 * 1024:
                    raise ValueError("Codex model response exceeded size limit")
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    try:
                        payload = json.loads(line)
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if isinstance(payload, dict) and isinstance(payload.get("id"), int):
                        answer[payload["id"]] = payload
        raise TimeoutError("Timed out waiting for Codex model metadata")

    try:
        write({"id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "claudex-catalog", "version": "0.1.0"}, "capabilities": None}})
        first = read_until(1)
        if first.get("error"):
            return {}
        write({"method": "initialized"})
        catalog: dict[str, dict] = {}
        cursor = None
        for _ in range(4):
            params: dict = {"includeHidden": True, "limit": 100}
            if cursor:
                params["cursor"] = cursor
            write({"id": next_id, "method": "model/list", "params": params})
            response = read_until(next_id)
            next_id += 1
            result = response.get("result") or {}
            if response.get("error") or not isinstance(result, dict):
                return {}
            for raw in result.get("data", []):
                if isinstance(raw, dict):
                    parsed = parse_model(raw)
                    if parsed:
                        catalog[parsed[0]] = parsed[1]
            cursor = result.get("nextCursor")
            if not cursor:
                return catalog
        return {}  # Refuse a truncated model catalog.
    finally:
        selector.close()
        if process.stdin:
            process.stdin.close()
        if process.stdout:
            process.stdout.close()
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)


def from_t3_codex_cache(path: Path) -> dict[str, dict]:
    """Secondary metadata source, generated by T3 Code's Codex app-server driver."""
    try:
        if path.is_symlink() or not path.is_file():
            return {}
        data = json.loads(path.read_text())
        result = {}
        for m in data.get("models", []):
            model = m.get("slug")
            if not isinstance(model, str) or not MODEL_SLUG_RE.fullmatch(model):
                continue
            desc = next((d for d in m.get("capabilities", {}).get("optionDescriptors", [])
                         if d.get("id") == "reasoningEffort"), {})
            options = desc.get("options", [])
            default = next((v.get("id") for v in options if v.get("isDefault")), None) or desc.get("currentValue")
            supported = [v.get("id") for v in options if v.get("id") in KNOWN_LEVELS]
            if default in supported:
                result[model] = {"default": default, "supported": supported, "displayName": m.get("name", model)}
        return result
    except (ValueError, KeyError, OSError, TypeError):
        return {}


def cache_read(path: Path) -> tuple[dict, float]:
    try:
        if path.is_symlink():
            return {}, 0
        data = json.loads(path.read_text())
        if data.get("schema") != 1 or not isinstance(data.get("models"), dict):
            return {}, 0
        return data["models"], float(data.get("fetchedAt", 0))
    except (OSError, ValueError, TypeError):
        return {}, 0


def cache_write(path: Path, models: dict, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("Refusing symlinked Codex catalog cache")
    fd, temp = tempfile.mkstemp(prefix=".codex-model-catalog-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump({"schema": 1, "fetchedAt": time.time(), "source": source,
                       "models": models}, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def catalog(args) -> dict:
    old, last_updated = cache_read(args.cache_file)
    if old and not args.refresh and time.time() - last_updated < CACHE_TTL_SECONDS:
        return old
    live = {}
    try:
        live = query_codex(args.codex_bin, timeout=args.timeout)
    except (OSError, TimeoutError, RuntimeError, ValueError, subprocess.SubprocessError):
        pass
    if live:
        # An old Codex CLI can omit newer models; supplement with T3's
        # Codex-driver cache without replacing the actual CLI's values.
        t3 = from_t3_codex_cache(args.t3_cache)
        for model, info in t3.items():
            live.setdefault(model, info)
        cache_write(args.cache_file, live, "codex-app-server+optional-t3-cache")
        return live
    t3 = from_t3_codex_cache(args.t3_cache)
    if t3:
        cache_write(args.cache_file, t3, "t3-codex-app-server-cache")
        return t3
    return old if time.time() - last_updated < STALE_TTL_SECONDS else {}


def sync_t3(path: Path, models: dict) -> int:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Refusing missing or symlinked T3 settings file")
    data = json.loads(path.read_text())
    provider = data["providerInstances"]["claudex"]
    if provider.get("driver") != "claudeAgent":
        raise ValueError("Unexpected T3 Claudex provider driver")
    entries = provider["config"].get("customModels", [])
    if not isinstance(entries, list):
        raise ValueError("Invalid T3 customModels structure")
    updates = 0
    for i, original in enumerate(entries):
        slug = original.get("slug") if isinstance(original, dict) else original
        if not isinstance(slug, str):
            continue
        info = models.get(normalized_model(slug))
        if not info or info["default"] not in MODEL_LEVELS:
            continue
        choices = [{"id": effort, "label": LABELS[effort],
                    "isDefault": effort == info["default"]}
                   for effort in info["supported"] if effort in MODEL_LEVELS]
        if not choices:
            continue
        effort_option = {"id": "effort", "label": "Reasoning", "type": "select", "options": choices}
        entry = original.copy() if isinstance(original, dict) else {"slug": original, "name": info.get("displayName", slug)}
        caps = dict(entry.get("capabilities", {}))
        desc = list(caps.get("optionDescriptors", []))
        existing = next((i for i,d in enumerate(desc) if d.get("id") == "effort"), None)
        if existing is None:
            desc.insert(0, effort_option)
            if not any(d.get("id") == "fastMode" for d in desc):
                desc.append({"id": "fastMode", "type": "boolean", "label": "Fast Mode"})
        else:
            desc[existing] = effort_option
        caps["optionDescriptors"] = desc
        entry["capabilities"] = caps
        if entry != original:
            entries[i] = entry
            updates += 1
    if not updates:
        return 0
    backup = path.with_name(path.name + ".before-claudex-reasoning-defaults")
    if not backup.exists():
        shutil.copy2(path, backup)
        os.chmod(backup, 0o600)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".t3-codex-defaults-")
    try:
        st = path.stat()
        os.fchmod(fd, st.st_mode & 0o777)
        os.fchown(fd, st.st_uid, st.st_gid)
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return updates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["get", "list", "sync-t3"])
    parser.add_argument("model_or_path", nargs="?")
    parser.add_argument("--codex-bin", default=os.environ.get("CLAUDEX_CODEX_BIN") or shutil.which("codex") or "")
    parser.add_argument("--cache-file", type=Path, default=Path(os.environ.get("CLAUDEX_REASONING_CACHE", str(Path.home()/".config/claudex/codex-model-defaults.json"))))
    parser.add_argument("--t3-cache", type=Path, default=Path.home()/".t3/caches/codex.json")
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    models = catalog(args)
    if args.action == "list":
        for model, data in sorted(models.items()):
            print(f"{model}\t{data['default']}")
        return 0
    if not args.model_or_path:
        parser.error("A model or T3 settings path is required")
    if args.action == "get":
        model = normalized_model(args.model_or_path)
        info = models.get(model)
        if info and info["default"] in MODEL_LEVELS:
            print(info["default"])
            return 0
        return 1
    count = sync_t3(Path(args.model_or_path), models)
    print(f"T3 Claudex Codex reasoning defaults: updated {count} model entries")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, KeyError, PermissionError, OSError) as err:
        print(f"claudex: {err}", file=sys.stderr)
        sys.exit(2)

#!/usr/bin/env python3
"""Offline regression tests for dynamic model metadata and T3 picker defaults."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("claudex_reasoning_defaults", HERE / "codex-reasoning-defaults.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def model(name, default):
    return {"model": name, "id": name, "displayName": name,
            "defaultReasoningEffort": default,
            "supportedReasoningEfforts": [{"reasoningEffort": x} for x in ("low", "medium", "high", "xhigh", "max", "ultra")]}


class CatalogTests(unittest.TestCase):
    def test_live_model_list_not_hardcoded(self):
        with tempfile.TemporaryDirectory() as d:
            server = Path(d) / "mock-codex"
            server.write_text("""#!/usr/bin/env python3
import json,sys
for line in sys.stdin:
  request=json.loads(line)
  if request.get('method')=='initialize':
    print(json.dumps({'id':request['id'],'result':{'userAgent':'synthetic'}}),flush=True)
  if request.get('method')=='model/list':
    entries=[
      {'model':'gpt-synthetic-one','defaultReasoningEffort':'low','displayName':'One',
       'supportedReasoningEfforts':[{'reasoningEffort':'low'},{'reasoningEffort':'high'}]},
      {'model':'gpt-synthetic-two','defaultReasoningEffort':'high','displayName':'Two',
       'supportedReasoningEfforts':[{'reasoningEffort':'medium'},{'reasoningEffort':'high'}]},
    ]
    print(json.dumps({'id':request['id'],'result':{'data':entries,'nextCursor':None}}),flush=True)
""")
            server.chmod(0o755)
            got = module.query_codex(str(server), timeout=4)
            self.assertEqual(got["gpt-synthetic-one"]["default"], "low")
            self.assertEqual(got["gpt-synthetic-two"]["default"], "high")
            self.assertNotIn("gpt-6.1-sol", got)

    def test_normalization_and_reject_invalid_slugs(self):
        self.assertEqual(module.normalized_model("gpt-synthetic-one[1m]"), "gpt-synthetic-one")
        for value in ("-untrusted/path", "gpt model", "../gpt", "gpt[1m];curl"):
            with self.assertRaises(ValueError): module.normalized_model(value)

    def test_t3_cache_uses_default_not_user_current_value(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "codex.json"
            p.write_text(json.dumps({"models": [{"slug": "gpt-synthetic-one", "name": "One",
                "capabilities": {"optionDescriptors": [{"id": "reasoningEffort", "currentValue": "high",
                   "options": [{"id": "low", "isDefault": True}, {"id": "high"}]}]}}]}))
            self.assertEqual(module.from_t3_codex_cache(p)["gpt-synthetic-one"]["default"], "low")

    def test_cached_nonsecret_metadata_and_ttl(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d) / "cache.json"
            catalog={"gpt-synthetic": {"default": "low", "supported": ["low","high"]}}
            module.cache_write(p, catalog, "synthetic")
            self.assertEqual(module.cache_read(p)[0], catalog)
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
            self.assertEqual(json.loads(p.read_text()).get("source"), "synthetic")

    def test_t3_model_picker_default_updates_and_override_retention(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d) / "settings.json"
            p.write_text(json.dumps({"providerInstances": {
                "claudex": {"driver": "claudeAgent", "config": {"binaryPath": "claudex",
                    "customModels": [{"slug": "gpt-synthetic-one[1m]", "name": "One"},
                                     {"slug": "gpt-unknown[1m]", "name": "Unknown"}]}},
                "codex": {"driver": "codex", "config": {"unrelated": True}}},
                "private_unrelated": "preserve_me"}))
            infos={"gpt-synthetic-one": {"default": "low", "supported": ["low","medium","high","ultra"], "displayName": "One"}}
            self.assertEqual(module.sync_t3(p, infos), 1)
            self.assertEqual(module.sync_t3(p, infos), 0)
            x=json.loads(p.read_text())
            desc=x["providerInstances"]["claudex"]["config"]["customModels"][0]["capabilities"]["optionDescriptors"]
            effort=next(x for x in desc if x["id"]=="effort")
            self.assertEqual([opt["id"] for opt in effort["options"]], ["low", "medium", "high"])
            self.assertEqual([opt["id"] for opt in effort["options"] if opt.get("isDefault")], ["low"])
            self.assertEqual(x["private_unrelated"], "preserve_me")
            self.assertEqual(x["providerInstances"]["codex"]["config"]["unrelated"], True)
            self.assertTrue(p.with_name("settings.json.before-claudex-reasoning-defaults").exists())


if __name__ == "__main__": unittest.main(verbosity=2)

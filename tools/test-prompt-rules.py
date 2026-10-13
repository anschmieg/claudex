#!/usr/bin/env python3
"""Deterministic dry run for exact-hash Claudex prompt rules on captured synthetic 2.1.294 data."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
CAPTURE=ROOT/'experiments/prompt-translation-rig/results/outbound-1.json'
RULES=ROOT/'prompt-rules'


def load_rules():
    rules=[]
    for file in sorted(RULES.glob('*.json')):
        data=json.loads(file.read_text())
        assert data['schema_version']==1
        for rule in data['rules']:
            assert all(k in rule for k in ('id','mode','target','match','expected_sha256','replacement'))
            rules.append(rule)
    return rules


def apply_rule(value, rule, model):
    match=rule['match']
    if match['kind']=='exact':
        anchor=match['value']
        if value.count(anchor)!=1:return None
        start=value.index(anchor);end=start+len(anchor)
    elif match['kind']=='section':
        opener,closer=match['start'],match['end']
        if value.count(opener)!=1:return None
        start=value.index(opener)
        rest=value[start+len(opener):]
        if rest.count(closer)!=1:return None
        end=start+len(opener)+rest.index(closer)
    else: raise AssertionError(match['kind'])
    old=value[start:end]
    if hashlib.sha256(old.encode()).hexdigest()!=rule['expected_sha256']:
        return None
    return value[:start]+rule['replacement'].replace('{model}',model)+value[end:]


def transform(packet,mode):
    packet=copy.deepcopy(packet)
    applied=[]
    for rule in load_rules():
        if mode=='selective' and rule['mode']!='selective':continue
        if mode=='off':continue
        if rule['target']=='instructions':
            converted=apply_rule(packet.get('instructions',''),rule,packet['model'])
            if converted is not None:
                packet['instructions']=converted;applied.append(rule['id'])
        else:
            tools=[t for t in packet['tools'] if t.get('name')==rule['tool']]
            if len(tools)!=1:continue
            converted=apply_rule(tools[0]['description'],rule,packet['model'])
            if converted is not None:
                tools[0]['description']=converted;applied.append(rule['id'])
    return packet, applied


def prompt_chars(packet):
    return len(packet.get('instructions',''))+sum(len(t.get('description','')) for t in packet.get('tools',[]))

class PromptRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not CAPTURE.is_file():
            raise unittest.SkipTest('Real synthetic CLI capture not present; raw prompt payloads are not published')
        cls.base=json.loads(CAPTURE.read_text())
    def test_rule_ids_are_unique(self):
        ids=[r['id'] for r in load_rules()]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(len(ids),7)
    def test_off_mode_preserves_full_payload(self):
        unchanged, applied=transform(self.base,'off')
        self.assertEqual(unchanged,self.base)
        self.assertEqual(applied,[])

    def test_selective_exact_match(self):
        shaped,applied=transform(self.base,'selective')
        self.assertEqual(len(applied),4,applied)
        self.assertIn('GPT coding agent',shaped['instructions'])
        self.assertNotIn('The most recent Claude models are',shaped['instructions'])
        self.assertIn('permission mode',shaped['instructions'])
    def test_aggressive_exact_match(self):
        shaped,applied=transform(self.base,'aggressive')
        self.assertEqual(len(applied),7,applied)
        self.assertLess(prompt_chars(shaped), prompt_chars(self.base))
    def test_all_non_description_tool_properties_unchanged(self):
        for mode in ('selective','aggressive'):
            shaped,_=transform(self.base,mode)
            self.assertEqual({k:v for k,v in self.base.items() if k not in ('instructions','tools')},
                             {k:v for k,v in shaped.items() if k not in ('instructions','tools')})
            self.assertEqual(len(shaped['tools']),len(self.base['tools']))
            for original,new in zip(self.base['tools'],shaped['tools']):
                self.assertEqual({k:v for k,v in original.items() if k!='description'},
                                 {k:v for k,v in new.items() if k!='description'})
    def test_unknown_upstream_change_preserved(self):
        original=copy.deepcopy(self.base)
        original['instructions']=original['instructions'].replace(
            "You are a Claude agent, built on Anthropic's Claude Agent SDK.",
            "This is an unrecognized future upstream agent identity.")
        shaped,applied=transform(original,'selective')
        self.assertNotIn('gpt-agent-identity',applied)
        self.assertIn('This is an unrecognized future upstream agent identity.',shaped['instructions'])
        original=copy.deepcopy(self.base)
        for t in original['tools']:
            if t.get('name')=='Workflow': t['description']+='\nNEW SAFETY RULE: never invent authorizations.'
        # Existing exact section still matches; unrelated upstream addition must survive.
        shaped,applied=transform(original,'aggressive')
        self.assertIn('NEW SAFETY RULE: never invent authorizations.',
                      next(t['description'] for t in shaped['tools'] if t.get('name')=='Workflow'))
    def test_hash_prevents_semantic_fuzzy_changes(self):
        original=copy.deepcopy(self.base)
        for t in original['tools']:
            if t.get('name')=='Workflow':
                t['description']=t['description'].replace('canonical multi-stage pattern','canonical multi-stage protocol')
        shaped,applied=transform(original,'aggressive')
        self.assertNotIn('workflow-shortened-example',applied)
        self.assertIn('canonical multi-stage protocol',next(t['description'] for t in shaped['tools'] if t.get('name')=='Workflow'))

if __name__=='__main__':
    unittest.main(verbosity=2)
    # Python unittest exits; run measurement by importing this module externally.

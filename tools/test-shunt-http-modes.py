#!/usr/bin/env python3
"""Replays a synthetic Claude Code capture through the real Shunt HTTP translator.

No upstream network or inference: the gateway is pinned to a fake loopback
Responses receiver. The test body was captured in a separate credential-free rig.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from urllib import request, error

ROOT=Path(__file__).resolve().parents[1]
CAPTURE=ROOT/'experiments/prompt-translation-rig/results/inbound-1.json'
BASELINE=ROOT/'experiments/prompt-translation-rig/results/outbound-1.json'
OUT=ROOT/'experiments/prompt-translation-rig/results'
RULES=ROOT/'prompt-rules'

def available_port():
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]

class Receiver(BaseHTTPRequestHandler):
    def do_POST(self):
        body=self.rfile.read(int(self.headers.get('content-length','0')))
        try: self.server.captured.append(json.loads(body))
        except json.JSONDecodeError: self.server.captured.append({'parse_error':True})
        message=b'{"error":{"message":"Synthetic fake backend: no model inference","type":"invalid_request_error"}}'
        self.send_response(400)
        self.send_header('content-type','application/json')
        self.send_header('content-length',str(len(message)))
        self.end_headers()
        self.wfile.write(message)
    def log_message(self,*_): pass

def test_mode(binary,mode,source,baseline):
    fake=ThreadingHTTPServer(('127.0.0.1',0),Receiver)
    fake.captured=[]
    thread=threading.Thread(target=fake.serve_forever,daemon=True);thread.start()
    shunt_port=available_port()
    config=(
        '[server]\n'
        f'bind = "127.0.0.1:{shunt_port}"\n'
        'default_provider = "claudex-codex"\n'
        '[server.auth]\n'
        'tokens_env = "SHUNT_CLIENT_TOKENS"\n'
        '[providers.claudex-codex]\n'
        'kind = "responses"\n'
        f'base_url = "http://127.0.0.1:{fake.server_address[1]}/v1"\n'
        'auth = "api_key"\n'
        'api_key_env = "CLAUDEX_TRANSPORT_TOKEN"\n'
        'tool_search = false\n'
        'request_compression = false\n'
        'websocket = false\n'
        'count_tokens = "tiktoken"\n'
        '[[routes]]\n'
        'model = "gpt-6.1-sol"\n'
        'provider = "claudex-codex"\n'
        'upstream_model = "gpt-6.1-sol"\n'
    )
    folder=OUT/('shaped-'+mode)
    folder.mkdir(parents=True,exist_ok=True)
    cfg=folder/'synthetic-shunt.toml'
    cfg.write_text(config)
    env={key:os.environ[key] for key in ('PATH','HOME','TMPDIR') if key in os.environ}
    env.update(SHUNT_CLIENT_TOKENS='rig:synthetic-secret',
               CLAUDEX_TRANSPORT_TOKEN='abcdef0123456789'*4,
               CLAUDEX_PROMPT_MODE=mode,CLAUDEX_PROMPT_RULES_DIR=str(RULES),RUST_LOG='error')
    log=folder/'shunt-stderr.log'
    with log.open('w') as output:
        process=subprocess.Popen([str(binary),'run','--config',str(cfg)],env=env,
            cwd=folder,stdout=output,stderr=subprocess.STDOUT)
        try:
            start=time.monotonic()
            while time.monotonic()-start<12:
                if process.poll() is not None:
                    raise RuntimeError(f'Shunt exited {process.returncode}: {log.read_text()[-550:]}')
                try:
                    with socket.create_connection(('127.0.0.1',shunt_port),timeout=.3):
                        break
                except OSError:
                    time.sleep(.12)
            else: raise RuntimeError('Shunt TCP listener not ready: '+log.read_text()[-600:])
            payload=json.dumps(source).encode()
            req=request.Request(f'http://127.0.0.1:{shunt_port}/v1/messages',data=payload,method='POST',headers={
                'content-type':'application/json','x-api-key':'synthetic-secret',
                'authorization':'Bearer synthetic-secret','anthropic-version':'2023-06-01'})
            try:
                with request.urlopen(req,timeout=10) as resp: resp.read()
            except error.HTTPError as exc: exc.read()
            start=time.monotonic()
            while not fake.captured and time.monotonic()-start<3:time.sleep(.07)
            if not fake.captured:raise AssertionError(f'No outbound Responses request: {log.read_text()[-600:]}')
            actual=fake.captured[0]
            original_tools={t.get('name'):t for t in baseline['tools']}
            actual_tools={t.get('name'):t for t in actual.get('tools',[])}
            assert len(original_tools)==len(actual_tools),(mode,len(original_tools),len(actual_tools))
            for name,tool in original_tools.items():
                assert name in actual_tools,name
                assert {k:v for k,v in tool.items() if k!='description'}=={k:v for k,v in actual_tools[name].items() if k!='description'},name
            assert actual['input']==baseline['input'],'Message content or roles changed'
            spec=importlib.util.spec_from_file_location('rules',ROOT/'tools/test-prompt-rules.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            expected,applied=module.transform(baseline,mode)
            assert actual['instructions']==expected['instructions'],'Shunt instructions differ from expected exact-hash rewrite'
            for name,tool in expected_tools(expected).items():
                assert actual_tools[name].get('description')==tool.get('description'),f'{name} description mismatch'
            (folder/'translated-response.json').write_text(json.dumps(actual,indent=2)+'\n')
            report={'mode':mode,'rules_matched':applied,'matched_count':len(applied),
                    'saved_characters':module.prompt_chars(baseline)-module.prompt_chars(actual),
                    'baseline_characters':module.prompt_chars(baseline),
                    'tool_count':len(actual_tools),'messages_identical':True,'passed':True}
            (folder/'verified-results.json').write_text(json.dumps(report,indent=2)+'\n')
            print('MODE_PASS',mode,json.dumps({k:v for k,v in report.items() if k!='rules_matched'}))
            return report
        finally:
            process.terminate()
            try:process.wait(timeout=4)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=4)
            fake.shutdown();fake.server_close()

def expected_tools(packet):
    return {t.get('name'):t for t in packet['tools']}

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--shunt',type=Path,required=True)
    parser.add_argument('--mode',choices=('off','selective','aggressive'),default='selective')
    opts=parser.parse_args()
    opts.shunt=opts.shunt.resolve()
    if not CAPTURE.is_file() or not BASELINE.is_file():
        parser.error('Synthetic capture files missing; see experiments/prompt-translation-rig README')
    test_mode(opts.shunt,opts.mode,json.loads(CAPTURE.read_text()),json.loads(BASELINE.read_text()))

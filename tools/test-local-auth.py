#!/usr/bin/env python3
"""Cross-platform, zero-inference Claudex local bearer-auth smoke.

Runs only against the local shunt and transport, synthetic offline SIWC token,
and deliberately invalid HTTPS proxy. Not a real account/login test.
"""
from pathlib import Path
import os
import platform
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from urllib.error import HTTPError, URLError

root=Path(__file__).resolve().parent.parent
os_name=platform.system()
arch=platform.machine().lower()
target={
    ("Darwin","arm64"):"darwin-arm64",
    ("Darwin","x86_64"):"darwin-x86_64",
    ("Linux","x86_64"):"linux-x86_64",
    ("Linux","aarch64"):"linux-arm64",
    ("Linux","arm64"):"linux-arm64",
}.get((os_name,arch))
if target is None:
    raise SystemExit(f"Unsupported test platform: {os_name}-{arch}")
shunt=root/"bin"/target/"shunt"
transport=root/"bin"/target/"claudex-transport"
if not shunt.is_file() or not transport.is_file():
    raise SystemExit(f"Native binaries missing for {target}")

def port():
    with socket.socket() as s:
        s.bind(("127.0.0.1",0))
        return s.getsockname()[1]

def request(port_number,path,token=None,method="GET",body=None):
    headers={}
    if token is not None:headers["Authorization"]="Bearer "+token
    if body is not None:headers["Content-Type"]="application/json"
    req=urllib.request.Request(
        f"http://127.0.0.1:{port_number}{path}",
        data=body,headers=headers,method=method)
    try:
        with urllib.request.urlopen(req,timeout=4) as response:
            return response.status
    except HTTPError as error:
        return error.code
    except URLError:
        return 0

client_token=secrets.token_hex(32)
transport_token=secrets.token_hex(32)
p_shunt=port()
p_transport=port()
while p_transport==p_shunt:p_transport=port()

with tempfile.TemporaryDirectory(prefix="claudex-auth-smoke-") as td:
    td=Path(td)
    helper=td/"offline-helper.mjs"
    helper.write_text("""#!/usr/bin/env node
if(process.argv[2]!=='token')process.exit(1);
console.log(JSON.stringify({
access_token:'SYNTHETIC_ONLY_NEVER_BILLED',
expires_at:Date.now()+3600000}));
""")
    helper.chmod(0o700)
    config=td/"shunt.toml"
    config.write_text(f"""[server]
bind = "127.0.0.1:{p_shunt}"
default_provider = "test"
auto_include_builtin_models = false

[server.auth]
tokens_env = "SHUNT_CLIENT_TOKENS"

[providers.test]
kind = "responses"
base_url = "http://127.0.0.1:{p_transport}/v1"
auth = "api_key"
api_key_env = "CLAUDEX_TRANSPORT_TOKEN"
tool_search = false
request_compression = false
websocket = false
count_tokens = "tiktoken"

[[routes]]
model = "gpt-6-luna[1m]"
provider = "test"
upstream_model = "gpt-6-luna"
""")
    env=os.environ.copy()
    env.update({
      "HOME":str(td),
      "CLAUDEX_TRANSPORT_TOKEN":transport_token,
      "SHUNT_CLIENT_TOKENS":"claudex:"+client_token,
      "CLAUDEX_AUTH_MODE":"siwc",
      "CLAUDEX_SIWC_HELPER":str(helper),
      "HTTPS_PROXY":"http://127.0.0.1:1",
      "HTTP_PROXY":"http://127.0.0.1:1",
      "ALL_PROXY":"http://127.0.0.1:1",
    })
    processes=[]
    logs=[]
    try:
        for name,cmd in [
          ("transport",[str(transport),"--listen",f"127.0.0.1:{p_transport}"]),
          ("shunt",[str(shunt),"--config",str(config),"run"]),
        ]:
            fd=(td/(name+".log")).open("wb")
            logs.append(fd)
            processes.append(subprocess.Popen(cmd,env=env,stdout=fd,stderr=subprocess.STDOUT))
        for p,path in ((p_shunt,"/health"),(p_transport,"/readyz")):
            for i in range(150):
                if request(p,path)==200:break
                if any(proc.poll() is not None for proc in processes):
                    raise RuntimeError("Test daemon exited before readiness")
                time.sleep(.05)
            else:
                raise RuntimeError("Test daemon not ready")
        body=b'{"model":"gpt-6-luna[1m]","max_tokens":32,"messages":[{"role":"user","content":"test"}]}'
        tests={
          "shunt_missing":request(p_shunt,"/v1/models")==401,
          "shunt_wrong":request(p_shunt,"/v1/models",token="f"*64)==401,
          "shunt_correct":request(p_shunt,"/v1/models",token=client_token)==200,
          "shunt_messages_missing":request(p_shunt,"/v1/messages",method="POST",body=body)==401,
          "transport_missing":request(p_transport,"/v1/responses",method="POST",body=b"{}")==401,
          "transport_wrong":request(p_transport,"/v1/responses",method="POST",token="f"*64,body=b"{}")==401,
          # All outbound HTTPS is pointed at a deliberately dead local proxy.
          "transport_correct":request(p_transport,"/v1/responses",method="POST",token=transport_token,body=b"{}")==502,
          "shunt_messages_correct":request(p_shunt,"/v1/messages",method="POST",token=client_token,body=body)!=401,
        }
        for key,passed in tests.items():
            print(("PASS" if passed else "FAIL"),key)
        assert all(tests.values()),"A local auth check failed"
    finally:
        for proc in reversed(processes):
            if proc.poll() is None:proc.terminate()
        for proc in reversed(processes):
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill();proc.wait(timeout=5)
        for fd in logs:fd.close()
    print("LOCAL_AUTH_SMOKE=PASS target="+target+" requests_to_models=0")

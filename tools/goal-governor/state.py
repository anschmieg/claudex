#!/usr/bin/env python3
"""Durable goal records. Independent of T3, Claude Code and Claudex internals."""
from __future__ import annotations
import contextlib, datetime as dt, fcntl, hashlib, json, os, stat, tempfile, uuid
import tasks
from pathlib import Path

SCHEMA=1
ROOT=Path(os.environ.get("CLAUDEX_GOAL_HOME",str(Path.home()/".local/state/claudex-governor")))

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")

def timeparse(s):
    try:return dt.datetime.fromisoformat(s.replace("Z","+00:00")) if s else None
    except (ValueError,AttributeError):return None

def uuidcheck(value):
    try:
        if str(uuid.UUID(value))==value:return value
    except (TypeError,ValueError):pass
    raise ValueError("invalid UUID")

def home():
    if ROOT.is_symlink():raise ValueError("symlinked state root")
    ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    if ROOT.stat().st_uid!=os.geteuid():raise ValueError("unexpected state owner")
    os.chmod(ROOT,0o700)
    goals=ROOT/"goals"
    if goals.is_symlink():raise ValueError("symlinked goal directory")
    goals.mkdir(mode=0o700,parents=True,exist_ok=True)
    os.chmod(goals,0o700)
    return goals

def path(thread):
    return home()/(uuidcheck(thread)+".json")

def write(path,obj):
    if path.is_symlink():raise ValueError("symlink state")
    raw=(json.dumps(obj,sort_keys=True,indent=2)+"\n").encode()
    fd,name=tempfile.mkstemp(prefix=".governor-",dir=str(path.parent))
    try:
        with os.fdopen(fd,"wb") as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.chmod(name,0o600)
        os.replace(name,path)
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if os.path.exists(name):os.unlink(name)

def read(p):
    if p.is_symlink() or not p.is_file() or p.stat().st_size>240_000:
        raise ValueError("missing or invalid governor state")
    return json.loads(p.read_text())

@contextlib.contextmanager
def locked():
    home()
    with open(ROOT/"lock","a+") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield

def load(thread):
    obj=read(path(thread))
    if obj.get("version")!=SCHEMA or obj.get("thread_id")!=thread:
        raise ValueError("invalid goal identity")
    return tasks.normalize(obj)

def create(thread,project,workspace,title,acceptance,next_action):
    uuidcheck(thread);uuidcheck(project)
    project_path=Path(workspace).resolve(strict=True)
    if not project_path.is_dir() or len(title.strip())<8 or len(next_action.strip())<20 or not acceptance:
        raise ValueError("concrete goal, workspace, acceptance and next action required")
    if len(acceptance)>24 or any(len(x.strip())<10 for x in acceptance):raise ValueError("invalid acceptance")
    file=path(thread)
    if file.exists() or file.is_symlink():raise ValueError("goal already enrolled")
    obj=dict(version=SCHEMA,thread_id=thread,project_id=project,workspace=str(project_path),
        title=title.strip()[:300],acceptance=[a.strip()[:400] for a in acceptance],
        status="active",auto_enabled=False,revision=0,updated_at=now(),enrolled_at=now(),
        next_action=next_action.strip()[:1800],evidence="User-enrolled initial goal",
        artifact=None,blocked_reason=None,completion_proposal=None)
    tasks.normalize(obj)
    write(file,obj)
    return obj

def artifact_digest(workspace,artifact):
    root=Path(workspace).resolve(strict=True)
    orig=Path(artifact)
    if not orig.is_absolute():orig=root/orig
    if orig.is_symlink():raise ValueError("symlinked evidence")
    final=orig.resolve(strict=True)
    if root not in final.parents:raise ValueError("evidence outside workspace")
    rel=final.relative_to(root)
    if any(part in (".git",".claude","node_modules") or part.startswith(".env") for part in rel.parts):
        raise ValueError("private evidence file")
    if rel.suffix in (".key",".p12",".pem",".env"):raise ValueError("secret material")
    meta=final.stat()
    if not stat.S_ISREG(meta.st_mode) or meta.st_size>3_000_000:
        raise ValueError("evidence size/type")
    return {"path":str(rel),"sha256":hashlib.sha256(final.read_bytes()).hexdigest(),"size":meta.st_size}

def user_message_evidence(db,thread,message_id):
    """Evidence of a real UI-origin user decision, never a tool-created prompt.

    Validating a decision is NOT an authorization for external privileged work.
    """
    from sync import client_messages
    row=db.execute("""SELECT message_id,created_at,text FROM projection_thread_messages
        WHERE thread_id=? AND message_id=? AND role='user' LIMIT 1""",
        (thread,message_id)).fetchone()
    if not row or not row['text'] or len(row['text'].strip())<10:
        raise ValueError('no verifiable user decision')
    events=db.execute("""SELECT payload_json FROM orchestration_events
        WHERE stream_id=? AND event_type='thread.turn-start-requested'
          AND actor_kind='client' ORDER BY occurred_at DESC LIMIT 500""",
        (thread,)).fetchall()
    if not any(isinstance(json.loads(event['payload_json'] or '{}'),dict) and
       json.loads(event['payload_json'] or '{}').get('messageId')==message_id for event in events):
        raise ValueError('user decision not client-origin')
    return dict(kind='user_decision',message_id=message_id,
                sha256=hashlib.sha256(row['text'].encode()).hexdigest())

def evidence_valid(obj,db=None):
    item=obj.get("artifact")
    if item is None:return obj.get("revision")==0
    if item.get('kind')=='user_decision':
        if db is None:return True  # CLI verified at checkpoint creation.
        try:return user_message_evidence(db,obj['thread_id'],item['message_id'])==item
        except (OSError,ValueError,KeyError,TypeError):return False
    try:
        measured=artifact_digest(obj["workspace"],item["path"])
        if item.get('kind')=='test_report':measured['kind']='test_report'
        return measured==item
    except (OSError,ValueError,KeyError):return False

def checkpoint(thread,next_action,evidence,artifact=None,expected_revision=None,
               evidence_kind='artifact',evidence_ref=None,db=None):
    obj=load(thread)
    if obj["status"]!="active":raise ValueError("inactive goal")
    if expected_revision is not None and obj["revision"]!=expected_revision:
        raise ValueError("checkpoint race")
    if len(next_action.strip())<20 or len(evidence.strip())<16:
        raise ValueError("concrete progress and next action required")
    if next_action.strip()==obj["next_action"]:
        raise ValueError("next action did not advance")
    if evidence_kind=='user_decision':
        if db is None or not evidence_ref:raise ValueError('user decision needs T3 verification')
        digest=user_message_evidence(db,obj['thread_id'],evidence_ref)
    elif evidence_kind in ('artifact','test_report'):
        if artifact is None:raise ValueError('evidence file required')
        digest=artifact_digest(obj["workspace"],artifact)
        if evidence_kind=='test_report':digest['kind']='test_report'
    else:raise ValueError('unsupported evidence kind')
    if obj.get("artifact")==digest:
        raise ValueError("evidence unchanged")
    obj.update(revision=obj["revision"]+1,next_action=next_action.strip()[:1800],
        evidence=evidence.strip()[:1500],artifact=digest,updated_at=now(),blocked_reason=None)
    write(path(thread),obj)
    return obj

def state_change(thread,status,reason=""):
    obj=load(thread)
    if status not in ("active","paused","blocked","needs_review"):raise ValueError("invalid status")
    if status in ("blocked","needs_review") and len(reason.strip())<12:raise ValueError("missing blocker")
    obj.update(status=status,blocked_reason=reason.strip()[:1300] or None,updated_at=now())
    write(path(thread),obj)
    return obj

def mark_review(thread,evidence):
    if len(evidence.strip())<30:raise ValueError("completion evidence too short")
    obj=load(thread)
    if obj["status"]!="active":raise ValueError("goal not active")
    obj.update(status="needs_review",completion_proposal=evidence[:3000],updated_at=now())
    write(path(thread),obj)
    return obj

def add_task(thread,key,title,depends=()):
    obj=load(thread)
    tasks.add(obj,key,title,depends)
    if obj['status'] in ('blocked','needs_review') and tasks.ready(obj):
        obj['status']='active'
        obj['blocked_reason']=None  # Original reason retained in legacy-blocker task.
    write(path(thread),obj)
    return obj

def task_state(thread,key,status,reason=None,evidence=None):
    obj=load(thread)
    tasks.transition(obj,key,status,reason,evidence)
    obj['status']=tasks.aggregate(obj)
    if obj['status']=='active':obj['blocked_reason']=None
    write(path(thread),obj)
    return obj

def reconcile_intent(thread,message_id,title=None,acceptance=None,priority=None):
    obj=load(thread)
    tasks.reconcile(obj,message_id,title,acceptance,priority)
    sync_task='sync-'+message_id.replace('-','')[:14].lower()
    if any(t['id']==sync_task for t in obj['tasks']):
        tasks.transition(obj,sync_task,'completed',
            evidence='Reconciled recorded client-origin user instruction '+message_id)
    if priority is not None and not tasks.ready(obj):
        task_id='work-'+message_id.replace('-','')[:14].lower()
        if not any(t['id']==task_id for t in obj['tasks']):
            tasks.add(obj,task_id,priority)
    obj['status']=tasks.aggregate(obj)
    if obj['status']=='active':obj['blocked_reason']=None
    write(path(thread),obj)
    return obj

def enabled(thread,value):
    obj=load(thread)
    if value and obj["status"]!="active":raise ValueError("goal inactive")
    obj["auto_enabled"]=bool(value)
    obj["updated_at"]=now()
    write(path(thread),obj)
    return obj

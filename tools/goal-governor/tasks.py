"""Task-level goal planning and non-authoritative conversation-sync queue."""
import hashlib, json, re
from datetime import datetime, timezone

STATES={'ready','running','blocked','completed','deferred'}
MAX_TASKS=256
MAX_PENDING_INTENTS=20
IMMUTABLE_CONSTRAINTS=(
    'Never bypass explicit human authorization for privileged browser, broker or external writes.',
    'Never replay an ambiguous external write without read-only outcome reconciliation.',
    'Preserve retained operation IDs, leases, nonces, budgets and other protected state.',
    'Never interpret goal reconciliation as permission to change runtime authorization.',
)

def normalize(goal):
    goal.setdefault('tasks',[])
    goal.setdefault('intent_sync',{'last_seen_message':None,'pending':[],'reconciled':[]})
    goal.setdefault('plan_revision',0)
    # These authorization boundaries are invariants, not ordinary goal text.
    goal['immutable_constraints']=list(IMMUTABLE_CONSTRAINTS)
    if (goal.get('status')=='blocked' and goal.get('blocked_reason')
            and not any(t.get('id')=='legacy-blocker' for t in goal['tasks'])
            and not any(t.get('state')=='blocked' for t in goal['tasks'])):
        # v1 stored only a global blocker. Preserve it as an independent task
        # before new alpha work reactivates the overall goal.
        goal['tasks'].append({'id':'legacy-blocker',
           'title':'Resolve the preexisting blocked project operation safely',
           'state':'blocked','depends_on':[],
           'blocker':str(goal['blocked_reason'])[:1200], 'evidence':None})
        goal['plan_revision']+=1
    return goal

def add(goal,key,title,depends=()):
    normalize(goal)
    if not re.fullmatch(r'[a-z][a-z0-9_-]{2,63}',key):raise ValueError('invalid task key')
    if len(title.strip())<12:raise ValueError('title too short')
    if len(goal['tasks'])>=MAX_TASKS or any(t['id']==key for t in goal['tasks']):raise ValueError('duplicate or too many tasks')
    existing={t['id'] for t in goal['tasks']}
    if not set(depends).issubset(existing) or key in depends:raise ValueError('dependency unknown')
    goal['tasks'].append({'id':key,'title':title.strip()[:300],'state':'ready',
        'depends_on':list(depends),'blocker':None,'evidence':None})
    goal['plan_revision']+=1
    return goal

def transition(goal,key,status,reason=None,evidence=None):
    normalize(goal)
    if status not in STATES:raise ValueError('invalid task state')
    task=next((x for x in goal['tasks'] if x['id']==key),None)
    if task is None:raise ValueError('unknown task')
    if status=='blocked' and (not reason or len(reason.strip())<12):raise ValueError('explain blocker')
    if status=='completed' and (not evidence or len(evidence.strip())<16):raise ValueError('verified evidence required')
    if status in ('running','completed') and any(
        next(t for t in goal['tasks'] if t['id']==dep)['state']!='completed' for dep in task['depends_on']):
        raise ValueError('dependencies incomplete')
    task['state']=status
    task['blocker']=reason.strip()[:1200] if status=='blocked' else None
    if status=='completed':task['evidence']=evidence.strip()[:1500]
    goal['plan_revision']+=1
    return goal

def ready(goal):
    normalize(goal)
    completed={t['id'] for t in goal['tasks'] if t['state']=='completed'}
    return [t for t in goal['tasks'] if t['state']=='ready' and set(t['depends_on']).issubset(completed)]

def aggregate(goal):
    normalize(goal)
    if not goal['tasks']:return goal['status']
    if ready(goal) or any(t['state']=='running' for t in goal['tasks']):return 'active'
    if all(t['state']=='completed' for t in goal['tasks']):return 'needs_review'
    if any(t['state']=='deferred' for t in goal['tasks']):return 'paused'
    return 'blocked'

def enqueue_user_message(goal,message_id,created_at,text):
    """Record untrusted intent for review; never directly execute the text."""
    normalize(goal)
    if not isinstance(text,str) or not text.strip():return False
    if any(p['message_id']==message_id for p in goal['intent_sync']['pending']):return False
    if message_id in goal['intent_sync']['reconciled']:return False
    # Do not copy prompt text into world-readable data or shell commands.
    # Exact text is retrieved from T3 by the already-authorized main agent.
    digest=hashlib.sha256(text.encode()).hexdigest()
    if len(goal['intent_sync']['pending'])>=MAX_PENDING_INTENTS:
        return None  # Queue full: caller MUST NOT advance its read cursor.
    goal['intent_sync']['pending'].append({'message_id':message_id,
        'created_at':created_at,'sha256':digest})
    goal['intent_sync']['last_seen_message']=message_id
    return True

def reconcile(goal,message_id,new_title=None,acceptance=None,priority=None):
    normalize(goal)
    pending=next((p for p in goal['intent_sync']['pending'] if p['message_id']==message_id),None)
    if not pending:raise ValueError('message not pending reconciliation')
    if new_title is not None:
        if len(new_title.strip())<8:raise ValueError('invalid title')
        goal['title']=new_title.strip()[:300]
    if acceptance is not None:
        if not acceptance or len(acceptance)>24 or any(len(a.strip())<10 for a in acceptance):
            raise ValueError('invalid acceptance criteria')
        # Existing acceptance is archived, not silently discarded.
        goal.setdefault('acceptance_history',[]).append({'criteria':goal['acceptance'],
            'superseded_by_message':message_id})
        goal['acceptance']=[a.strip()[:400] for a in acceptance]
    if priority is not None:goal['next_action']=priority.strip()[:1800]
    goal['intent_sync']['pending']=[p for p in goal['intent_sync']['pending'] if p['message_id']!=message_id]
    goal['intent_sync']['reconciled'].append(message_id)
    goal['plan_revision']+=1
    return goal

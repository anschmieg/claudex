"""Detect UI-origin instructions in T3 read-only events; no prompt execution."""
import json
from datetime import datetime,timezone,timedelta


def client_messages(db,thread,after,limit=30):
    """Only commands originating from the T3 client are treated as user intent.

    Provider/system-created user-role messages (cron, agents, recovery) cannot
    modify the user's durable goal. This is not an LLM classifier.
    """
    rows=db.execute("""SELECT occurred_at,payload_json FROM orchestration_events
       WHERE stream_id=? AND actor_kind='client'
         AND event_type='thread.turn-start-requested' AND occurred_at>?
       ORDER BY occurred_at ASC LIMIT ?""",(thread,after,limit)).fetchall()
    messages=[]
    for event in rows:
        try:
            data=json.loads(event['payload_json'] or '{}')
            mid=data.get('messageId')
            if not isinstance(mid,str) or len(mid)>128:continue
            message=db.execute("""SELECT message_id,created_at,text FROM projection_thread_messages
               WHERE thread_id=? AND message_id=? AND role='user' LIMIT 1""",(thread,mid)).fetchone()
            if message and isinstance(message['text'],str) and message['text'].strip():
                messages.append(dict(message_id=mid,created_at=message['created_at'],
                                     text=message['text'],event_at=event['occurred_at']))
        except (TypeError,ValueError,KeyError):continue
    return messages


def ingest(goal,db):
    from tasks import add, enqueue_user_message, normalize
    normalize(goal)
    sync=goal['intent_sync']
    cursor=sync.get('cursor')
    if not cursor:
        # v1 migration: recover the latest human instruction even if the
        # previous agent updated the goal AFTER receiving that instruction.
        # Bound the bootstrap lookback to avoid replaying an ancient backlog.
        since=(datetime.now(timezone.utc)-timedelta(hours=6)).isoformat().replace('+00:00','Z')
        cursor=max(goal.get('enrolled_at') or since,since)
    events=client_messages(db,goal['thread_id'],cursor)
    altered=False
    for event in events:
        mid=event['message_id']
        enqueued=enqueue_user_message(goal,mid,event['created_at'],event['text'])
        if enqueued is None:
            # Keep the old cursor, so this instruction remains pending in the
            # next poll instead of being silently dropped under load.
            break
        if enqueued:
            task_id='sync-'+mid.replace('-','')[:14].lower()
            if not any(t['id']==task_id for t in goal['tasks']):
                add(goal,task_id,'Reconcile latest user instruction with durable goals, tasks and approval boundaries')
            # New independent reconciliation task can unblock the *project*
            # while leaving existing protected operations individually blocked.
            if goal['status'] in ('blocked','needs_review'):
                if goal['status']=='needs_review' and goal.get('blocked_reason'):
                    goal.setdefault('review_history',[]).append({
                       'prior_reason':goal['blocked_reason'],
                       'superseded_by_message':mid})
                goal['status']='active'
                goal['blocked_reason']=None  # Protected blocker retained as task.
            altered=True
        sync['cursor']=event['event_at']
    return altered

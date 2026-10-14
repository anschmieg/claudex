"""Tests: genuine T3 user-goal updates, independent blockers, evidence."""
import json,sqlite3,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT))
import state,sync,tasks
THREAD='11111111-2222-4333-8444-555555555555'
PROJECT='66666666-7777-4888-9999-aaaaaaaaaaaa'
MID='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
class SyncTests(unittest.TestCase):
 def setUp(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.work=Path(tmp.name)
  old=state.ROOT;state.ROOT=self.work/'state';self.addCleanup(lambda:setattr(state,'ROOT',old))
  self.project=self.work/'project';self.project.mkdir();project=self.project
  self.goal=state.create(THREAD,PROJECT,project,'Build safe Responses alpha',
    ['Preserve browser authorization','Verify genuine alpha request'],
    'Investigate separate alpha and run authorized baseline tests.')
  self.goal['updated_at']='2026-10-14T19:00:00Z'
  self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.addCleanup(self.db.close)
  self.db.execute('create table orchestration_events(stream_id text,actor_kind text,event_type text,occurred_at text,payload_json text)')
  self.db.execute('create table projection_thread_messages(thread_id text,message_id text,role text,created_at text,text text)')
 def message(self,actor='client'):
  when='2026-10-14T19:30:00Z'
  self.db.execute('insert into orchestration_events values (?,?,?,?,?)',(THREAD,actor,'thread.turn-start-requested',when,json.dumps({'messageId':MID})))
  self.db.execute('insert into projection_thread_messages values (?,?,?,?,?)',(THREAD,MID,'user',when,'Ship the safe alpha first, defer production hardening.'))
 def test_real_user_intent_dedup_and_task(self):
  self.message();self.assertTrue(sync.ingest(self.goal,self.db))
  self.assertEqual(len(tasks.ready(self.goal)),1)
  self.assertFalse(sync.ingest(self.goal,self.db))
  self.assertEqual(len(self.goal['intent_sync']['pending']),1)
 def test_provider_message_ignored(self):
  self.message('provider');self.assertFalse(sync.ingest(self.goal,self.db))
  self.assertFalse(self.goal['tasks'])
 def test_independent_work_despite_protected_block(self):
  tasks.add(self.goal,'browser-maintenance','Repair retained browser operation')
  tasks.transition(self.goal,'browser-maintenance','blocked','Explicit owner authorization is still required')
  self.goal['status']='blocked';self.message()
  self.assertTrue(sync.ingest(self.goal,self.db))
  self.assertEqual(self.goal['status'],'active')
  self.assertEqual(next(t for t in self.goal['tasks'] if t['id']=='browser-maintenance')['state'],'blocked')
  self.assertEqual(len(tasks.ready(self.goal)),1)
 def test_reconcile_preserves_acceptance_history(self):
  self.message();sync.ingest(self.goal,self.db);state.write(state.path(THREAD),self.goal)
  goal=state.reconcile_intent(THREAD,MID,'Deliver usable alpha first',
   ['Verify a real Responses request through permitted access'],
   'Implement standalone alpha using authorized available services.')
  self.assertFalse(goal['intent_sync']['pending'])
  self.assertEqual(goal['acceptance_history'][0]['criteria'][0],'Preserve browser authorization')
  self.assertEqual(goal['immutable_constraints'],list(tasks.IMMUTABLE_CONSTRAINTS))
  self.assertEqual(goal['status'],'active')
 def test_verified_decision_checkpoint(self):
  self.message();state.write(state.path(THREAD),self.goal)
  result=state.checkpoint(THREAD,'Implement and verify a standalone alpha next.',
    'New explicit user alpha priority has been verified.',evidence_kind='user_decision',evidence_ref=MID,db=self.db)
  self.assertTrue(state.evidence_valid(result,db=self.db))
  self.db.execute('update orchestration_events set actor_kind=? where stream_id=?',('provider',THREAD))
  self.assertFalse(state.evidence_valid(result,db=self.db))
 def test_unverified_decision_rejected(self):
  self.message('provider')
  with self.assertRaises(ValueError):state.user_message_evidence(self.db,THREAD,MID)
 def test_hashed_test_report_supports_progress_without_source_edits(self):
  report=self.project/'alpha-test-results.json'
  report.write_text('{"passed":21,"failed":0}')
  state.write(state.path(THREAD),self.goal)
  result=state.checkpoint(THREAD,'Run the next live alpha API acceptance check.',
    'Fresh reproducible test report passed all 21 checks.',artifact=report,
    evidence_kind='test_report')
  self.assertTrue(state.evidence_valid(result,db=self.db))
  with self.assertRaises(ValueError):state.checkpoint(THREAD,
    'Proceed to the next different stable API acceptance check.',
    'No additional test evidence was produced.',artifact=report,evidence_kind='test_report')
  report.write_text('{"passed":22,"failed":0}')
  self.assertFalse(state.evidence_valid(result,db=self.db))

 def test_full_sync_queue_preserves_unread_cursor(self):
  self.message()
  self.goal['intent_sync']['pending']=[{'message_id':str(i),'sha256':'0'*64,'created_at':'2026-10-14T19:00:00Z'} for i in range(20)]
  old_cursor=self.goal['intent_sync'].get('cursor')
  self.assertFalse(sync.ingest(self.goal,self.db))
  self.assertEqual(self.goal['intent_sync'].get('cursor'),old_cursor)
  self.assertEqual(len(self.goal['intent_sync']['pending']),20)
 def test_all_remaining_blocked_tasks_block_goal(self):
  state.write(state.path(THREAD),self.goal)
  state.add_task(THREAD,'browser-maintenance','Repair protected browser handoff')
  result=state.task_state(THREAD,'browser-maintenance','blocked',
    reason='Owner has not authorized privileged state maintenance')
  self.assertEqual(result['status'],'blocked')
  self.assertEqual(result['tasks'][0]['state'],'blocked')
  result=state.add_task(THREAD,'isolated-alpha','Prepare safe independent alpha')
  self.assertEqual(result['status'],'active')
  self.assertEqual(result['tasks'][0]['state'],'blocked')

 def test_dependencies_independent(self):
  tasks.add(self.goal,'verify-alpha','Verify baseline responses')
  tasks.add(self.goal,'deploy-alpha','Deploy authorized alpha',['verify-alpha'])
  self.assertEqual([x['id'] for x in tasks.ready(self.goal)],['verify-alpha'])
  with self.assertRaises(ValueError):tasks.transition(self.goal,'deploy-alpha','running')
  tasks.transition(self.goal,'verify-alpha','completed',evidence='Reproducible full alpha tests passed')
  self.assertEqual([x['id'] for x in tasks.ready(self.goal)],['deploy-alpha'])
if __name__=='__main__':unittest.main(verbosity=2)

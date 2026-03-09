"""
SCHEDULED BATCH PUSH — Daily at 12:00 AM (midnight)
=====================================================
This file is intentionally NOT imported in app.py.

HOW TO ACTIVATE:
  1. Install APScheduler:      pip install APScheduler
     (also add "APScheduler" to requirements.txt)

  2. In app.py, add near the top (after blueprint registrations):
        from scheduler import start_scheduler
        start_scheduler(app)

  3. Restart the Flask server — the job will run every day at 00:00 UTC.

WHAT IT DOES:
  - At midnight, finds every document in updated_data.edited_questions
    where is_synced != True
  - Pushes each to RTU SQL (QuestionMasters + QuestionMaster_Answer),
    same logic as the manual /api/questions/batch-push-rtu endpoint
  - Marks is_synced=True in MongoDB and writes an audit_log entry per question
  - Logs a summary to stdout (visible in Flask console / server logs)
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timezone


def _run_nightly_push(app):
    """Core push logic — runs inside Flask app context."""
    with app.app_context():
        from db import get_db_connection, get_updated_data_db, get_authorization_db

        now = datetime.now(timezone.utc).replace(tzinfo=None)   # store as naive UTC
        performed_by      = "scheduler"
        performed_by_name = "Scheduled Job"
        performed_by_role = "System"

        try:
            updated_db  = get_updated_data_db()
            auth_db     = get_authorization_db()
            edited_coll = updated_db['edited_questions']

            docs = list(edited_coll.find({'is_synced': {'$ne': True}}))

            if not docs:
                print(f"[SCHEDULER] {now:%Y-%m-%d %H:%M} — nothing to push, all synced.")
                return

            print(f"[SCHEDULER] {now:%Y-%m-%d %H:%M} — pushing {len(docs)} question(s) to RTU…")

            success_ids, failed_ids = [], []
            db = cursor = None

            try:
                db     = get_db_connection()
                cursor = db.cursor()

                for doc in docs:
                    qid = doc.get('que_id')
                    updates_made = []
                    try:
                        # ── QuestionMasters (question + explanation) ──────────────
                        qm_fields, qm_values = [], []
                        if doc.get('question') is not None:
                            qm_fields.append('Question = ?')
                            qm_values.append(doc['question'])
                            updates_made.append('question')
                        if doc.get('explanation') is not None:
                            qm_fields.append('AnswerExplanation = ?')
                            qm_values.append(doc['explanation'])
                            updates_made.append('explanation')
                        if qm_fields:
                            qm_values.append(qid)
                            cursor.execute(
                                f"UPDATE QuestionMasters SET {', '.join(qm_fields)} WHERE QueId = ?",
                                qm_values
                            )

                        # ── QuestionMaster_Answer (options A–D) ───────────────────
                        cursor.execute(
                            'SELECT AnsId FROM QuestionMaster_Answer '
                            'WHERE QueId = ? AND Status = 1 ORDER BY AnsId ASC',
                            (qid,)
                        )
                        ans_ids = [row[0] for row in cursor.fetchall()]
                        for i, field in enumerate(['optionA', 'optionB', 'optionC', 'optionD']):
                            if i < len(ans_ids) and doc.get(field) is not None:
                                cursor.execute(
                                    'UPDATE QuestionMaster_Answer '
                                    'SET Answer = ? WHERE AnsId = ? AND QueId = ?',
                                    (doc[field], ans_ids[i], qid)
                                )
                                updates_made.append(field)

                        db.commit()

                        # ── Mark synced in MongoDB ────────────────────────────────
                        edited_coll.update_one(
                            {'que_id': qid},
                            {'$set': {
                                'is_synced':          True,
                                'last_synced_date':   now,
                                'last_synced_by':     performed_by,
                                'last_synced_by_name': performed_by_name,
                            }}
                        )

                        # ── Audit log entry ───────────────────────────────────────
                        try:
                            auth_db['audit_log'].insert_one({
                                'que_id':            qid,
                                'performed_by':      performed_by,
                                'performed_by_name': performed_by_name,
                                'performed_by_role': performed_by_role,
                                'action_type':       'PushToRTU',
                                'action_date':       now,
                                'status':            'Synced',
                                'details':           f"Nightly push — fields: {', '.join(updates_made)}"
                            })
                        except Exception:
                            pass

                        success_ids.append(qid)

                    except Exception as qerr:
                        print(f"[SCHEDULER] ✗ QID {qid} failed: {qerr}")
                        failed_ids.append(qid)

            finally:
                try:
                    if cursor: cursor.close()
                    if db:     db.close()
                except Exception:
                    pass

            print(
                f"[SCHEDULER] Done — ✓ {len(success_ids)} pushed, "
                f"✗ {len(failed_ids)} failed."
                + (f" Failed QIDs: {failed_ids}" if failed_ids else "")
            )

        except Exception as e:
            print(f"[SCHEDULER] Fatal error during nightly push: {e}")


def start_scheduler(app):
    """
    Call this once from app.py to register and start the nightly push job.

    Example (add in app.py after blueprint registration):
        from scheduler import start_scheduler
        start_scheduler(app)
    """
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        func=_run_nightly_push,
        args=[app],
        trigger=CronTrigger(hour=0, minute=0),   # 00:00 UTC every day
        id="nightly_rtu_push",
        name="Nightly batch push to RTU",
        replace_existing=True,
        misfire_grace_time=300      # allow up to 5 min late start
    )
    scheduler.start()
    print("[SCHEDULER] Nightly RTU push job registered — fires daily at 00:00 UTC.")
    return scheduler

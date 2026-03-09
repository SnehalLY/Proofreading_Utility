"""
actions_routes.py — Question action endpoints (Save, Review, Push to RTU)
                    and history / admin utilities.

All mutating endpoints require the user to be present in the RTU UserMaster
table (validated via _require_rtu_user_id) so every change can be logged
back to QuestionProofReadingLogHistory in the RTU SQL database.

Endpoints:
  POST /api/questions/<id>/save          — Save edited question to MongoDB.
  POST /api/questions/<id>/push-to-rtu   — Push MongoDB edits to RTU SQL.
  POST /api/questions/<id>/review        — Mark question as reviewed.
  GET  /api/questions/<id>/history       — Per-question change history.
  GET  /api/history/high-level           — Global history with pagination.
  POST /api/history/backfill-edits       — Admin: backfill missing audit entries.
  GET  /api/review-queue                 — Edited questions pending review.
  GET  /api/questions/unpushed           — Admin: questions not yet synced to RTU.
  POST /api/questions/batch-push-rtu     — Admin: push all unsynced questions.
"""
from flask import Blueprint, jsonify, request, session
from db import get_db_connection, get_authorization_db, get_updated_data_db
from functools import wraps
from datetime import datetime
from bson import ObjectId

actions_bp = Blueprint("actions_bp", __name__)

# AUTH HELPERS
def _resolve_session_from_header():
    """
    Fallback: if Flask session has no user_id (e.g. old/invalid cookie),
    check the X-User-Id header, verify the user is active in MongoDB,
    and populate the session for the duration of this request.
    """
    if 'user_id' in session:
        return True  # already authenticated via cookie
    
    user_id_header = request.headers.get('X-User-Id', '').strip()
    if not user_id_header:
        return False
    
    try:
        from bson import ObjectId
        auth_db = get_authorization_db()
        user = auth_db['users'].find_one(
            {'_id': ObjectId(user_id_header), 'is_active': True},
            {'username': 1, 'role': 1}
        )
        if user:
            session['user_id'] = str(user['_id'])
            session['username'] = user['username']
            session['user_role'] = user['role']
            return True
    except Exception as e:
        print(f"[AUTH] X-User-Id validation failed: {e}")
    
    return False


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not _resolve_session_from_header():
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function


def role_required(required_roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not _resolve_session_from_header():
                return jsonify({"error": "Unauthorized"}), 401

            user_role = session.get('user_role')
            if user_role not in required_roles:
                return jsonify({
                    "error": f"Forbidden - {user_role} cannot perform this action"
                }), 403

            return f(*args, **kwargs)
        return decorated_function
    return decorator

# ──────────────────────────────────────────────────────────────
# RTU LOGGING HELPERS
# ──────────────────────────────────────────────────────────────

def _require_rtu_user_id(mongo_user_id):
    """
    Look up the logged-in user's email in RTU UserMaster (CustomerId=310).

    Returns: (rtu_user_id: int, error_response: None)   — user found, action allowed
             (None, flask_response)                      — user NOT in UserMaster, action blocked

    Only question-level actions (Save / Review / PushToRTU) call this.
    Admin/auth actions (ApproveSignup, RejectSignup, Login, etc.) never call this
    and are never logged to RTU.
    """
    try:
        auth_db = get_authorization_db()
        user = auth_db['users'].find_one(
            {'_id': ObjectId(mongo_user_id)},
            {'email': 1, 'username': 1}
        )
        if not user or not user.get('email'):
            return None, (jsonify({
                "error": "Your account has no email on record. Contact an Admin."
            }), 403)

        email = user['email']
        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute(
            "SELECT UserId FROM UserMaster WHERE LOWER(Email) = LOWER(?) AND CustomerId = 310",
            (email,)
        )
        row = cursor.fetchone()
        cursor.close()
        db.close()

        if row:
            return row[0], None
        else:
            print(f"[RTU_LOG] Blocked: {email} not found in RTU UserMaster (CustomerId=310)")
            return None, (jsonify({
                "error": (
                    f"Your email ({email}) is not registered in the RTU system. "
                    "Please use your RTU sub-user account (e.g. name_rtu@imocha.io) to perform this action."
                )
            }), 403)

    except Exception as e:
        print(f"[RTU_LOG] _require_rtu_user_id error: {e}")
        return None, (jsonify({"error": f"RTU user validation failed: {e}"}), 500)


def _log_to_rtu_proofread(question_id, rtu_user_id, proof_status):
    """
    Insert a row into QuestionProofReadingLogHistory in RTU.
    proof_status: 0 = In Progress (Save), 1 = Completed (Review / PushToRTU)
    Non-fatal — never raises, never blocks the main response.
    """
    if rtu_user_id is None:
        return
    try:
        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute(
            """
            INSERT INTO QuestionProofReadingLogHistory
                (QuestionId, ProofReadingStatus, CreatedBy, CreatedOn)
            VALUES (?, ?, ?, ?)
            """,
            (question_id, proof_status, rtu_user_id, datetime.utcnow())
        )
        db.commit()
        cursor.close()
        db.close()
    except Exception as e:
        print(f"[RTU_LOG] Proofread log failed (non-fatal): {e}")


# SAVE QUESTION ENDPOINT
@actions_bp.route("/api/questions/<int:question_id>/save", methods=["POST"])
@login_required
@role_required(['Editor', 'Admin', 'Senior Editor'])
def save_question(question_id):
    data = request.json
    user_id = session.get('user_id')
    username = session.get('username')
    user_role = session.get('user_role')
    # QB metadata sent from frontend for audit purposes only (not editable fields)
    qb_id   = data.get('qb_id')
    qb_name = data.get('qb_name')

    # Gate: only users registered in RTU UserMaster may save edits
    rtu_uid, rtu_err = _require_rtu_user_id(user_id)
    if rtu_err:
        return rtu_err

    try:
        mongo_db = get_updated_data_db()
        auth_db = get_authorization_db()

        # normalize collection name to `edited_questions` (used elsewhere in the codebase)
        edited_collection = mongo_db['edited_questions']

        # Store only the user-editable fields that map directly to RTU columns.
        # correctAnswer and difficulty are intentionally excluded (not editable by users).
        # que_id is the immutable key — only written on first insert via $setOnInsert,
        # never overwritten on subsequent saves.
        edited_collection.update_one(
            {"que_id": question_id},
            {
                "$set": {
                    "question":            data.get("question"),
                    "optionA":             data.get("optionA"),
                    "optionB":             data.get("optionB"),
                    "optionC":             data.get("optionC"),
                    "optionD":             data.get("optionD"),
                    "explanation":         data.get("explanation"),
                    "last_modified_by":    user_id,
                    "last_modified_by_name": username,
                    "last_modified_role":  user_role,
                    "last_modified_date":  datetime.utcnow(),
                    "is_synced":           False,
                    # Editing again resets any previous review — must be re-reviewed
                    "review_status":       None,
                    "reviewed_by_name":    None,
                    "reviewed_date":       None,
                    # QB metadata stored for reference only (not used in fetch logic)
                    "qb_id":   qb_id,
                    "qb_name": qb_name
                },
                "$setOnInsert": {
                    "que_id": question_id   # written only once when doc is first created
                }
            },
            upsert=True
        )

        # Save a version snapshot so Track Versions shows full history
        try:
            versions_col = mongo_db['question_versions']
            version_num = versions_col.count_documents({'que_id': question_id}) + 2  # V1=RTU, edits start at V2
            versions_col.insert_one({
                'que_id':         question_id,
                'version':        version_num,
                'question':       data.get('question'),
                'optionA':        data.get('optionA'),
                'optionB':        data.get('optionB'),
                'optionC':        data.get('optionC'),
                'optionD':        data.get('optionD'),
                'explanation':    data.get('explanation'),
                'saved_by_name':  username,
                'saved_by_role':  user_role,
                'saved_at':       datetime.utcnow(),
                'qb_id':          qb_id,
                'qb_name':        qb_name
            })
            print(f"[SAVE] Recorded version V{version_num} for QID-{question_id}")
        except Exception as ve:
            print(f"[SAVE] Version snapshot failed (non-fatal): {ve}")

        # Insert audit log for save (so history shows Save actions)
        try:
            auth_db['audit_log'].insert_one({
                'que_id': question_id,
                'performed_by': user_id,
                'performed_by_name': username,
                'performed_by_role': user_role,
                'action_type': 'Save',
                'action_date': datetime.utcnow(),
                'status': 'Edited',
                'qb_id':   qb_id,
                'qb_name': qb_name
            })
        except Exception:
            # non-fatal: continue even if audit insert fails
            pass

        # Log to RTU QuestionProofReadingLogHistory (ProofReadingStatus=0 = In Progress)
        # rtu_uid already resolved above — log insert is non-fatal
        _log_to_rtu_proofread(question_id, rtu_uid, 0)

        return jsonify({
            "message": "Question saved in MongoDB successfully",
            "question_id": question_id,
            "status": "Edited"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# PUSH TO RTU ENDPOINT
@actions_bp.route("/api/questions/<int:question_id>/push-to-rtu", methods=["POST"])
@login_required
@role_required(['Admin', 'Senior Editor', 'Editor'])
def push_to_rtu(question_id):
    """
    Push saved MongoDB edits (B) back to RTU SQL database (A).
    Only updates fields that were actually saved by the user:
    question text, optionA-D, explanation.
    correctAnswer and difficulty are NOT touched (never edited).
    """
    user_id  = session.get('user_id')
    username = session.get('username')
    user_role = session.get('user_role')

    # Gate: only users registered in RTU UserMaster may push to RTU
    rtu_uid, rtu_err = _require_rtu_user_id(user_id)
    if rtu_err:
        return rtu_err

    try:
        # 1. Fetch the MongoDB document
        updated_db = get_updated_data_db()
        edited_collection = updated_db['edited_questions']

        mongo_doc = edited_collection.find_one({'que_id': question_id})
        if not mongo_doc:
            mongo_doc = edited_collection.find_one({'que_id': str(question_id)})
        if not mongo_doc:
            return jsonify({"error": f"No edited data found in MongoDB for QID-{question_id}. Save edits first."}), 404

        # 2. Connect to RTU (SQL)
        db = get_db_connection()
        cursor = db.cursor()
        updates_made = []

        # 2a. Update QuestionMasters (question text + explanation)
        qm_fields, qm_values = [], []
        if mongo_doc.get('question') is not None:
            qm_fields.append("Question = ?")
            qm_values.append(mongo_doc['question'])
            updates_made.append('question')
        if mongo_doc.get('explanation') is not None:
            qm_fields.append("AnswerExplanation = ?")
            qm_values.append(mongo_doc['explanation'])
            updates_made.append('explanation')

        if qm_fields:
            qm_values.append(question_id)
            cursor.execute(
                f"UPDATE QuestionMasters SET {', '.join(qm_fields)} WHERE QueId = ?",
                qm_values
            )

        # 2b. Update QuestionMaster_Answer (options A-D)
        # Get AnsIds ordered by AnsId ASC — position determines which option
        cursor.execute(
            "SELECT AnsId FROM QuestionMaster_Answer WHERE QueId = ? AND Status = 1 ORDER BY AnsId ASC",
            (question_id,)
        )
        ans_ids = [row[0] for row in cursor.fetchall()]

        for i, field in enumerate(['optionA', 'optionB', 'optionC', 'optionD']):
            if i < len(ans_ids) and mongo_doc.get(field) is not None:
                cursor.execute(
                    "UPDATE QuestionMaster_Answer SET Answer = ? WHERE AnsId = ? AND QueId = ?",
                    (mongo_doc[field], ans_ids[i], question_id)
                )
                updates_made.append(field)

        db.commit()
        cursor.close()
        db.close()

        # 3. Mark as synced in MongoDB
        edited_collection.update_one(
            {'que_id': question_id},
            {'$set': {
                'is_synced': True,
                'last_synced_date': datetime.utcnow(),
                'last_synced_by': user_id,
                'last_synced_by_name': username
            }}
        )

        # 4. Write audit log
        try:
            auth_db = get_authorization_db()
            auth_db['audit_log'].insert_one({
                'que_id':             question_id,
                'performed_by':       user_id,
                'performed_by_name':  username,
                'performed_by_role':  user_role,
                'action_type':        'PushToRTU',
                'action_date':        datetime.utcnow(),
                'status':             'Synced',
                'details':            f"Fields synced: {', '.join(updates_made)}"
            })
        except Exception:
            pass

        # Log to RTU QuestionProofReadingLogHistory (ProofReadingStatus=1 = Completed)
        # rtu_uid already resolved above — log insert is non-fatal
        _log_to_rtu_proofread(question_id, rtu_uid, 1)

        print(f"[PUSH_RTU] QID-{question_id} pushed to RTU. Fields updated: {updates_made}")
        return jsonify({
            "message": f"QID-{question_id} pushed to RTU successfully",
            "question_id": question_id,
            "fields_updated": updates_made,
            "status": "Synced"
        })

    except Exception as e:
        print(f"[PUSH_RTU] Error: {e}")
        return jsonify({"error": str(e)}), 500


# REVIEW QUESTION ENDPOINT
@actions_bp.route("/api/questions/<int:question_id>/review", methods=["POST"])
@login_required
@role_required(['Admin', 'Senior Editor', 'Editor'])
def review_question(question_id):

    data = request.json
    auth_db = get_authorization_db()

    # Gate: only users registered in RTU UserMaster may mark reviews
    rtu_uid, rtu_err = _require_rtu_user_id(session.get('user_id'))
    if rtu_err:
        return rtu_err

    try:
        user_id  = session.get('user_id')
        username = session.get('username')
        user_role = session.get('user_role')
        now = datetime.utcnow()

        # Stamp review_status into edited_questions so the batch fetch
        #    picks it up on reload — even if this question has never been edited.
        try:
            updated_db = get_updated_data_db()
            updated_db['edited_questions'].update_one(
                {'que_id': question_id},
                {
                    '$set': {
                        'review_status':      'Completed',
                        'reviewed_by_name':   username,
                        'reviewed_date':      now
                    },
                    '$setOnInsert': {'que_id': question_id}
                },
                upsert=True
            )
        except Exception as e:
            pass  # stamp failure is non-fatal

        auth_db['audit_log'].insert_one({
            'que_id': question_id,
            'performed_by': user_id,
            'performed_by_name': username,
            'performed_by_role': user_role,
            'action_type': 'Review',
            'action_date': now,
            'status': 'Completed',
            'review_comment': data.get('reviewComment', '')
        })

        # Log to RTU QuestionProofReadingLogHistory (ProofReadingStatus=1 = Completed)
        # rtu_uid already resolved above — log insert is non-fatal
        _log_to_rtu_proofread(question_id, rtu_uid, 1)

        return jsonify({
            "message": "Question marked as complete successfully",
            "question_id": question_id,
            "status": "Completed"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# GET QUESTION HISTORY ENDPOINT
@actions_bp.route("/api/questions/<int:question_id>/history", methods=["GET"])
@login_required
def get_question_history(question_id):
    """
    Return a single unified timeline for a question, sorted newest-first.
    Each entry has:
      action_type  — Save (V2) / Review / PushToRTU / RTU ProofRead
      performed_by_name / performed_by_role
      action_date  — ISO string
      status       — Edited / Completed / Synced / In Progress
      source       — 'versions' | 'audit_log' | 'rtu'
      details      — optional comment or QB name
    """
    timeline = []

    # ── 1. Save snapshots (question_versions) — one row per Save ─────────────
    try:
        updated_db = get_updated_data_db()
        for v in updated_db['question_versions'].find({'que_id': question_id}):
            saved_at = v.get('saved_at')
            timeline.append({
                'action_type':       f"Save (V{v.get('version', '?')})",
                'performed_by_name': v.get('saved_by_name'),
                'performed_by_role': v.get('saved_by_role'),
                'action_date':       saved_at.isoformat() if hasattr(saved_at, 'isoformat') else str(saved_at) if saved_at else None,
                'status':            'Edited',
                'source':            'versions',
                'details':           v.get('qb_name') or str(v.get('qb_id', ''))
            })
    except Exception as e:
        print(f"[HISTORY] question_versions error: {e}")

    # ── 2. Audit log — Review / PushToRTU / legacy Save entries ──────────────
    try:
        auth_db = get_authorization_db()
        all_users = {str(u['_id']): u.get('username', 'Unknown')
                     for u in auth_db['users'].find({}, {'username': 1})}

        for entry in auth_db['audit_log'].find({'que_id': question_id}):
            performed_by = entry.get('performed_by')
            username = entry.get('performed_by_name') or all_users.get(str(performed_by), performed_by)
            action_date = entry.get('action_date')
            timeline.append({
                'action_type':       entry.get('action_type', 'Edit'),
                'performed_by_name': username,
                'performed_by_role': entry.get('performed_by_role'),
                'action_date':       action_date.isoformat() if isinstance(action_date, datetime) else str(action_date),
                'status':            entry.get('status'),
                'source':            'audit_log',
                'details':           entry.get('review_comment') or entry.get('details', '')
            })
    except Exception as e:
        print(f"[HISTORY] audit_log error: {e}")

    # ── 3. RTU QuestionProofReadingLogHistory — pushed / proofread entries ────
    try:
        db = get_db_connection()
        cursor = db.cursor()
        try:
            cursor.execute("""
                SELECT
                    qp.ProofReadingStatus,
                    qp.CreatedOn,
                    ISNULL(u.FirstName, '') + ' ' + ISNULL(u.LastName, '') AS UserName
                FROM QuestionProofReadingLogHistory qp
                LEFT JOIN UserMaster u ON qp.CreatedBy = u.UserId
                WHERE qp.QuestionId = ?
                ORDER BY qp.CreatedOn DESC
            """, (question_id,))
            rows = cursor.fetchall()
        except Exception:
            # Fallback without join
            cursor.execute("""
                SELECT ProofReadingStatus, CreatedOn, CreatedBy
                FROM QuestionProofReadingLogHistory
                WHERE QuestionId = ?
                ORDER BY CreatedOn DESC
            """, (question_id,))
            rows = cursor.fetchall()

        for row in rows:
            proof_status = row[0]
            created_on   = row[1]
            user_name    = row[2].strip() if row[2] and str(row[2]).strip() else 'Unknown'
            timeline.append({
                'action_type':       'RTU ProofRead',
                'performed_by_name': user_name,
                'performed_by_role': None,
                'action_date':       created_on.isoformat() if hasattr(created_on, 'isoformat') else str(created_on) if created_on else None,
                'status':            'Completed' if proof_status == 1 else 'In Progress',
                'source':            'rtu',
                'details':           ''
            })
        cursor.close()
        db.close()
    except Exception as e:
        print(f"[HISTORY] SQL connection error: {e}")

    # Sort newest first
    timeline.sort(key=lambda x: x.get('action_date') or '', reverse=True)

    return jsonify({
        'question_id': question_id,
        'total':       len(timeline),
        'history':     timeline
    })




@actions_bp.route("/api/history/high-level", methods=["GET"])
@login_required
def get_high_level_history():
    """Return global history with pagination from both MongoDB and SQL."""
    
    # Query parameters
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)
    action_type = request.args.get("action_type")
    
    # Enforce max limit
    limit = min(limit, 200)
    
    all_history = []
    
    # 1) Fetch from MongoDB audit_log
    try:
        auth_db = get_authorization_db()
        audit_collection = auth_db['audit_log']
        
        mongo_query = {}
        if action_type:
            mongo_query['action_type'] = action_type
        
        mongo_history = list(audit_collection.find(
            mongo_query
        ).sort('action_date', -1))
        
        # Pre-load all users for quick lookup
        users_collection = auth_db['users']
        all_users = {str(u['_id']): u.get('username', 'Unknown') for u in users_collection.find({}, {'username': 1})}
        
        for entry in mongo_history:
            # Get username from pre-loaded cache or use performed_by_name
            performed_by = entry.get('performed_by')
            username = entry.get('performed_by_name')
            if not username and performed_by:
                username = all_users.get(str(performed_by), performed_by)
            
            all_history.append({
                '_id': str(entry.get('_id')),
                'que_id': entry.get('que_id'),
                'action_type': entry.get('action_type'),
                'performed_by': performed_by,
                'performed_by_name': username,
                'performed_by_role': entry.get('performed_by_role'),
                'action_date': entry.get('action_date').isoformat() if isinstance(entry.get('action_date'), datetime) else str(entry.get('action_date')),
                'status': entry.get('status'),
                'source': 'mongo'
            })
    except Exception as e:
        print(f"[GLOBAL_HISTORY] MongoDB error: {e}")
    
    # 2) Fetch from SQL QuestionProofReadingLogHistory - with user join
    try:
        db = get_db_connection()
        cursor = db.cursor()
        
        # Join with UserMaster to get username
        sql_query = """
            SELECT TOP (?) 
                qp.QuestionId,
                qp.ProofReadingStatus,
                qp.CreatedBy,
                qp.CreatedOn,
                ISNULL(u.FirstName, '') + ' ' + ISNULL(u.LastName, '') AS UserName
            FROM QuestionProofReadingLogHistory qp
            LEFT JOIN UserMaster u ON qp.CreatedBy = u.UserId
            ORDER BY qp.CreatedOn DESC
        """
        
        try:
            cursor.execute(sql_query, (limit + offset,))
            rows = cursor.fetchall()
            
            for row in rows:
                # Get CreatedBy as string for display
                created_by = row[2]
                # Use the username from join, or fall back to User ID if not found
                username = row[4] if row[4] else f"User ID: {created_by}"
                
                all_history.append({
                    'que_id': row[0],
                    'action_type': 'ProofRead' if row[1] == 1 else 'Review',
                    'performed_by': created_by,
                    'performed_by_name': username,
                    'performed_by_role': None,
                    'action_date': row[3].isoformat() if hasattr(row[3], 'isoformat') else str(row[3]) if row[3] else None,
                    'status': 'Completed' if row[1] == 1 else 'Pending',
                    'source': 'sql'
                })
        except Exception as e:
            print(f"[GLOBAL_HISTORY] SQL join error: {e}")
            # Fallback to simple query
            cursor.execute("""
                SELECT TOP (?) 
                    QuestionId,
                    ProofReadingStatus,
                    CreatedBy,
                    CreatedOn
                FROM QuestionProofReadingLogHistory
                ORDER BY CreatedOn DESC
            """, (limit + offset,))
            rows = cursor.fetchall()
            
            for row in rows:
                created_by = row[2]
                username = f"User ID: {created_by}" if created_by is not None else 'Unknown'
                
                all_history.append({
                    'que_id': row[0],
                    'action_type': 'ProofRead' if row[1] == 1 else 'Review',
                    'performed_by': created_by,
                    'performed_by_name': username,
                    'performed_by_role': None,
                    'action_date': row[3].isoformat() if hasattr(row[3], 'isoformat') else str(row[3]) if row[3] else None,
                    'status': 'Completed' if row[1] == 1 else 'Pending',
                    'source': 'sql'
                })
        
        cursor.close()
        db.close()
    except Exception as e:
        print(f"[GLOBAL_HISTORY] SQL connection error: {e}")
    
    # 3) Sort all by date descending
    all_history.sort(key=lambda x: x.get('action_date') or '', reverse=True)
    
    # 4) Apply pagination
    total = len(all_history)
    paginated = all_history[offset:offset + limit]
    
    return jsonify({
        "total_records": total,
        "limit": limit,
        "offset": offset,
        "has_more": (offset + limit) < total,
        "history": paginated
    })


# =====================================================
# BACKFILL: create audit_log entries from existing edited_questions (Admin only)
# Useful when audit logging was missing for past saves
@actions_bp.route("/api/history/backfill-edits", methods=["POST"])
@login_required
@role_required(["Admin"])
def backfill_edit_audit():
    try:
        updated_db = get_updated_data_db()
        auth_db = get_authorization_db()

        edited_coll = updated_db.get('edited_questions')
        if edited_coll is None:
            return jsonify({"error": "edited_questions collection not found"}), 404

        edited_docs = list(edited_coll.find({}))
        created = 0

        for doc in edited_docs:
            qid = doc.get('que_id')
            if not qid:
                continue

            # if there is already a Save audit entry, skip
            exists = auth_db['audit_log'].find_one({"que_id": qid, "action_type": "Save"})
            if exists:
                continue

            audit_doc = {
                'que_id': qid,
                'performed_by': doc.get('last_modified_by'),
                'performed_by_name': doc.get('last_modified_by_name'),
                'performed_by_role': doc.get('last_modified_role'),
                'action_type': 'Save',
                'action_date': doc.get('last_modified_date', datetime.utcnow()),
                'status': doc.get('status', 'Edited')
            }

            auth_db['audit_log'].insert_one(audit_doc)
            created += 1

        return jsonify({"message": "Backfill complete", "created": created})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =====================================================
# REVIEW QUEUE — edited questions awaiting review
# =====================================================
@actions_bp.route("/api/review-queue", methods=["GET"])
@login_required
@role_required(["Admin", "Senior Editor"])
def get_review_queue():
    try:
        updated_db = get_updated_data_db()
        # All docs where review_status is not 'Completed' (None or missing = pending review)
        pending = list(updated_db['edited_questions'].find(
            {'review_status': {'$ne': 'Completed'}},
            {
                'que_id': 1, 'qb_name': 1, 'qb_id': 1,
                'question': 1, 'optionA': 1, 'optionB': 1, 'optionC': 1, 'optionD': 1,
                'explanation': 1,
                'last_modified_by_name': 1, 'last_modified_role': 1,
                'last_modified_date': 1, '_id': 0
            }
        ).sort('last_modified_date', -1))

        for doc in pending:
            if doc.get('last_modified_date'):
                doc['last_modified_date'] = doc['last_modified_date'].isoformat()

        return jsonify(pending)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =====================================================
# BATCH PUSH — preview unpushed + push all to RTU
# =====================================================
@actions_bp.route("/api/questions/unpushed", methods=["GET"])
@login_required
@role_required(["Admin"])
def get_unpushed_questions():
    """Returns all edited questions not yet synced to RTU."""
    try:
        updated_db = get_updated_data_db()
        docs = list(updated_db['edited_questions'].find(
            {'is_synced': {'$ne': True}},
            {
                'que_id': 1, 'qb_name': 1, 'qb_id': 1,
                'review_status': 1,
                'last_modified_by_name': 1, 'last_modified_role': 1,
                'last_modified_date': 1, '_id': 0
            }
        ).sort('last_modified_date', -1))
        for doc in docs:
            if doc.get('last_modified_date'):
                doc['last_modified_date'] = doc['last_modified_date'].isoformat()
        return jsonify(docs)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@actions_bp.route("/api/questions/batch-push-rtu", methods=["POST"])
@login_required
@role_required(["Admin"])
def batch_push_rtu():
    """Push all unsynced edited questions to RTU in one batch."""
    user_id   = session.get('user_id')
    username  = session.get('username')
    user_role = session.get('user_role')
    now       = datetime.utcnow()

    try:
        updated_db  = get_updated_data_db()
        auth_db     = get_authorization_db()
        edited_coll = updated_db['edited_questions']

        docs = list(edited_coll.find({'is_synced': {'$ne': True}}))
        if not docs:
            return jsonify({'message': 'Nothing to push — all questions already synced', 'results': []})

        results  = []   # per-question outcome
        db       = None
        cursor   = None

        try:
            db     = get_db_connection()
            cursor = db.cursor()

            for doc in docs:
                qid          = doc.get('que_id')
                updates_made = []
                try:
                    # --- QuestionMasters (question text + explanation) ---
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

                    # --- QuestionMaster_Answer (options A-D) ---
                    cursor.execute(
                        'SELECT AnsId FROM QuestionMaster_Answer WHERE QueId = ? AND Status = 1 ORDER BY AnsId ASC',
                        (qid,)
                    )
                    ans_ids = [row[0] for row in cursor.fetchall()]
                    for i, field in enumerate(['optionA', 'optionB', 'optionC', 'optionD']):
                        if i < len(ans_ids) and doc.get(field) is not None:
                            cursor.execute(
                                'UPDATE QuestionMaster_Answer SET Answer = ? WHERE AnsId = ? AND QueId = ?',
                                (doc[field], ans_ids[i], qid)
                            )
                            updates_made.append(field)

                    db.commit()

                    # mark synced in MongoDB
                    edited_coll.update_one(
                        {'que_id': qid},
                        {'$set': {
                            'is_synced':           True,
                            'last_synced_date':     now,
                            'last_synced_by':       user_id,
                            'last_synced_by_name':  username
                        }}
                    )

                    # audit log entry
                    try:
                        auth_db['audit_log'].insert_one({
                            'que_id':            qid,
                            'performed_by':      user_id,
                            'performed_by_name': username,
                            'performed_by_role': user_role,
                            'action_type':       'PushToRTU',
                            'action_date':       now,
                            'status':            'Synced',
                            'details':           f"Batch push — fields: {', '.join(updates_made)}"
                        })
                    except Exception:
                        pass

                    results.append({
                        'que_id':        qid,
                        'status':        'success',
                        'fields_updated': updates_made,
                        'review_status': doc.get('review_status')
                    })

                except Exception as qerr:
                    results.append({
                        'que_id':  qid,
                        'status':  'error',
                        'error':   str(qerr),
                        'review_status': doc.get('review_status')
                    })

        finally:
            try:
                if cursor: cursor.close()
                if db:     db.close()
            except Exception:
                pass

        success_count = sum(1 for r in results if r['status'] == 'success')
        error_count   = sum(1 for r in results if r['status'] == 'error')
        return jsonify({
            'message':       f'{success_count} pushed, {error_count} failed',
            'success_count': success_count,
            'error_count':   error_count,
            'results':       results
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

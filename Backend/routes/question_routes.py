"""
question_routes.py — Question Bank and Question fetch endpoints.

Endpoints:
  GET /api/question-banks          — List question banks (supports search + limit).
  GET /api/questions/<qb_id>       — All questions for a question bank,
                                     overlaid with MongoDB edits.
  GET /api/question/<question_id>  — Single question using the QTD flow
                                     (MongoDB edits + RTU metadata).
  GET /api/qtds                    — All question IDs from RTU (diagnostic).
"""
from flask import Blueprint, jsonify, request
from db import get_db_connection, get_updated_data_db

question_bp = Blueprint("question_bp", __name__)

# =====================================================
# HELPER FUNCTIONS
# =====================================================

def get_all_qtds():
    """
    Extract all Question Table Definitions (QTDs) from RTU database.
    This creates an array of all unique question identifiers/schemas.
    """
    try:
        db = get_db_connection()
        cursor = db.cursor()
        
        # Get all unique question IDs and their metadata
        query = """
        SELECT DISTINCT
            qm.QueId,
            qbm.QBId,
            qbm.QBName
        FROM QuestionMasters qm
        INNER JOIN QuestionBankMaster qbm ON qm.QBId = qbm.QBId
        WHERE qm.Status = 1 AND qbm.Status = 1 AND qbm.CustomerId = 310
        ORDER BY qm.QueId
        """
        
        cursor.execute(query)
        rows = cursor.fetchall()
        
        qtds = [
            {
                'question_id': row[0],
                'qb_id': row[1],
                'qb_name': row[2]
            }
            for row in rows
        ]
        
        cursor.close()
        db.close()
        return qtds
    except Exception as e:
        print(f"[QTD_EXTRACTION] Error: {e}")
        return []


def get_question_from_rtu(question_id):
    """
    Fetch question from RTU (SQL) database using QTD query.
    """
    try:
        db = get_db_connection()
        cursor = db.cursor()

        query = """WITH CTE_MAIN AS (
            SELECT
                qtm.QueType, qm.QueId, qm.CreatedOn, cm.Category, qbm.QBName, qbm.QBId,
                qm.Question, qm.DifficultyLevel, qm.AnswerExplanation, qm.Tags, qm.Points, qm.Author, qm.Status
            FROM QuestionBankMaster qbm
            INNER JOIN QuestionMasters qm ON qbm.QBId = qm.QBId
            INNER JOIN CategoryMaster cm ON qbm.CategoryId = cm.CategoryId
            LEFT JOIN QuestionTypeMaster qtm ON qm.QueTypeId = qtm.QueTypeId
            WHERE qm.QueId = ?
                AND qbm.status = 1
                AND qm.status = 1
        ),
        CTE_ANS AS (
            SELECT
                qma.QueId,
                qma.Answer,
                qma.IsCorrect,
                ROW_NUMBER() OVER(PARTITION BY qma.QueId ORDER BY qma.AnsId ASC) AS Order_Number
            FROM CTE_MAIN ct
            LEFT JOIN QuestionMaster_Answer qma ON ct.QueId = qma.QueId
            WHERE qma.status = 1
        ),
        CTE_OPTIONS AS (
            SELECT
                QueId, Answer,
                CASE
                    WHEN Order_Number = 1 THEN 'Option A'
                    WHEN Order_Number = 2 THEN 'Option B'
                    WHEN Order_Number = 3 THEN 'Option C'
                    WHEN Order_Number = 4 THEN 'Option D'
                    WHEN Order_Number = 5 THEN 'Option E'
                END AS [OPTION]
            FROM CTE_ANS
        ),
        CTE_OPT_PVT AS (
            SELECT *
            FROM CTE_OPTIONS
            PIVOT(
                MAX(Answer)
                FOR [OPTION]
                IN ([Option A],[Option B],[Option C],[Option D],[Option E])
            ) AS PivotTable
        ),
        CTE_CORRECT_ANS AS (
            SELECT
                QueId,
                CASE
                    WHEN Order_Number = 1 THEN 'A'
                    WHEN Order_Number = 2 THEN 'B'
                    WHEN Order_Number = 3 THEN 'C'
                    WHEN Order_Number = 4 THEN 'D'
                    WHEN Order_Number = 5 THEN 'E'
                END AS [Correct Answer]
            FROM CTE_ANS
            WHERE IsCorrect = 1
        ),
        CTE_LATEST_REVIEW AS (
            SELECT 
                qp.QuestionId,
                qp.ProofReadingStatus,
                qp.CreatedBy AS ReviewedBy,
                qp.CreatedOn AS ReviewedOn,
                ISNULL(u.FirstName, '') + ' ' + ISNULL(u.LastName, '') AS ReviewedByName
            FROM (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY QuestionId
                        ORDER BY CreatedOn DESC
                    ) AS rn
                FROM QuestionProofReadingLogHistory
                WHERE QuestionId = ?   -- filter early: only this one question
            ) qp
            LEFT JOIN UserMaster u ON qp.CreatedBy = u.UserId
            WHERE qp.rn = 1
        ),
        CTE_CORRECT_ANS_PVT AS (
            SELECT *
            FROM CTE_CORRECT_ANS
            PIVOT(
                MAX([Correct Answer])
                FOR [Correct Answer]
                IN ([A],[B],[C],[D],[E])
            ) AS PivotTable
        )
        SELECT TOP 1
            tmp.QueType as questionType,
            tmp.QueId as id,
            tmp.QueId as questionNumber,
            tmp.QBId as qb_id,
            tmp.CreatedOn as createdDate,
            tmp.Category as category,
            tmp.QBName as skill,
            tmp.Question as questionText,
            pvt_O.[Option A] as optionA,
            pvt_O.[Option B] as optionB,
            pvt_O.[Option C] as optionC,
            pvt_O.[Option D] as optionD,
            pvt_O.[Option E] as optionE,
            LTRIM(CONCAT_WS(',', pvt_A.A, pvt_A.B, pvt_A.C, pvt_A.D, pvt_A.E), ',') as correctAnswer,
            CASE
                WHEN tmp.DifficultyLevel = 1 THEN 'Easy'
                WHEN tmp.DifficultyLevel = 2 THEN 'Medium'
                WHEN tmp.DifficultyLevel = 3 THEN 'Hard'
            END as difficultyLevel,
            tmp.AnswerExplanation as answerExplanation,
            tmp.Tags as topic,
            tmp.Author as author,
            tmp.Status as status,
            CASE 
                WHEN pr.ProofReadingStatus = 1 THEN 'Completed'
                ELSE 'Pending'
            END AS reviewStatus,
            pr.ReviewedBy,
            pr.ReviewedByName,
            pr.ReviewedOn
        FROM CTE_MAIN tmp
        JOIN CTE_OPT_PVT pvt_O ON tmp.QueId = pvt_O.QueId
        LEFT JOIN CTE_CORRECT_ANS_PVT pvt_A ON tmp.QueId = pvt_A.QueId
        LEFT JOIN CTE_LATEST_REVIEW pr ON tmp.QueId = pr.QuestionId
        """

        cursor.execute(query, (question_id, question_id))
        row = cursor.fetchone()

        if not row:
            cursor.close()
            db.close()
            return None

        columns = [col[0] for col in cursor.description]
        data = dict(zip(columns, row))
        
        cursor.close()
        db.close()
        return data
    except Exception as e:
        print(f"[QTD_QUERY_RTU] Error fetching question {question_id}: {e}")
        return None


def get_questions_from_mongodb_batch(question_ids):
    """
    Fetch multiple questions from MongoDB in a single query using $in operator.
    Returns a dict keyed by int que_id -> document.
    """
    try:
        updated_db = get_updated_data_db()
        edited_collection = updated_db['edited_questions']
        
        int_ids = [int(x) for x in question_ids if x is not None]
        str_ids = [str(x) for x in int_ids]
        
        results = edited_collection.find({
            '$or': [
                {'que_id': {'$in': int_ids}},
                {'que_id': {'$in': str_ids}}
            ]
        })
        
        lookup = {}
        for doc in results:
            qid = doc.get('que_id')
            if isinstance(qid, str):
                try:
                    qid = int(qid)
                except (ValueError, TypeError):
                    pass
            lookup[qid] = doc
        
        return lookup
    except Exception as e:
        print(f"[MONGO_BATCH] Batch fetch error: {e}")
        return {}


def get_question_from_mongodb(question_id):
    """
    Fetch question from MongoDB (edited_questions collection).
    Tries both int and str que_id to handle either storage type.
    Returns the merged result dict, or None if not found.
    """
    try:
        updated_db = get_updated_data_db()
        edited_collection = updated_db['edited_questions']

        # Try int key first, fall back to string key
        edited = edited_collection.find_one({'que_id': question_id})
        if not edited:
            edited = edited_collection.find_one({'que_id': str(question_id)})

        if not edited:
            return None

        result = {
            'id': question_id,
            'questionText': edited.get('question'),
            'optionA': edited.get('optionA'),
            'optionB': edited.get('optionB'),
            'optionC': edited.get('optionC'),
            'optionD': edited.get('optionD'),
            'correctAnswer': edited.get('answer'),
            'difficultyLevel': edited.get('difficulty'),
            'answerExplanation': edited.get('explanation'),
            'isEdited': bool(edited.get('question') or edited.get('optionA') or edited.get('explanation')),
            'lastModifiedBy': edited.get('last_modified_by_name'),
            'lastModifiedDate': edited.get('last_modified_date').isoformat() if edited.get('last_modified_date') else None,
            'isSynced':         bool(edited.get('is_synced')),
            'lastSyncedByName': edited.get('last_synced_by_name'),
            'lastSyncedDate':   edited.get('last_synced_date').isoformat() if edited.get('last_synced_date') else None,
            'source': 'mongodb',
            'changes': {},
            # review_status persisted here by the review endpoint
            # _review_status_key_exists distinguishes:
            #   True + None  = was explicitly reset by save => Pending
            #   True + 'Completed' = reviewed => Completed
            #   False        = key never written (brand-new edit, never reviewed) => fall back to RTU
            'review_status':          edited.get('review_status'),
            '_review_status_key_set': 'review_status' in edited,
            'reviewed_by_name': edited.get('reviewed_by_name'),
            'reviewed_date':    edited.get('reviewed_date').isoformat() if edited.get('reviewed_date') else None,
        }
        
        return result

    except Exception as e:
        print(f"[MONGO] Error fetching question {question_id} from MongoDB: {e}")
        return None


def get_question_with_qtd_flow(question_id):
    """
    QTD (Question Table Definition) fetch flow:
    1. Check MongoDB first for any saved edits.
    2. If found: use MongoDB values for editable fields, supplement with RTU for metadata.
    3. If not found: fetch everything from RTU (SQL).
    """
    # Step 1: Check MongoDB for saved edits
    mongo_question = get_question_from_mongodb(question_id)

    if mongo_question:
        # Step 2: Merge — MongoDB editable fields + RTU metadata
        rtu_question = get_question_from_rtu(question_id)
        
        if rtu_question:
            # MongoDB wins for all user-editable fields; RTU provides structural/metadata fields
            merged = {
                # --- Structural / metadata (from RTU, not user-editable) ---
                'questionType':    rtu_question.get('questionType'),
                'questionNumber':  rtu_question.get('questionNumber'),
                'qb_id':           rtu_question.get('qb_id'),
                'createdDate':     rtu_question.get('createdDate'),
                'category':        rtu_question.get('category'),
                'skill':           rtu_question.get('skill'),
                'topic':           rtu_question.get('topic'),
                'author':          rtu_question.get('author'),
                'status':          rtu_question.get('status'),
                'reviewStatus':    rtu_question.get('reviewStatus'),
                'ReviewedBy':      rtu_question.get('ReviewedBy'),
                'ReviewedByName':  rtu_question.get('ReviewedByName'),
                'ReviewedOn':      rtu_question.get('ReviewedOn'),
                # --- Editable fields (MongoDB takes priority) ---
                'id':              question_id,
                'questionText':    mongo_question.get('questionText') or rtu_question.get('questionText'),
                'optionA':         mongo_question.get('optionA') if mongo_question.get('optionA') is not None else rtu_question.get('optionA'),
                'optionB':         mongo_question.get('optionB') if mongo_question.get('optionB') is not None else rtu_question.get('optionB'),
                'optionC':         mongo_question.get('optionC') if mongo_question.get('optionC') is not None else rtu_question.get('optionC'),
                'optionD':         mongo_question.get('optionD') if mongo_question.get('optionD') is not None else rtu_question.get('optionD'),
                'correctAnswer':   mongo_question.get('correctAnswer') or rtu_question.get('correctAnswer'),
                'difficultyLevel': mongo_question.get('difficultyLevel') or rtu_question.get('difficultyLevel'),
                'answerExplanation': mongo_question.get('answerExplanation') or rtu_question.get('answerExplanation'),
                # review_status from MongoDB takes priority over RTU reviewStatus.
                # If the key was explicitly set (edit happened), use MongoDB value:
                #   - 'Completed' => Completed
                #   - None        => Pending (reset by save)
                # If the key was never written (no prior save), fall back to RTU.
                'reviewStatus':    (
                    'Completed' if mongo_question.get('review_status') == 'Completed'
                    else 'Pending' if mongo_question.get('_review_status_key_set')
                    else rtu_question.get('reviewStatus')
                ),
                'ReviewedByName':  mongo_question.get('reviewed_by_name') or rtu_question.get('ReviewedByName'),
                'ReviewedOn':      mongo_question.get('reviewed_date') or rtu_question.get('ReviewedOn'),
                # --- Edit tracking ---
                'isEdited':         mongo_question.get('isEdited', False),
                'source':           'mongodb',
                'lastModifiedBy':   mongo_question.get('lastModifiedBy'),
                'lastModifiedDate': mongo_question.get('lastModifiedDate'),
                'isSynced':         mongo_question.get('isSynced', False),
                'lastSyncedByName': mongo_question.get('lastSyncedByName'),
                'lastSyncedDate':   mongo_question.get('lastSyncedDate'),
                'changes':          mongo_question.get('changes', {}),
            }
        else:
            # RTU unavailable — return MongoDB data as-is
            merged = mongo_question

        return merged

    # Step 3: Not in MongoDB — fetch everything from RTU
    rtu_question = get_question_from_rtu(question_id)
    if rtu_question:
        rtu_question['isEdited'] = False
        rtu_question['source'] = 'rtu'
        return rtu_question

    return None


# =====================================================
# API ENDPOINTS
# =====================================================

# FETCH QUESTION BANKS (List + Search + Limit)
@question_bp.route("/api/question-banks", methods=["GET"])
def get_question_banks():
    try:
        db = get_db_connection()
    except Exception as e:
        print(f"[QB_LIST] SQL connection failed: {e}")
        return jsonify({"error": "Database connection failed", "detail": str(e)}), 503

    cursor = db.cursor()

    limit = request.args.get("limit", 5000, type=int)
    search = request.args.get("search", "", type=str)

    query = """
        SELECT TOP (?)
            QBId AS id,
            QBName AS name,
            Tags AS description,
            CreatedOn AS created_date,
            NoOfQues AS question_count,
            Status,
            CustomerId
        FROM dbo.QuestionBankMaster
        WHERE Status = 1
          AND CustomerId = 310
          AND (
                QBName LIKE ?
                OR CAST(QBId AS VARCHAR) LIKE ?
              )
        ORDER BY QBName ASC
    """

    try:
        search_param = f"%{search}%"
        cursor.execute(query, (limit, search_param, search_param))

        rows = cursor.fetchall()
        columns = [col[0] for col in cursor.description]
        data = [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        print(f"[QB_LIST] Query failed: {e}")
        cursor.close(); db.close()
        return jsonify({"error": "Query failed", "detail": str(e)}), 500

    cursor.close()
    db.close()

    return jsonify(data)


# FETCH ALL QUESTIONS FOR A QUESTION BANK
@question_bp.route("/api/questions/<int:qb_id>", methods=["GET"])
def get_questions_by_bank(qb_id):
    try:
        db = get_db_connection()
    except Exception as e:
        print(f"[QB] SQL connection failed: {e}")
        return jsonify({"error": "Database connection failed", "detail": str(e)}), 503
    cursor = db.cursor()

    query = """WITH CTE_MAIN AS (
        SELECT
            qtm.QueType, qm.QueId, qm.CreatedOn, cm.Category, qbm.QBName,
            qm.Question, qm.DifficultyLevel, qm.AnswerExplanation, qm.Tags, qm.Points, qm.Author, qm.Status
        FROM QuestionBankMaster qbm
        INNER JOIN QuestionMasters qm ON qbm.QBId = qm.QBId
        INNER JOIN CategoryMaster cm ON qbm.CategoryId = cm.CategoryId
        LEFT JOIN QuestionTypeMaster qtm ON qm.QueTypeId = qtm.QueTypeId
        WHERE qbm.QBId = ?
            AND qbm.status = 1
            AND qm.status = 1
    ),
    CTE_ANS AS (
        SELECT
            qma.QueId,
            qma.Answer,
            qma.IsCorrect,
            ROW_NUMBER() OVER(PARTITION BY qma.QueId ORDER BY qma.AnsId ASC) AS Order_Number
        FROM CTE_MAIN ct
        LEFT JOIN QuestionMaster_Answer qma ON ct.QueId = qma.QueId
        WHERE qma.status = 1
    ),
    CTE_OPTIONS AS (
        SELECT
            QueId, Answer,
            CASE
                WHEN Order_Number = 1 THEN 'Option A'
                WHEN Order_Number = 2 THEN 'Option B'
                WHEN Order_Number = 3 THEN 'Option C'
                WHEN Order_Number = 4 THEN 'Option D'
                WHEN Order_Number = 5 THEN 'Option E'
            END AS [OPTION]
        FROM CTE_ANS
    ),
    CTE_OPT_PVT AS (
        SELECT *
        FROM CTE_OPTIONS
        PIVOT(
            MAX(Answer)
            FOR [OPTION]
            IN ([Option A],[Option B],[Option C],[Option D],[Option E])
        ) AS PivotTable
    ),
    CTE_CORRECT_ANS AS (
        SELECT
            QueId,
            CASE
                WHEN Order_Number = 1 THEN 'A'
                WHEN Order_Number = 2 THEN 'B'
                WHEN Order_Number = 3 THEN 'C'
                WHEN Order_Number = 4 THEN 'D'
                WHEN Order_Number = 5 THEN 'E'
            END AS [Correct Answer]
        FROM CTE_ANS
        WHERE IsCorrect = 1
    ),
    CTE_LATEST_REVIEW AS (
        SELECT 
            qp.QuestionId,
            qp.ProofReadingStatus,
            qp.CreatedBy AS ReviewedBy,
            qp.CreatedOn AS ReviewedOn,
            ISNULL(u.FirstName, '') + ' ' + ISNULL(u.LastName, '') AS ReviewedByName
        FROM (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY QuestionId
                    ORDER BY CreatedOn DESC
                ) AS rn
            FROM QuestionProofReadingLogHistory
            WHERE QuestionId IN (SELECT QueId FROM CTE_MAIN)  -- filter to only this QB's questions
        ) qp
        LEFT JOIN UserMaster u ON qp.CreatedBy = u.UserId
        WHERE qp.rn = 1
    ),
    CTE_CORRECT_ANS_PVT AS (
        SELECT *
        FROM CTE_CORRECT_ANS
        PIVOT(
            MAX([Correct Answer])
            FOR [Correct Answer]
            IN ([A],[B],[C],[D],[E])
        ) AS PivotTable
    )
    SELECT
        tmp.QueType as questionType,
        tmp.QueId as id,
        tmp.QueId as questionNumber,
        tmp.CreatedOn as createdDate,
        tmp.Category as category,
        tmp.QBName as skill,
        tmp.Question as questionText,
        pvt_O.[Option A] as optionA,
        pvt_O.[Option B] as optionB,
        pvt_O.[Option C] as optionC,
        pvt_O.[Option D] as optionD,
        pvt_O.[Option E] as optionE,
        LTRIM(CONCAT_WS(',', pvt_A.A, pvt_A.B, pvt_A.C, pvt_A.D, pvt_A.E), ',') as correctAnswer,
        CASE
            WHEN tmp.DifficultyLevel = 1 THEN 'Easy'
            WHEN tmp.DifficultyLevel = 2 THEN 'Medium'
            WHEN tmp.DifficultyLevel = 3 THEN 'Hard'
        END as difficultyLevel,
        tmp.AnswerExplanation as answerExplanation,
        tmp.Tags as topic,
        tmp.Author as author,
        tmp.Status as status,
        CASE 
            WHEN pr.ProofReadingStatus = 1 THEN 'Reviewed'
            ELSE 'Pending'
        END AS reviewStatus,
        pr.ReviewedBy,
        pr.ReviewedByName,
        pr.ReviewedOn
    FROM CTE_MAIN tmp
    JOIN CTE_OPT_PVT pvt_O ON tmp.QueId = pvt_O.QueId
    LEFT JOIN CTE_CORRECT_ANS_PVT pvt_A ON tmp.QueId = pvt_A.QueId
    LEFT JOIN CTE_LATEST_REVIEW pr ON tmp.QueId = pr.QuestionId
    ORDER BY tmp.CreatedOn DESC"""

    try:
        cursor.execute(query, (qb_id,))
        rows = cursor.fetchall()
    except Exception as e:
        print(f"[QB] SQL query failed for qb_id={qb_id}: {e}")
        cursor.close(); db.close()
        return jsonify({"error": "Query failed or timed out", "detail": str(e)}), 500

    if not rows:
        cursor.close()
        db.close()
        return jsonify([])

    columns = [col[0] for col in cursor.description]
    data = [dict(zip(columns, row)) for row in rows]
    
    # OVERLAY: Batch-fetch all edited questions from MongoDB in one query
    question_ids = [q["id"] for q in data]
    mongo_lookup = get_questions_from_mongodb_batch(question_ids)
    
    for question in data:
        doc = mongo_lookup.get(question["id"])
        # Tag every question with the QB id (from route param — already known)
        question["qb_id"] = qb_id
        if doc:
            # MongoDB wins for all editable fields; fall back to RTU if MongoDB field is None/empty
            question["questionText"]    = doc.get("question") or question["questionText"]
            question["optionA"]         = doc.get("optionA")  if doc.get("optionA")  is not None else question.get("optionA")
            question["optionB"]         = doc.get("optionB")  if doc.get("optionB")  is not None else question.get("optionB")
            question["optionC"]         = doc.get("optionC")  if doc.get("optionC")  is not None else question.get("optionC")
            question["optionD"]         = doc.get("optionD")  if doc.get("optionD")  is not None else question.get("optionD")
            question["correctAnswer"]   = doc.get("answer")   or question.get("correctAnswer")   # ← was missing before
            question["difficultyLevel"] = doc.get("difficulty") or question["difficultyLevel"]
            question["answerExplanation"] = doc.get("explanation") or question["answerExplanation"]
            # review_status stamped by review endpoint takes priority over RTU's reviewStatus
            if doc.get("review_status") == "Completed":
                question["reviewStatus"]    = "Completed"
                question["ReviewedByName"]  = doc.get("reviewed_by_name")
                question["ReviewedOn"]      = doc.get("reviewed_date").isoformat() if doc.get("reviewed_date") else None
            elif "review_status" in doc:
                # key exists but is None = reset by save => force Pending regardless of RTU
                question["reviewStatus"] = "Pending"
                question["ReviewedByName"] = None
                question["ReviewedOn"] = None
            question["isEdited"]        = bool(doc.get("question") or doc.get("optionA") or doc.get("explanation"))
            question["lastModifiedBy"]  = doc.get("last_modified_by_name")
            question["lastModifiedDate"] = doc.get("last_modified_date").isoformat() if doc.get("last_modified_date") else None
            question["isSynced"]         = bool(doc.get("is_synced"))
            question["lastSyncedByName"] = doc.get("last_synced_by_name")
            question["lastSyncedDate"]   = doc.get("last_synced_date").isoformat() if doc.get("last_synced_date") else None
        else:
            question["isEdited"] = False
            question["lastModifiedBy"] = None
            question["lastModifiedDate"] = None
            question["isSynced"] = False
            question["lastSyncedByName"] = None
            question["lastSyncedDate"] = None

    cursor.close()
    db.close()

    return jsonify(data)


# FETCH SINGLE QUESTION BY QID (Using QTD Flow)
# NOTE: Uses /api/question/ (singular) to avoid conflict with /api/questions/<qb_id>
@question_bp.route("/api/question/<int:question_id>", methods=["GET"])
def get_single_question(question_id):
    """
    Fetch single question using QTD flow:
    - First check MongoDB for edits
    - If not found, fetch from RTU (SQL)
    """
    question = get_question_with_qtd_flow(question_id)

    if question:
        return jsonify(question)
    else:
        return jsonify({"error": "Question not found"}), 404


# GET ALL QTDs (for admin/diagnostic purposes)
@question_bp.route("/api/qtds", methods=["GET"])
def get_all_qtds_endpoint():
    """
    Get all Question Table Definitions from RTU for diagnostic purposes.
    """
    qtds = get_all_qtds()
    return jsonify({
        "total": len(qtds),
        "qtds": qtds
    })


"""
Admin Routes for Change History viewing
Only accessible to Admin users
"""

from flask import Blueprint, jsonify, request, session
from db import get_authorization_db
from functools import wraps

admin_bp = Blueprint("admin_bp", __name__)

# AUTH HELPER
def _resolve_session_from_header():
    """Fallback session resolution from X-User-Id header."""
    if 'user_id' in session:
        return True
    
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
        print(f"[ADMIN] X-User-Id header validation failed: {e}")
    
    return False


def admin_required(f):
    """Decorator to ensure only admins can access the route."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not _resolve_session_from_header():
            return jsonify({"error": "Unauthorized"}), 401
        user_role = session.get('user_role')
        if user_role != 'Admin':
            return jsonify({"error": f"Forbidden - {user_role} cannot access admin features"}), 403
        return f(*args, **kwargs)
    return decorated_function


def login_required(f):
    """Decorator for any authenticated user."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not _resolve_session_from_header():
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function


# ====================================================================
# ADMIN ENDPOINTS
# ====================================================================

@admin_bp.route("/api/admin/questions/<int:question_id>/compare", methods=["GET"])
@login_required
def compare_question_versions(question_id):
    """
    Returns V1 (RTU original) and all saved versions for side-by-side comparison.
    """
    try:
        from routes.question_routes import get_question_from_rtu
        from db import get_updated_data_db

        rtu = get_question_from_rtu(question_id)

        def normalize_rtu(q):
            if not q:
                return None
            return {
                'question':    q.get('questionText') or q.get('question'),
                'optionA':     q.get('optionA'),
                'optionB':     q.get('optionB'),
                'optionC':     q.get('optionC'),
                'optionD':     q.get('optionD'),
                'explanation': q.get('answerExplanation') or q.get('explanation'),
            }

        # Fetch all saved version snapshots, oldest first
        mongo_db = get_updated_data_db()
        raw_versions = list(mongo_db['question_versions']
            .find({'que_id': question_id})
            .sort('version', 1))

        versions = []
        for v in raw_versions:
            versions.append({
                'version':       v['version'],
                'question':      v.get('question'),
                'optionA':       v.get('optionA'),
                'optionB':       v.get('optionB'),
                'optionC':       v.get('optionC'),
                'optionD':       v.get('optionD'),
                'explanation':   v.get('explanation'),
                'saved_by_name': v.get('saved_by_name'),
                'saved_by_role': v.get('saved_by_role'),
                'saved_at':      v['saved_at'].isoformat() if hasattr(v.get('saved_at'), 'isoformat') else str(v.get('saved_at', '')),
            })

        return jsonify({
            'question_id': question_id,
            'v1_rtu':      normalize_rtu(rtu),
            'versions':    versions,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

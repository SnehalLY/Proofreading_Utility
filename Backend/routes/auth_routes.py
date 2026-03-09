"""
auth_routes.py — User authentication and account management endpoints.

Endpoints:
  POST /api/auth/signup          — Submit signup request (pending admin approval).
  GET  /api/auth/users           — List all users (for login selector).
  GET  /api/auth/pending-signups — Admin: list pending approvals.
  POST /api/auth/approve/<id>    — Admin: approve signup with a role.
  POST /api/auth/reject/<id>     — Admin: reject signup.
  POST /api/auth/login           — Login and establish a session.
  POST /api/auth/logout          — Clear the session.
  GET  /api/auth/me              — Return the current logged-in user.
"""
from flask import Blueprint, jsonify, request, session
from db import get_authorization_db
from functools import wraps
from bson import ObjectId
from datetime import datetime
import re

auth_bp = Blueprint("auth_bp", __name__)

# Helper: Check if user is authenticated
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function


def role_required(required_roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return jsonify({"error": "Unauthorized"}), 401

            user_role = session.get('user_role')
            if user_role not in required_roles:
                return jsonify({"error": "Forbidden - Insufficient privileges"}), 403

            return f(*args, **kwargs)
        return decorated_function
    return decorator


# SIGN UP - Create New User
@auth_bp.route("/api/auth/signup", methods=["POST"])
def signup():
    """
    Signup endpoint
    Body:
    {
        "username": "john doe",
        "email": "john.doe@imocha.string",
        "role": "Editor" or "Admin"
    }
    """
    try:
        data = request.json
        username = data.get("username")
        email = data.get("email")

        if not username or not email:
            return jsonify({"error": "username and email required"}), 400

        # Email validation:
        #   Regular user : firstname.surname@imocha.<anything>
        #   RTU sub-user : name_rtu@imocha.io  /  name.x_rtu@imocha.io  /  name.surname_rtu@imocha.co
        email_regex = r'^([a-zA-Z]+\.[a-zA-Z]+@imocha\.[a-zA-Z]+|[a-zA-Z]+(\.[a-zA-Z]+)*_rtu@imocha\.(io|co))$'
        if not re.match(email_regex, email):
            return jsonify({
                "error": "Invalid email format. Must be: firstname.surname@imocha.[domain]  or  name_rtu@imocha.io / name_rtu@imocha.co"
            }), 400

        db = get_authorization_db()
        users_collection = db["users"]

        # Prevent duplicate email
        if users_collection.find_one({"email": email}):
            return jsonify({"error": "Email already exists"}), 400

        # All new users are pending approval (is_active=False, role assigned by admin)
        new_user = {
            "username": username,
            "email": email,
            "role": None,          # role is assigned by admin at approval time
            "is_active": False,    # All new signups are pending until admin approves
            "is_pending": True,
            "created_at": datetime.utcnow()
        }

        result = users_collection.insert_one(new_user)

        return jsonify({
            "message": "Signup submitted for admin approval",
            "user_id": str(result.inserted_id),
            "is_pending": True
        }), 201

    except Exception as err:
        return jsonify({"error": str(err)}), 500


# GET AVAILABLE USERS (Including pending signups)
@auth_bp.route("/api/auth/users", methods=["GET"])
def get_available_users():
    try:
        db = get_authorization_db()
        users_collection = db["users"]

        # Return all users (active and pending)
        users = list(users_collection.find(
            {},
            {"username": 1, "email": 1, "role": 1, "is_active": 1, "is_pending": 1}
        ))

        # Convert ObjectId to string for JSON serialization
        for user in users:
            user["id"] = str(user.pop("_id"))

        return jsonify(users)

    except Exception as err:
        return jsonify({"error": str(err)}), 500


# =====================================================
# PENDING SIGNUPS (Admin only)
# =====================================================
@auth_bp.route("/api/auth/pending-signups", methods=["GET"])
@login_required
@role_required(["Admin"])
def get_pending_signups():
    try:
        db = get_authorization_db()
        users_collection = db["users"]

        pending = list(users_collection.find({"is_pending": True}, {"username": 1, "email": 1, "role": 1, "created_at": 1}))
        for u in pending:
            u["id"] = str(u.pop("_id"))
        return jsonify(pending)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@auth_bp.route("/api/auth/approve/<user_id>", methods=["POST"])
@login_required
@role_required(["Admin"])
def approve_signup(user_id):
    try:
        data = request.get_json(silent=True) or {}
        role = data.get('role')
        if role not in ['Editor', 'Admin', 'Senior Editor']:
            return jsonify({'error': 'A valid role must be assigned: Editor, Senior Editor or Admin'}), 400

        db = get_authorization_db()
        users_collection = db["users"]

        result = users_collection.update_one(
            {"_id": ObjectId(user_id), "is_pending": True},
            {"$set": {"is_active": True, "is_pending": False, "role": role}}
        )
        if result.matched_count == 0:
            return jsonify({"error": "Pending user not found"}), 404

        # audit log (optional)
        try:
            db["audit_log"].insert_one({
                "action_type": "ApproveSignup",
                "performed_by": session.get('user_id'),
                "performed_by_name": session.get('username'),
                "target_user_id": user_id,
                "action_date": datetime.utcnow()
            })
        except Exception:
            pass

        return jsonify({"message": "User approved"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@auth_bp.route("/api/auth/reject/<user_id>", methods=["POST"])
@login_required
@role_required(["Admin"])
def reject_signup(user_id):
    try:
        db = get_authorization_db()
        users_collection = db["users"]

        result = users_collection.update_one({"_id": ObjectId(user_id), "is_pending": True}, {"$set": {"is_pending": False, "is_active": False, "is_rejected": True}})
        if result.matched_count == 0:
            return jsonify({"error": "Pending user not found"}), 404

        # audit log (optional)
        try:
            db["audit_log"].insert_one({
                "action_type": "RejectSignup",
                "performed_by": session.get('user_id'),
                "performed_by_name": session.get('username'),
                "target_user_id": user_id,
                "action_date": datetime.utcnow()
            })
        except Exception:
            pass

        return jsonify({"message": "User rejected"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# LOGIN ENDPOINT
@auth_bp.route("/api/auth/login", methods=["POST"])
def login():
    """
    Login endpoint.
    Body: { "user_id": "ObjectId_string" }
    Sets a session cookie on success.
    """
    data = request.json
    user_id = data.get("user_id")

    if not user_id:
        return jsonify({"error": "user_id required"}), 400

    try:
        db = get_authorization_db()
        users_collection = db["users"]

        try:
            obj_id = ObjectId(user_id)
        except Exception:
            return jsonify({"error": "Invalid user_id format"}), 400

        user = users_collection.find_one({"_id": obj_id})

        if not user:
            return jsonify({"error": "User not found"}), 404

        # Reject accounts still awaiting admin approval
        if user.get('is_pending'):
            return jsonify({
                "error": "Account pending admin approval",
                "is_pending": True
            }), 403

        # Reject deactivated accounts
        if not user.get("is_active"):
            return jsonify({"error": "Account not activated"}), 403

        # Establish server-side session
        session["user_id"] = str(user["_id"])
        session["username"] = user["username"]
        session["user_role"] = user["role"]

        return jsonify({
            "message": "Login successful",
            "user": {
                "id": str(user["_id"]),
                "username": user["username"],
                "email": user["email"],
                "role": user["role"]
            }
        })

    except Exception as err:
        return jsonify({"error": str(err)}), 500


# LOGOUT ENDPOINT
@auth_bp.route("/api/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "Logout successful"})


# GET CURRENT USER
@auth_bp.route("/api/auth/me", methods=["GET"])
@login_required
def get_current_user():
    return jsonify({
        "user_id": session.get("user_id"),
        "username": session.get("username"),
        "role": session.get("user_role")
    })

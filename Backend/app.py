"""
app.py \u2014 Flask application entry point.

Registers all blueprints, configures CORS and session settings,
and starts the development server when run directly.
"""
from flask import Flask
from flask_cors import CORS
import os

from routes.question_routes import question_bp
from routes.auth_routes import auth_bp
from routes.actions_routes import actions_bp
from routes.admin_routes import admin_bp

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Frontend')
app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path='')

# CORS Configuration - Allow credentials (sessions/cookies)
allowed_origins = [
    "http://localhost:3000", "http://127.0.0.1:3000",
    "http://localhost:5500", "http://127.0.0.1:5500",
    "http://localhost:8000", "http://127.0.0.1:8000",
]
# In production, allow same-origin requests (Railway assigns a domain)
railway_url = os.getenv('RAILWAY_PUBLIC_DOMAIN')
if railway_url:
    allowed_origins.append(f"https://{railway_url}")

CORS(app,
     origins=allowed_origins,
     supports_credentials=True,
     allow_headers=["Content-Type", "Authorization", "X-User-Id"],
     expose_headers=["Content-Type"],
     methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"]
)

# Session configuration
# Fixed secret key - must not change on restart or sessions get invalidated
app.secret_key = os.getenv('SECRET_KEY', 'internal-data-utility-secret-key-2026')
app.config['SESSION_COOKIE_NAME'] = 'session'
app.config['SESSION_COOKIE_HTTPONLY'] = False
app.config['SESSION_COOKIE_SECURE'] = bool(os.getenv('RAILWAY_PUBLIC_DOMAIN'))
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'        # Lax works for same-host (127.0.0.1) different-port fetch requests
app.config['SESSION_COOKIE_DOMAIN'] = None
app.config['PERMANENT_SESSION_LIFETIME'] = 86400     # 24 hours

# Register blueprints
app.register_blueprint(question_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(actions_bp)
app.register_blueprint(admin_bp)

# ── Nightly RTU push scheduler (INACTIVE) ──────────────────────────────────────
# To activate: pip install APScheduler, then uncomment the two lines below.
# from scheduler import start_scheduler
# start_scheduler(app)
# ──────────────────────────────────────────────────────────────────────────────

@app.route('/')
def serve_index():
    return app.send_static_file('index.html')

@app.route('/login.html')
def serve_login():
    return app.send_static_file('login.html')

@app.route('/signup.html')
def serve_signup():
    return app.send_static_file('signup.html')

if __name__ == "__main__":
    port = int(os.getenv('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port, use_reloader=False)

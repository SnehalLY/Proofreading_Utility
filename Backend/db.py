"""
db.py — Database connection helpers.

Provides:
  get_db_connection()      — New pyodbc connection to Azure SQL Server (RTU).
  get_authorization_db()   — MongoDB 'authorization' database (users, audit_log).
  get_updated_data_db()    — MongoDB 'updated_data' database (edited_questions,
                             question_versions).

MongoDB uses a module-level cached client so only one TCP connection is opened
per process lifetime (important for multi-threaded Flask workers).
"""
import os
import pyodbc
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

# ── SQL Server (RTU) ─────────────────────────────────────────────────────────
def get_db_connection():
    """Open and return a fresh pyodbc connection to the Azure SQL Server (RTU)."""
    server = os.getenv('AZURE_DB_SERVER', '')
    port = os.getenv('AZURE_DB_PORT', '1433')

    # Build SERVER value — avoid doubling "tcp:" if it's already in the env var
    if server.startswith('tcp:'):
        server_str = f"{server},{port}"
    else:
        server_str = f"tcp:{server},{port}"

    conn_str = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={server_str};"
        f"DATABASE={os.getenv('AZURE_DB_NAME')};"
        f"UID={os.getenv('AZURE_DB_USER')};"
        f"PWD={os.getenv('AZURE_DB_PASSWORD')};"
        "Encrypt=yes;"
        "TrustServerCertificate=yes;"
        "Connection Timeout=100;"
    )
    return pyodbc.connect(conn_str)

# ── MongoDB ──────────────────────────────────────────────────────────────────
MONGO_URL       = os.getenv('MONGO_URL')
MONGO_DB_NAME_A = os.getenv('MONGO_DB_NAME_A', 'authorization')
MONGO_DB_NAME_B = os.getenv('MONGO_DB_NAME_B', 'updated_data')

# Single shared MongoClient instance (thread-safe; reuse across requests)
_mongo_client = None

def _get_mongo_client():
    """Return the cached MongoClient, creating it on first call."""
    global _mongo_client

    if _mongo_client is not None:
        return _mongo_client
    
    try:
        _mongo_client = MongoClient(
            MONGO_URL,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=10000,
            socketTimeoutMS=10000,
            retryWrites=True,
            w='majority',
            tlsAllowInvalidCertificates=True
        )
        _mongo_client.admin.command('ping')
        print("✅ MongoDB connection successful")
        return _mongo_client
    except Exception as err:
        print(f"❌ MongoDB connection failed: {err}")
        raise


def get_authorization_db():
    """Return the 'authorization' MongoDB database (users, audit_log, etc.)."""
    client = _get_mongo_client()
    return client[MONGO_DB_NAME_A]


def get_updated_data_db():
    """Return the 'updated_data' MongoDB database (edited_questions, question_versions)."""
    client = _get_mongo_client()
    return client[MONGO_DB_NAME_B]
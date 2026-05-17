#!/usr/bin/env python3
"""
bootstrap_server.py — Lightweight Flask API that triggers bootstrap_orientation.py
for a new user immediately after they complete the onboarding questionnaire.

Port:  5050
Route: POST /bootstrap
Auth:  Supabase JWT validated against /auth/v1/user
"""

import json
import os
import tempfile
import time
import logging
import subprocess
from collections import defaultdict

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# ── Config ────────────────────────────────────────────────────────────────────

ENV_FILE                = '/root/.anthology.env'
BOOTSTRAP_SCRIPT        = '/root/anthology/bootstrap_orientation.py'
FIRST_DISPATCH_SCRIPT   = '/root/pipeline/first_dispatch.py'
SYSTEM_DIR              = '/root/anthology-system'
LOG_FILE                = '/root/anthology-system/logs/bootstrap-server.log'
VENV_PYTHON             = '/root/anthology-env/bin/python3'
PORT                    = 5050
SUBPROCESS_TIMEOUT      = 30
RATE_LIMIT_MAX          = 3
RATE_LIMIT_WINDOW       = 3600  # seconds
FIRST_DISPATCH_RATE_MAX = 1     # per hour per user

ALLOWED_ORIGINS = [
    'https://anthology-weld.vercel.app',
    'http://localhost',
    'http://localhost:3000',
    'http://localhost:8080',
    'http://127.0.0.1',
    'http://127.0.0.1:3000',
]

load_dotenv(ENV_FILE)
SUPABASE_URL      = os.environ.get('SUPABASE_URL', '').rstrip('/')
SUPABASE_ANON_KEY = os.environ.get('SUPABASE_ANON_KEY', '')

# ── Logging ───────────────────────────────────────────────────────────────────

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger('bootstrap-server')

# ── Rate limiting (in-memory) ─────────────────────────────────────────────────

_rate_store: dict = defaultdict(list)
_first_dispatch_rate_store: dict = defaultdict(list)


def is_rate_limited(user_id: str) -> bool:
    """Return True (and do NOT record) if user has hit the limit; else record and return False."""
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW
    _rate_store[user_id] = [t for t in _rate_store[user_id] if t > window_start]
    if len(_rate_store[user_id]) >= RATE_LIMIT_MAX:
        return True
    _rate_store[user_id].append(now)
    return False


def is_first_dispatch_rate_limited(user_id: str) -> bool:
    """Rate-limit /first-dispatch to 1 request per user per hour."""
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW
    _first_dispatch_rate_store[user_id] = [
        t for t in _first_dispatch_rate_store[user_id] if t > window_start
    ]
    if len(_first_dispatch_rate_store[user_id]) >= FIRST_DISPATCH_RATE_MAX:
        return True
    _first_dispatch_rate_store[user_id].append(now)
    return False


# ── Flask app ─────────────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app, origins=ALLOWED_ORIGINS)

# ── JWT validation ────────────────────────────────────────────────────────────

def validate_jwt(token: str, expected_user_id: str) -> bool:
    """Validate Bearer token via Supabase /auth/v1/user and confirm user_id matches."""
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        logger.error('SUPABASE_URL or SUPABASE_ANON_KEY not set')
        return False
    try:
        resp = requests.get(
            f'{SUPABASE_URL}/auth/v1/user',
            headers={
                'apikey':        SUPABASE_ANON_KEY,
                'Authorization': f'Bearer {token}',
            },
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning(f'Supabase auth returned {resp.status_code}')
            return False
        return resp.json().get('id') == expected_user_id
    except Exception as exc:
        logger.error(f'JWT validation exception: {exc}')
        return False

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/bootstrap', methods=['POST'])
def bootstrap():
    ts = __import__('datetime').datetime.utcnow().isoformat()

    # 1. Parse body
    try:
        body = request.get_json(force=True, silent=True)
        if not body or 'user_id' not in body:
            raise ValueError('Missing user_id')
        user_id = str(body['user_id']).strip()
        if not user_id:
            raise ValueError('Empty user_id')
    except Exception as exc:
        logger.warning(f'[{ts}] 400 bad body: {exc}')
        return jsonify({'status': 'error', 'message': 'Missing or malformed request body'}), 400

    # 2. Auth header
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        logger.warning(f'[{ts}] 401 no bearer token user={user_id}')
        return jsonify({'status': 'error', 'message': 'Missing Authorization header'}), 401
    token = auth_header[len('Bearer '):]

    # 3. Rate limit
    if is_rate_limited(user_id):
        logger.warning(f'[{ts}] 429 rate limited user={user_id}')
        return jsonify({'status': 'error', 'message': 'Rate limit exceeded — max 3 requests per hour'}), 429

    # 4. Validate JWT
    if not validate_jwt(token, user_id):
        logger.warning(f'[{ts}] 401 JWT invalid user={user_id}')
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    # 5. Script exists?
    if not os.path.isfile(BOOTSTRAP_SCRIPT):
        logger.error(f'[{ts}] 500 script not found: {BOOTSTRAP_SCRIPT}')
        return jsonify({'status': 'error', 'message': f'bootstrap_orientation.py not found at {BOOTSTRAP_SCRIPT}'}), 500

    # 6. Run bootstrap
    logger.info(f'[{ts}] bootstrapping user={user_id}')
    try:
        result = subprocess.run(
            [
                VENV_PYTHON,
                BOOTSTRAP_SCRIPT,
                '--user-id',    user_id,
                '--env',        ENV_FILE,
                '--system-dir', SYSTEM_DIR,
            ],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        logger.error(f'[{ts}] 504 subprocess timeout user={user_id}')
        return jsonify({'status': 'error', 'message': 'Bootstrap timed out after 30 seconds'}), 504

    if result.returncode == 0:
        # 7. Verify registry entry was written
        registry_path = os.path.join(SYSTEM_DIR, 'users', 'registry.json')
        try:
            with open(registry_path, 'r', encoding='utf-8') as rf:
                registry = json.load(rf)
            registered_ids = {u.get('user_id') for u in registry.get('users', [])}
            if user_id in registered_ids:
                logger.info(f'[{ts}] Registry verified for {user_id}')
            else:
                logger.warning(
                    f'[{ts}] WARNING: Registry entry missing after bootstrap for {user_id} '
                    f'— writing recovery entry'
                )
                try:
                    recovery_entry = {
                        'user_id':          user_id,
                        'name':             'Unknown',
                        'orientation_path': f'/root/anthology-system/users/{user_id}/orientation.md',
                        'active':           True,
                    }
                    registry.setdefault('users', []).append(recovery_entry)
                    registry_dir = os.path.dirname(registry_path)
                    with tempfile.NamedTemporaryFile(
                        'w', dir=registry_dir, delete=False,
                        suffix='.tmp', encoding='utf-8'
                    ) as tf:
                        json.dump(registry, tf, indent=2, ensure_ascii=False)
                        tmp_path = tf.name
                    os.replace(tmp_path, registry_path)
                    logger.info(f'[{ts}] Recovery entry written to registry.json for {user_id}')
                except Exception as recovery_exc:
                    logger.error(f'[{ts}] Recovery write failed for {user_id}: {recovery_exc}')
        except Exception as verify_exc:
            logger.error(f'[{ts}] Registry verification failed for {user_id}: {verify_exc}')

        logger.info(f'[{ts}] 200 ok user={user_id}')
        return jsonify({'status': 'ok', 'message': result.stdout}), 200
    else:
        logger.error(f'[{ts}] 500 bootstrap failed user={user_id} stderr={result.stderr!r}')
        return jsonify({'status': 'error', 'message': result.stderr}), 500


@app.route('/first-dispatch', methods=['POST'])
def first_dispatch():
    ts = __import__('datetime').datetime.utcnow().isoformat()

    # 1. Parse body
    try:
        body = request.get_json(force=True, silent=True)
        if not body or 'user_id' not in body:
            raise ValueError('Missing user_id')
        user_id = str(body['user_id']).strip()
        if not user_id:
            raise ValueError('Empty user_id')
    except Exception as exc:
        logger.warning(f'[{ts}] /first-dispatch 400 bad body: {exc}')
        return jsonify({'status': 'error', 'message': 'Missing or malformed request body'}), 400

    # 2. Auth header
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        logger.warning(f'[{ts}] /first-dispatch 401 no bearer token user={user_id}')
        return jsonify({'status': 'error', 'message': 'Missing Authorization header'}), 401
    token = auth_header[len('Bearer '):]

    # 3. Rate limit (1 request per user per hour)
    if is_first_dispatch_rate_limited(user_id):
        logger.warning(f'[{ts}] /first-dispatch 429 rate limited user={user_id}')
        return jsonify({'status': 'error', 'message': 'Rate limit exceeded — max 1 request per hour'}), 429

    # 4. Validate JWT
    if not validate_jwt(token, user_id):
        logger.warning(f'[{ts}] /first-dispatch 401 JWT invalid user={user_id}')
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    # 5. Script exists?
    if not os.path.isfile(FIRST_DISPATCH_SCRIPT):
        logger.error(f'[{ts}] /first-dispatch 500 script not found: {FIRST_DISPATCH_SCRIPT}')
        return jsonify({'status': 'error', 'message': f'first_dispatch.py not found at {FIRST_DISPATCH_SCRIPT}'}), 500

    # 6. Spawn non-blocking — return 202 immediately
    logger.info(f'[{ts}] /first-dispatch accepted user={user_id}')
    subprocess.Popen(
        [
            VENV_PYTHON,
            FIRST_DISPATCH_SCRIPT,
            '--user-id', user_id,
            '--env',     ENV_FILE,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # 7. Append to first-dispatch-queue.log for visibility
    try:
        queue_log_path = os.path.join(SYSTEM_DIR, 'logs', 'first-dispatch-queue.log')
        timestamp_str = __import__('datetime').datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        with open(queue_log_path, 'a', encoding='utf-8') as qf:
            qf.write(f'{timestamp_str} | {user_id} | spawned\n')
    except Exception as log_exc:
        logger.warning(f'[{ts}] /first-dispatch queue log write failed: {log_exc}')

    return jsonify({'status': 'accepted', 'message': 'First dispatch generation started'}), 202


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'}), 200


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    logger.info(f'Bootstrap server starting on port {PORT}')
    app.run(host='0.0.0.0', port=PORT, debug=False)

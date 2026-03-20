"""
MiroFish Health Endpoints
Prometheus-ready health checks for Neo4j, Ollama, and uploads directory.
"""

import os
import time
import requests
from datetime import datetime
from flask import Blueprint, jsonify, current_app

from ..config import Config
from ..utils.logger import get_logger

health_bp = Blueprint('health', __name__)
logger = get_logger('mirofish.health')


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _check_neo4j() -> tuple:
    """Ping the Neo4j HTTP browser endpoint. Returns (ok: bool, latency_ms: int)."""
    try:
        # Convert bolt://host:7687 → http://host:7474
        uri = Config.NEO4J_URI or 'bolt://localhost:7687'
        http_uri = uri.replace('bolt://', 'http://').replace(':7687', ':7474')
        start = time.monotonic()
        r = requests.get(http_uri, timeout=5)
        ms = int((time.monotonic() - start) * 1000)
        return r.status_code == 200, ms
    except Exception as e:
        logger.debug(f"Neo4j health check failed: {e}")
        return False, -1


def _check_ollama() -> tuple:
    """Ping Ollama /api/tags. Returns (ok: bool, latency_ms: int)."""
    try:
        base = (Config.LLM_BASE_URL or 'http://localhost:11434/v1').rstrip('/v1').rstrip('/')
        # Normalise docker-internal hostname when running outside container
        base = base.replace('host.docker.internal', 'localhost')
        # If base still ends with /v1, strip it
        if base.endswith('/v1'):
            base = base[:-3]
        start = time.monotonic()
        r = requests.get(f"{base}/api/tags", timeout=5)
        ms = int((time.monotonic() - start) * 1000)
        return r.status_code == 200, ms
    except Exception as e:
        logger.debug(f"Ollama health check failed: {e}")
        return False, -1


def _check_uploads_dir() -> bool:
    """Verify the uploads directory exists and is writable."""
    try:
        folder = os.path.abspath(Config.UPLOAD_FOLDER)
        os.makedirs(folder, exist_ok=True)
        test_path = os.path.join(folder, '.health_check')
        with open(test_path, 'w') as f:
            f.write('ok')
        os.remove(test_path)
        return True
    except Exception as e:
        logger.debug(f"Uploads dir check failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@health_bp.route('/api/health', methods=['GET'])
def health_check():
    """
    Core health check — returns status of all stack components.

    Response schema::

        {
            "status": "healthy" | "degraded" | "unhealthy",
            "timestamp": "<ISO8601>",
            "components": {
                "backend":     {"status": "up",   "latency_ms": 0},
                "neo4j":       {"status": "up",   "latency_ms": 42},
                "ollama":      {"status": "down", "latency_ms": -1},
                "uploads_dir": {"status": "ok",   "writable": true}
            }
        }

    HTTP 200 when healthy/degraded, 503 when unhealthy.
    """
    components = {}
    overall = "healthy"

    # Neo4j — critical; down → unhealthy
    neo4j_ok, neo4j_ms = _check_neo4j()
    components["neo4j"] = {"status": "up" if neo4j_ok else "down", "latency_ms": neo4j_ms}
    if not neo4j_ok:
        overall = "unhealthy"

    # Ollama — important but not fatal; down → degraded (unless already unhealthy)
    ollama_ok, ollama_ms = _check_ollama()
    components["ollama"] = {"status": "up" if ollama_ok else "down", "latency_ms": ollama_ms}
    if not ollama_ok and overall == "healthy":
        overall = "degraded"

    # Uploads dir — needed for artifacts; unavailable → degraded
    uploads_ok = _check_uploads_dir()
    components["uploads_dir"] = {"status": "ok" if uploads_ok else "error", "writable": uploads_ok}
    if not uploads_ok and overall == "healthy":
        overall = "degraded"

    # Backend is trivially up (we got here)
    components["backend"] = {"status": "up", "latency_ms": 0}

    # Surface any stored preflight results
    preflight = current_app.extensions.get('preflight')

    body = {
        "status": overall,
        "timestamp": datetime.now().isoformat(),
        "components": components,
    }
    if preflight is not None:
        body["preflight"] = preflight

    http_code = 503 if overall == "unhealthy" else 200
    return jsonify(body), http_code


@health_bp.route('/api/health/ready', methods=['GET'])
def readiness_check():
    """
    Readiness check — are ALL components up and ready for simulation?

    Prometheus should call this before starting any simulation run.
    Returns HTTP 200 when ready, 503 when not.
    """
    neo4j_ok, _ = _check_neo4j()
    ollama_ok, _ = _check_ollama()
    uploads_ok = _check_uploads_dir()

    ready = neo4j_ok and ollama_ok and uploads_ok

    return jsonify({
        "ready": ready,
        "timestamp": datetime.now().isoformat(),
        "neo4j": neo4j_ok,
        "ollama": ollama_ok,
        "uploads": uploads_ok,
    }), 200 if ready else 503

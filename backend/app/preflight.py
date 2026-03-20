"""
MiroFish Startup Preflight Checks
Run on app startup to detect missing services/config early.
Logs warnings but never blocks startup.
"""

import os
import time
import requests
import logging

from .config import Config

logger = logging.getLogger('mirofish.preflight')

# Required environment variable names (as strings, checked against os.environ)
_REQUIRED_ENV_VARS = [
    'NEO4J_URI',
    'NEO4J_PASSWORD',
    'LLM_BASE_URL',
    'LLM_MODEL_NAME',
]


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_neo4j() -> dict:
    """Verify Neo4j HTTP endpoint is reachable."""
    try:
        uri = Config.NEO4J_URI or 'bolt://localhost:7687'
        http_uri = uri.replace('bolt://', 'http://').replace(':7687', ':7474')
        r = requests.get(http_uri, timeout=5)
        if r.status_code == 200:
            return {"ok": True, "url": http_uri}
        return {"ok": False, "url": http_uri, "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _check_ollama() -> dict:
    """Verify Ollama /api/tags endpoint is reachable."""
    try:
        base = (Config.LLM_BASE_URL or 'http://localhost:11434/v1').rstrip('/')
        base = base.replace('host.docker.internal', 'localhost')
        if base.endswith('/v1'):
            base = base[:-3]
        url = f"{base}/api/tags"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            return {"ok": True, "url": url}
        return {"ok": False, "url": url, "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _check_required_model() -> dict:
    """Verify the configured LLM model is present in Ollama."""
    try:
        base = (Config.LLM_BASE_URL or 'http://localhost:11434/v1').rstrip('/')
        base = base.replace('host.docker.internal', 'localhost')
        if base.endswith('/v1'):
            base = base[:-3]
        r = requests.get(f"{base}/api/tags", timeout=5)
        models = [m['name'] for m in r.json().get('models', [])]
        required = Config.LLM_MODEL_NAME
        ok = required in models
        result = {"ok": ok, "required": required}
        if not ok:
            result["available"] = models
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _check_uploads_dir() -> dict:
    """Verify uploads directory exists and is writable."""
    folder = os.path.abspath(Config.UPLOAD_FOLDER)
    try:
        os.makedirs(folder, exist_ok=True)
        test_path = os.path.join(folder, '.preflight')
        with open(test_path, 'w') as f:
            f.write('ok')
        os.remove(test_path)
        return {"ok": True, "path": folder}
    except Exception as e:
        return {"ok": False, "path": folder, "error": str(e)}


def _check_required_env_vars() -> dict:
    """Check that required environment variables are set."""
    missing = []
    for var in _REQUIRED_ENV_VARS:
        # Accept values set either via os.environ or via Config class attributes
        env_val = os.environ.get(var)
        config_attr = var.replace('LLM_BASE_URL', 'LLM_BASE_URL') \
                        .replace('LLM_MODEL_NAME', 'LLM_MODEL_NAME')
        config_val = getattr(Config, config_attr, None)
        if not env_val and not config_val:
            missing.append(var)
    return {"ok": len(missing) == 0, "missing": missing}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_preflight_checks() -> dict:
    """
    Run all startup preflight checks.

    Logs warnings for any failures but does NOT prevent app startup.
    Returns a structured dict that the app can store and expose via /api/health.

    Example return value::

        {
            "neo4j":          {"ok": True,  "url": "http://localhost:7474"},
            "ollama":         {"ok": False, "error": "Connection refused"},
            "required_model": {"ok": True,  "required": "qwen2.5:32b"},
            "uploads_dir":    {"ok": True,  "path": "/app/uploads"},
            "env_vars":       {"ok": True,  "missing": []},
        }
    """
    results: dict = {}

    logger.info("Running startup preflight checks...")

    results['neo4j'] = _check_neo4j()
    results['ollama'] = _check_ollama()
    results['required_model'] = _check_required_model()
    results['uploads_dir'] = _check_uploads_dir()
    results['env_vars'] = _check_required_env_vars()

    failed = [k for k, v in results.items() if not v.get('ok', False)]

    if not failed:
        logger.info("✅ Preflight checks passed — all systems nominal")
    else:
        logger.warning("⚠️  Preflight warnings: %s", failed)
        for key in failed:
            detail = results[key]
            error_msg = detail.get('error') or detail.get('missing') or 'check failed'
            logger.warning("   %s: %s", key, error_msg)

    return results

"""
MiroFish Ops Endpoints
Prometheus-friendly polling endpoints for simulation lifecycle monitoring.
"""

from datetime import datetime
from flask import Blueprint, jsonify

from ..utils.logger import get_logger
from ..services.simulation_runner import SimulationRunner, RunnerStatus

ops_bp = Blueprint('ops', __name__)
logger = get_logger('mirofish.ops')

# Terminal runner states
_TERMINAL_STATUSES = {RunnerStatus.COMPLETED, RunnerStatus.STOPPED, RunnerStatus.FAILED}

# Stall threshold: no state update in this many seconds → stalled
_STALL_THRESHOLD_SECONDS = 600  # 10 minutes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_stalled(run_state) -> bool:
    """
    Return True if simulation is RUNNING but hasn't updated in 10+ minutes.
    """
    if run_state.runner_status != RunnerStatus.RUNNING:
        return False
    if not run_state.updated_at:
        return False
    try:
        last = datetime.fromisoformat(run_state.updated_at)
        elapsed = (datetime.now() - last).total_seconds()
        return elapsed > _STALL_THRESHOLD_SECONDS
    except Exception:
        return False


def _percent_complete(run_state) -> float:
    total = run_state.total_rounds or 0
    current = run_state.current_round or 0
    if total <= 0:
        return 0.0
    return round(min(current / total * 100, 100.0), 2)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@ops_bp.route('/api/ops/simulation/<simulation_id>/poll', methods=['GET'])
def poll_simulation(simulation_id: str):
    """
    Prometheus-friendly simulation status poll.

    Returns a compact, machine-readable status object. No human-only text.
    No ambiguous states. Prometheus should call this every 60 seconds during
    an active simulation.

    Response schema::

        {
            "simulation_id": "sim_abc123",
            "terminal": false,          // true = final state reached
            "success": null,            // true/false once terminal, null while running
            "status": "running",        // running | completed | failed | stopped | stalled | idle
            "percent_complete": 42.5,
            "rounds_done": 42,
            "rounds_total": 100,
            "stalled": false,           // true = RUNNING but no progress for 10+ min
            "stalled_since": null,      // ISO8601 timestamp of last update when stalled
            "last_updated": "2026-01-01T00:00:00"
        }

    HTTP 200 on success, 404 if simulation not found.
    """
    try:
        run_state = SimulationRunner.get_run_state(simulation_id)
    except Exception as e:
        logger.error(f"ops/poll: error fetching run state for {simulation_id}: {e}")
        return jsonify({"error": "Internal error fetching simulation state"}), 500

    if run_state is None:
        return jsonify({"error": f"Simulation '{simulation_id}' not found"}), 404

    status = run_state.runner_status
    terminal = status in _TERMINAL_STATUSES

    # Determine success
    if status == RunnerStatus.COMPLETED:
        success = True
    elif status in (RunnerStatus.FAILED, RunnerStatus.STOPPED):
        success = False
    else:
        success = None

    stalled = _is_stalled(run_state)
    status_label = "stalled" if stalled else status.value

    return jsonify({
        "simulation_id": simulation_id,
        "terminal": terminal,
        "success": success,
        "status": status_label,
        "percent_complete": _percent_complete(run_state),
        "rounds_done": run_state.current_round,
        "rounds_total": run_state.total_rounds,
        "stalled": stalled,
        "stalled_since": run_state.updated_at if stalled else None,
        "last_updated": run_state.updated_at,
    }), 200

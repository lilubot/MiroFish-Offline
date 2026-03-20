"""
MiroFish Routes Package
Ops and health endpoints for Prometheus monitoring.
"""

from .health import health_bp
from .ops import ops_bp

__all__ = ['health_bp', 'ops_bp']

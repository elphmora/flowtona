"""
app/api/dependencies.py

Application dependency registry for Job Service.

Phase 0 has no repositories or domain/application services yet. The
registry exists now as the stable composition seam used by create_app()
and will grow one vertical slice at a time.
"""

from dataclasses import dataclass


@dataclass(slots=True)
class ServiceRegistry:
    """Runtime application dependencies."""


def build_services() -> ServiceRegistry:
    """Construct the runtime service graph."""

    return ServiceRegistry()

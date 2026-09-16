"""
app/api/dependencies.py

Application dependency registry for Job Service.

build_services(settings) now takes Settings and constructs the real
object graph -- the Phase 0 placeholder ("build_services() takes no
arguments today... revisited when that becomes real") is revisited
here: ClientServiceClient needs CLIENT_SERVICE_BASE_URL/
CLIENT_SERVICE_TIMEOUT_SECONDS to construct. app/main.py's lifespan is
updated to pass resolved_settings through.

get_job_service() follows the same small request.app.state accessor
pattern already established (get_settings in
app/api/system/info.py, get_token_verifier in
app/api/auth_dependency.py).
"""

from dataclasses import dataclass

from fastapi import Request

from app.core.config import Settings
from app.repositories.in_memory.job_repository import InMemoryJobRepository
from app.repositories.job_repository import JobRepository
from app.services.client_service_client import ClientServiceClient
from app.services.job_service import JobService


@dataclass(slots=True)
class ServiceRegistry:
    """Runtime application dependencies."""

    job_repository: JobRepository
    job_service: JobService


def build_services(settings: Settings) -> ServiceRegistry:
    """Construct the runtime service graph."""
    job_repository = InMemoryJobRepository()
    client_service_client = ClientServiceClient(
        base_url=settings.CLIENT_SERVICE_BASE_URL,
        timeout_seconds=settings.CLIENT_SERVICE_TIMEOUT_SECONDS,
    )
    job_service = JobService(client_service_client, job_repository)
    return ServiceRegistry(job_repository=job_repository, job_service=job_service)


def get_job_service(request: Request) -> JobService:
    return request.app.state.services.job_service

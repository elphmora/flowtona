"""
app/main.py

Application entrypoint — assembles the FastAPI app from its
constituent pieces (middleware, exception handlers, routes). Kept
deliberately small and just wiring; no business logic here.

No routes registered yet — this is the exception-handling
infrastructure piece. Route registration is the next piece of work;
this service is not yet runnable as a meaningful API (see the operator
guide's "Running locally" section).

Middleware and exception handlers are registered in this specific
order: request ID middleware FIRST, so request.state.request_id
already exists by the time any exception handler runs and needs it.
"""

from fastapi import FastAPI

from app.api.errors import register_exception_handlers
from app.core.config import settings
from app.middleware.request_id import add_request_id_middleware

app = FastAPI(
    title=settings.SERVICE_NAME,
    version=settings.SERVICE_VERSION,
)

add_request_id_middleware(app)
register_exception_handlers(app)

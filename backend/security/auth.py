"""Bearer token authentication middleware for FastAPI/Starlette."""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Protect /api/* routes with a Bearer token.

    Behaviour:
    - No token configured (empty string) → allow everything (backward compat).
    - Only routes starting with /api/ are protected.
    - Static files, root (/), and WebSocket upgrades pass through freely.
    - Accepts token via Authorization: Bearer <token> header.
    - Also accepts ?token=<token> query param as fallback.
    - Returns 401 JSON on failure.
    """

    def __init__(self, app, api_token: str = ""):
        super().__init__(app)
        self._token = api_token.strip()

    async def dispatch(self, request: Request, call_next):
        # No token configured → open access (backward compat)
        if not self._token:
            return await call_next(request)

        path = request.url.path

        # Only protect /api/ routes; everything else is public
        if not path.startswith("/api/"):
            return await call_next(request)

        # Allow WebSocket upgrade requests through
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)

        # Check Authorization: Bearer <token> header
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            provided = auth_header[len("Bearer "):]
            if provided == self._token:
                return await call_next(request)

        # Fallback: ?token= query param
        query_token = request.query_params.get("token", "")
        if query_token and query_token == self._token:
            return await call_next(request)

        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized – valid Bearer token required"},
        )

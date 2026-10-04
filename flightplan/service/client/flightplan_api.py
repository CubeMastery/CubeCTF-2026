"""HTTP client for the Cairn Flight Plan Exchange API."""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx


DEFAULT_PORT = 4729


def default_url() -> str:
    return os.environ.get("FLIGHTPLAN_URL", f"http://localhost:{DEFAULT_PORT}")


class FlightPlanClient:
    """Async wrapper around the flight plan HTTP API."""

    def __init__(self, base_url: str, timeout: float = 10.0, verbose: bool = False) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.verbose = verbose
        self.log: list[str] = []
        event_hooks: dict[str, list] = {"request": [], "response": []}
        if verbose:
            event_hooks["request"].append(self._on_request)
            event_hooks["response"].append(self._on_response)
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            trust_env=False,
            event_hooks=event_hooks,
        )
        self.operator: Optional[dict] = None

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "FlightPlanClient":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.aclose()

    @property
    def logged_in(self) -> bool:
        return self.operator is not None

    async def _on_request(self, request: httpx.Request) -> None:
        lines = [f"→ {request.method} {request.url.path}"]
        if request.content:
            lines.append(f"  {request.content.decode(errors='replace')}")
        self.log.append("\n".join(lines))

    async def _on_response(self, response: httpx.Response) -> None:
        await response.aread()
        lines = [f"← {response.status_code} {response.reason_phrase}"]
        if response.content:
            lines.append(f"  {response.content.decode(errors='replace')}")
        self.log.append("\n".join(lines))

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = await self._http.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise ApiError(response.status_code, _detail(response))
        return response.json() if response.content else {}

    async def index(self) -> dict:
        """Portal metadata: name, tagline, and the published endpoint map."""
        return await self._request("GET", "/")

    async def airac(self) -> dict:
        """Current AIRAC cycle, publication window, and station beacon."""
        return await self._request("GET", "/airac.json")

    async def register(self, username: str, password: str, full_name: str, home_base: str) -> dict:
        return await self._request(
            "POST", "/api/register",
            json={
                "username": username,
                "password": password,
                "full_name": full_name,
                "home_base": home_base,
            },
        )

    async def login(self, username: str, password: str) -> dict:
        self.operator = await self._request("POST", "/api/login", json={"username": username, "password": password})
        return self.operator

    async def logout(self) -> dict:
        result = await self._request("POST", "/api/logout")
        self.operator = None
        return result

    async def list_plans(self) -> list:
        """Every plan filed by the signed-in operator, newest release first."""
        return (await self._request("GET", "/api/plans"))["plans"]

    async def create_plan(self, **fields: Any) -> dict:
        return await self._request("POST", "/api/plans", json=fields)

    async def briefing(self, ident: str) -> dict:
        """Public station packet for a plan."""
        return await self._request("GET", f"/api/briefing/{ident}")

    async def private_plan(self, ident: str) -> dict:
        """Crew remarks for a plan owned by the signed-in operator."""
        return await self._request("GET", f"/api/plans/{ident}/private")

    async def navlog(self, ident: str) -> dict:
        """Unsealed navlog record for a plan owned by the signed-in operator."""
        return await self._request("GET", f"/api/plans/{ident}/navlog")


class ApiError(Exception):
    """The service answered with an error status."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"HTTP {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


def _detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or response.reason_phrase
    if isinstance(payload, dict) and "detail" in payload:
        return str(payload["detail"])
    return str(payload)

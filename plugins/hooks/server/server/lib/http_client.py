"""HTTP POST helper for firing hooks at target MCP servers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30.0  # seconds


@dataclass
class FireResult:
    """Outcome of a single hook POST."""

    hook_id: str
    status_code: int | None = None
    body: str | None = None
    error: str | None = None
    result: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.status_code is not None and self.status_code < 400


async def post_hook(
    *,
    hook_id: str,
    url: str,
    target_tool: str,
    params: dict[str, Any],
    timeout: float = _DEFAULT_TIMEOUT,
) -> FireResult:
    """POST *params* to *url* and return a ``FireResult``.

    The payload sent is::

        {"tool": target_tool, "params": params}

    Any transport or HTTP error is caught and returned inside
    ``FireResult.error`` so that callers never see raw exceptions.
    """
    payload = {"tool": target_tool, "params": params}
    try:
        if url.startswith("unix://"):
            # Unix domain socket: unix:///tmp/claude-hooks-plugin.sock
            socket_path = url[len("unix://"):]
            transport = httpx.AsyncHTTPTransport(uds=socket_path)
            effective_url = "http://localhost/hook"
        else:
            transport = httpx.AsyncHTTPTransport(proxy=None)
            effective_url = url
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            resp = await client.post(effective_url, json=payload)
            body_text = resp.text
            # Handle empty response
            if not body_text or not body_text.strip():
                return FireResult(
                    hook_id=hook_id,
                    status_code=resp.status_code,
                    body=body_text,
                    error="Empty response",
                )
            # Try to parse structured response from /hook endpoint
            try:
                data = resp.json()
                if isinstance(data, dict):
                    if data.get("ok"):
                        raw_result = data.get("result")
                        return FireResult(
                            hook_id=hook_id,
                            status_code=resp.status_code,
                            body=body_text,
                            result=str(raw_result) if raw_result is not None else None,
                        )
                    else:
                        return FireResult(
                            hook_id=hook_id,
                            status_code=resp.status_code,
                            body=body_text,
                            error=data.get("error", f"HTTP {resp.status_code}"),
                        )
            except Exception:
                pass
            # Fallback for non-JSON responses
            return FireResult(
                hook_id=hook_id,
                status_code=resp.status_code,
                body=body_text,
                error=f"Non-JSON response: {body_text[:200]}",
            )
    except httpx.TimeoutException:
        msg = f"Timeout after {timeout}s posting to {url}"
        logger.warning("hook %s: %s", hook_id, msg)
        return FireResult(hook_id=hook_id, error=msg)
    except httpx.HTTPError as exc:
        msg = f"HTTP error posting to {url}: {exc}"
        logger.warning("hook %s: %s", hook_id, msg)
        return FireResult(hook_id=hook_id, error=msg)
    except Exception as exc:  # noqa: BLE001
        msg = f"Unexpected error posting to {url}: {exc}"
        logger.warning("hook %s: %s", hook_id, msg)
        return FireResult(hook_id=hook_id, error=msg)

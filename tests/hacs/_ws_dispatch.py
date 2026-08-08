"""Shared WebSocket dispatch helper for handler-level tests.

Home Assistant applies two layers *outside* the handler object:

* ``ActiveConnection.async_handle`` validates the incoming message
  against the schema that ``@websocket_api.websocket_command`` attached
  as ``handler._ws_schema``;
* ``async_setup_websocket_api`` wraps every handler in
  :func:`websocket_api.require_admin` at registration time.

Calling ``handler(...)`` — or worse, ``handler.__wrapped__(...)`` —
skips both.  :func:`dispatch` reproduces the pipeline faithfully so
unit-level tests still exercise the schema, and it lives in one place
so the non-obvious HA internals it encodes (the ``schema is False``
rule, the ``async_response`` background-task drain, re-raising handler
exceptions instead of swallowing them in a mock) cannot drift between
copies.

Note:
    :func:`dispatch` *simulates* the admin gate — it installs
    ``require_admin`` itself instead of observing the one
    ``async_setup_websocket_api`` installs.  Proof that the production
    registration actually wires the guard lives in
    ``test_websocket_authz.py::TestAdminGate`` (sweep over the
    registered table) and in ``test_websocket_full_stack.py`` (real
    socket, real registration).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import voluptuous as vol
from homeassistant.components import websocket_api

__all__ = ["dispatch"]


def _reraise(_msg: Any, err: BaseException) -> None:
    """Re-raise a handler exception instead of turning it into a WS error."""
    raise err


async def dispatch(
    handler: Any,
    hass: Any,
    connection: Any,
    msg: dict[str, Any],
    *,
    is_admin: bool = True,
) -> None:
    """Invoke a WebSocket command through its real decorator chain.

    Mirrors :meth:`ActiveConnection.async_handle`: validate ``msg``
    against the schema attached by ``@websocket_api.websocket_command``,
    then call the handler behind a ``require_admin`` wrapper (the same
    one ``async_setup_websocket_api`` installs at registration time),
    then drain the background task created by ``@async_response``.

    HA stores ``False`` instead of a voluptuous schema for the
    degenerate "only ``type``" command and enforces "no extra keys"
    itself by counting the message keys — that rule is reproduced here
    so type-only commands are validated exactly as in production.

    Args:
        handler: The decorated ``ws_*`` command function.
        hass: HA instance or stub; its ``async_create_background_task``
            is replaced so ``@async_response`` tasks can be awaited.
        connection: WebSocket connection stub.
        msg: Message payload; ``type`` is filled in automatically.
        is_admin: Whether the calling user is an administrator.

    Raises:
        vol.Invalid: If ``msg`` violates the command schema.
        Unauthorized: If ``is_admin`` is False.
    """
    msg = {"type": handler._ws_command, **msg}
    schema = handler._ws_schema
    if schema is False:
        if len(msg) > 2:
            raise vol.Invalid("extra keys not allowed")
    else:
        msg = schema(msg)

    connection.user = SimpleNamespace(is_admin=is_admin)
    # HA turns handler exceptions into WS errors; re-raise instead so a
    # crash inside the handler fails the test loudly.
    connection.async_handle_exception = MagicMock(side_effect=_reraise)

    pending: list[asyncio.Future] = []
    hass.async_create_background_task = lambda coro, name=None, **_kw: pending.append(asyncio.ensure_future(coro))

    websocket_api.require_admin(handler)(hass, connection, msg)
    for task in pending:
        await task

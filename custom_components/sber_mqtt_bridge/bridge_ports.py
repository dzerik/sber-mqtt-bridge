"""Narrow ports (interfaces) the bridge hands to its collaborators.

Historically every collaborator of :class:`~.sber_bridge.SberBridge`
received the *whole* bridge and read its private attributes — roughly a
hundred call sites against ~25 private fields.  That made the bridge a
de-facto friend class of four modules and froze the internal layout.

This module holds the small, explicitly-typed contracts that replace
that back-reference.  Collaborators depend on these ports (plus plain
callables), never on ``SberBridge`` itself, so the bridge stays free to
reshape its internals as long as it keeps supplying the ports.

Only structural typing is used: :class:`~.sber_bridge.BridgeStats`
satisfies :class:`StatsPort` without importing anything from here, which
keeps the dependency graph acyclic.
"""

from __future__ import annotations

from typing import Protocol


class StatsPort(Protocol):
    """Mutable counter bag a collaborator is allowed to update.

    Structural subset of :class:`~.sber_bridge.BridgeStats` limited to
    the fields the publisher and the command dispatcher actually touch.
    Deliberately *not* a read-only view: bumping a counter is the whole
    point, and hiding it behind methods would only add indirection.
    """

    messages_sent: int
    """Total MQTT messages published to Sber."""

    publish_errors: int
    """Total failed publish attempts."""

    commands_received: int
    """Total Sber commands processed."""

    status_requests: int
    """Total status requests received from Sber."""

    config_requests: int
    """Total config requests received from Sber."""

    errors_from_sber: int
    """Total error messages received from Sber."""

    last_error_detail: str
    """Human-readable detail of the last error message from Sber cloud."""

    validation_failures: list[str]
    """Entity IDs excluded from the last config publish by validation."""

    acknowledged_entities: set[str]
    """Entity IDs Sber has acknowledged."""

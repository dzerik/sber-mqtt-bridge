"""SSL helpers shared by the transport layer and the config flow.

Kept free of Home Assistant / UI imports so that the MQTT transport
(:mod:`mqtt_client_service`) does not depend on the presentation layer
(:mod:`config_flow`).
"""

from __future__ import annotations

import logging
import socket
import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization

from .const import CONF_SBER_TRUSTED_CERTIFICATE, CONF_SBER_VERIFY_SSL

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ServerCertificate:
    """Public information and PEM data for a broker leaf certificate."""

    pem: str
    fingerprint: str
    subject: str
    issuer: str
    not_before: str
    not_after: str
    self_signed: bool
    valid_now: bool
    hostname_matches: bool

    def as_dict(self, *, include_pem: bool = False) -> dict[str, Any]:
        """Return a JSON-safe representation for the HA WebSocket API."""
        result: dict[str, Any] = {
            "fingerprint": self.fingerprint,
            "subject": self.subject,
            "issuer": self.issuer,
            "not_before": self.not_before,
            "not_after": self.not_after,
            "self_signed": self.self_signed,
            "valid_now": self.valid_now,
            "hostname_matches": self.hostname_matches,
        }
        if include_pem:
            result["pem"] = self.pem
        return result


def _name_text(name: x509.Name) -> str:
    """Format a certificate name without exposing cryptography objects."""
    return ", ".join(f"{attribute.oid._name or attribute.oid.dotted_string}={attribute.value}" for attribute in name)


def _hostname_matches(certificate: x509.Certificate, host: str) -> bool:
    """Match the broker hostname against DNS SANs, including one-label wildcards."""
    try:
        names = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(
            x509.DNSName
        )
    except x509.ExtensionNotFound:
        names = []
    host = host.rstrip(".").lower()
    for name in names:
        name = name.rstrip(".").lower()
        if name.startswith("*."):
            suffix = name[1:]
            if host.endswith(suffix) and host.count(".") == suffix.count("."):
                return True
        elif name == host:
            return True
    return False


def inspect_server_certificate(host: str, port: int, timeout: float = 10.0) -> ServerCertificate:
    """Fetch a broker certificate without trusting it, for explicit review.

    This function is intentionally diagnostic only.  Its result must never
    be persisted automatically: the caller must display the fingerprint and
    require an explicit user action before pinning it.
    """
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=timeout) as raw_socket, context.wrap_socket(
        raw_socket, server_hostname=host
    ) as tls_socket:
        der = tls_socket.getpeercert(binary_form=True)
    if not der:
        raise ValueError("broker did not provide a certificate")
    certificate = x509.load_der_x509_certificate(der)
    pem = certificate.public_bytes(serialization.Encoding.PEM).decode()
    fingerprint = certificate.fingerprint(hashes.SHA256())
    not_before = certificate.not_valid_before_utc.astimezone(UTC).isoformat()
    not_after = certificate.not_valid_after_utc.astimezone(UTC).isoformat()
    now = datetime.now(UTC)
    return ServerCertificate(
        pem=pem,
        fingerprint=":".join(f"{byte:02X}" for byte in fingerprint),
        subject=_name_text(certificate.subject),
        issuer=_name_text(certificate.issuer),
        not_before=not_before,
        not_after=not_after,
        self_signed=certificate.subject == certificate.issuer,
        valid_now=certificate.not_valid_before_utc <= now <= certificate.not_valid_after_utc,
        hostname_matches=_hostname_matches(certificate, host),
    )


def create_ssl_context(verify: bool = True, trusted_certificate: str | None = None) -> ssl.SSLContext:
    """Create an SSL context for the Sber MQTT broker connection.

    Note:
        This performs blocking I/O (loads system CA certificates) and must
        be called via ``hass.async_add_executor_job`` from the event loop.

    Args:
        verify: If True, verify server certificate (recommended).
                If False, skip verification (for brokers with custom/self-signed CA).

    Returns:
        Configured SSL context.
    """
    ssl_context = ssl.create_default_context()
    if trusted_certificate and verify:
        # The user explicitly pinned this certificate.  Keep hostname
        # verification enabled; the PEM is a trust anchor only for this
        # broker and is never accepted implicitly.
        ssl_context.load_verify_locations(cadata=trusted_certificate)
    if not verify:
        _LOGGER.warning(
            "SSL verification DISABLED for Sber broker — "
            "connection is vulnerable to MITM attacks. "
            "Only use this with a trusted private / self-signed broker."
        )
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
    return ssl_context


def entry_verify_ssl(data: Mapping[str, Any], options: Mapping[str, Any]) -> bool:
    """Return the effective "Verify SSL certificate" setting of a config entry.

    The setup form stores the value in the entry data; the panel stores later
    changes in the entry options, which therefore take precedence. Every
    connection to the broker (the running bridge and reauthentication) must
    use this one rule, otherwise a broker with its own certificate accepts
    one connection and rejects the other.

    Args:
        data: The config entry data.
        options: The config entry options.

    Returns:
        True when the broker certificate must be verified.
    """
    return bool(options.get(CONF_SBER_VERIFY_SSL, data.get(CONF_SBER_VERIFY_SSL, True)))


def entry_trusted_certificate(data: Mapping[str, Any], options: Mapping[str, Any]) -> str | None:
    """Return the manually approved certificate PEM, if one is configured."""
    value = options.get(CONF_SBER_TRUSTED_CERTIFICATE, data.get(CONF_SBER_TRUSTED_CERTIFICATE))
    return value if isinstance(value, str) and value.strip() else None

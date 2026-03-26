"""
Cerver-owned transport for private local compute.

This package is responsible for opening and maintaining the outbound
connection from a local runtime to Cerver, then forwarding compute
requests to the local server.
"""

from .client import CerverConnectTransport

__all__ = ["CerverConnectTransport"]

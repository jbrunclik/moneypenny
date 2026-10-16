"""One TLS context for the app's short-lived httpx clients.

Every httpx client builds its own SSLContext, loading a fresh copy of the CA
bundle (~0.8 MB of native memory). After a request the client sits in a
reference cycle, so that memory waited for a full garbage collection, which
busy workers almost never ran: Oct 16 2026, research bursts (a client per page
fetch and per search call) raised a worker's floor by 30-90 MB. An SSLContext
is safe to share between threads.
"""

import ssl
from functools import cache

import httpx


@cache
def shared_ssl_context() -> ssl.SSLContext:
    """httpx's default verifying context, built once per process."""
    return httpx.create_ssl_context()

"""Queued and cached local chat completions."""

from .proxy import Client, ProxyError

__all__ = ["Client", "ProxyError"]

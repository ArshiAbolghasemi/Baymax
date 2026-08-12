"""Clients for the external services Baymax depends on.

Import submodules directly (``baymax.clients.embedding``). Kept free of
re-exports so ``baymax.config`` can import ``baymax.clients.config`` without
dragging in the runtime clients — and the logger they need.
"""

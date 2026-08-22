"""Clients for the external services Baymax depends on.

Import submodules directly (``hiro.clients.embedding``). Kept free of
re-exports so ``hiro.config`` can import ``hiro.clients.config`` without
dragging in the runtime clients — and the logger they need.
"""

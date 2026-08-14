"""Clients for the external services Baymax depends on.

Import submodules directly (``clients.embedding``). Kept free of
re-exports so ``config`` can import ``clients.config`` without
dragging in the runtime clients — and the logger they need.
"""

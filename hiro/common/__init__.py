"""Utilities shared by every package: logging and environment access.

Import submodules directly (``common.logging``). This package exports
nothing on purpose — ``config`` imports ``common.env`` while
composing itself, so any re-export here would close an import cycle.
"""

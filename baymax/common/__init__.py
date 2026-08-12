"""Utilities shared by every package: logging and environment access.

Import submodules directly (``baymax.common.logging``). This package exports
nothing on purpose — ``baymax.config`` imports ``baymax.common.env`` while
composing itself, so any re-export here would close an import cycle.
"""

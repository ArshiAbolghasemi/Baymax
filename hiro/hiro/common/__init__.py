"""Utilities shared by every package: logging and environment access.

Import submodules directly (``hiro.common.logging``). This package exports
nothing on purpose — ``hiro.config`` imports ``hiro.common.env`` while
composing itself, so any re-export here would close an import cycle.
"""

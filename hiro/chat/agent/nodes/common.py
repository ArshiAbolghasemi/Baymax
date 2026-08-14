"""Shared helpers for chat workflow nodes."""


def render(template: str, setting: str, **values: object) -> str:
    """Format a configurable template, naming the setting if malformed."""
    try:
        return template.format(**values)
    except (KeyError, IndexError) as exc:
        msg = f"{setting} has an unknown placeholder {exc}; expected {sorted(values)}"
        raise ValueError(msg) from exc

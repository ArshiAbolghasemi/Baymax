"""Terminal presentation.

All Rich usage lives here so the client and the loop stay free of formatting.
"""

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

from rich.box import ROUNDED
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from cli.config import Settings

ACCENT = "bright_cyan"
MUTED = "grey62"

try:
    import readline  # noqa: F401
except ImportError:  # pragma: no cover - Windows without pyreadline
    HAS_READLINE = False
else:
    HAS_READLINE = True

console = Console()


@dataclass
class ReplyStats:
    """Timings worth seeing while tuning prompts and endpoints."""

    text: str
    first_token_s: float | None
    total_s: float

    @property
    def summary(self) -> str:
        first = f"{self.first_token_s * 1000:.0f}ms" if self.first_token_s is not None else "—"
        return f"{len(self.text)} chars · first token {first} · total {self.total_s:.1f}s"


def banner(settings: Settings) -> None:
    body = Table.grid(padding=(0, 2))
    body.add_column(style=MUTED, justify="right")
    body.add_column()
    body.add_row("endpoint", settings.base_url)
    body.add_row("model", f"[{ACCENT}]{settings.model}[/{ACCENT}]")
    body.add_row("session", str(settings.session_uid))

    console.print(
        Panel(
            Group(
                Text("Baymax", style=f"bold {ACCENT}"),
                Text("your personal healthcare companion", style=MUTED),
                Text(""),
                body,
            ),
            box=ROUNDED,
            border_style=ACCENT,
            padding=(1, 2),
        )
    )
    console.print(f"[{MUTED}]/help for commands · ctrl-d to leave[/{MUTED}]\n")


def help_panel() -> None:
    table = Table(box=ROUNDED, border_style=MUTED, show_header=False, padding=(0, 2))
    table.add_column(style=ACCENT, no_wrap=True)
    table.add_column(style="white")
    table.add_row("/new", "start a fresh conversation (new session, cleared history)")
    table.add_row("/clear", "clear the screen")
    table.add_row("/models", "list the models the endpoint advertises")
    table.add_row("/session", "show the current session uid")
    table.add_row("/raw", "toggle markdown rendering off and on")
    table.add_row("/help", "show this")
    table.add_row("/quit", "leave (ctrl-d does the same)")
    console.print(table)


def info(message: str) -> None:
    console.print(f"[{MUTED}]{message}[/{MUTED}]")


def error(message: str) -> None:
    console.print(f"[bold red]✗[/bold red] [red]{message}[/red]")


def prompt_text() -> str:
    """The input prompt.

    Colour codes are wrapped in \\001/\\002 only when readline is present: those
    markers tell it which bytes are non-printing, and without readline they are
    written to the terminal literally.
    """
    if HAS_READLINE:
        return "\001\033[1;36m\002you ›\001\033[0m\002 "
    return "\033[1;36myou ›\033[0m "


async def stream_reply(chunks: AsyncIterator[str], *, markdown: bool) -> ReplyStats:
    """Render the reply as it arrives, and only the reply.

    A spinner covers the wait for the first token — which includes the guardrail
    call and retrieval, so it is never instant — then the text is re-rendered in
    place as each chunk lands.
    """
    parts: list[str] = []
    started = time.perf_counter()
    first_token_s: float | None = None

    console.print(Text("baymax ›", style=f"bold {ACCENT}"))

    status = console.status(f"[{MUTED}]thinking…[/{MUTED}]", spinner="dots")
    status.start()
    live: Live | None = None

    try:
        async for chunk in chunks:
            if live is None:
                first_token_s = time.perf_counter() - started
                status.stop()
                live = Live(console=console, refresh_per_second=12, vertical_overflow="visible")
                live.start()

            parts.append(chunk)
            body = "".join(parts)
            live.update(Markdown(body) if markdown else Text(body))
    finally:
        if live is not None:
            live.stop()
            # Live leaves the cursor at the end of its last frame; without this
            # the stats line lands on top of the final line of the reply.
            console.print()
        else:
            status.stop()

    text = "".join(parts)
    stats = ReplyStats(
        text=text, first_token_s=first_token_s, total_s=time.perf_counter() - started
    )

    if not text:
        error("the endpoint returned no content")
    else:
        console.print(f"[{MUTED}]{stats.summary}[/{MUTED}]\n")

    return stats

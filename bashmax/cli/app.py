"""The interactive loop."""

import argparse
import asyncio
import uuid

from cli import render
from cli.client import ChatClient, ChatError
from cli.config import DEFAULT_BASE_URL, DEFAULT_MODEL, Settings


class Conversation:
    """Client-side transcript.

    The endpoint is stateless per request in the OpenAI sense, so the whole
    transcript is replayed each turn; the server still persists it against
    ``session_uid`` for its own history and audit.
    """

    def __init__(self) -> None:
        self._messages: list[dict[str, str]] = []

    @property
    def messages(self) -> list[dict[str, str]]:
        return list(self._messages)

    def add_user(self, content: str) -> None:
        self._messages.append({"role": "user", "content": content})

    def add_assistant(self, content: str) -> None:
        self._messages.append({"role": "assistant", "content": content})

    def drop_last_user(self) -> None:
        """Undo the pending turn so a failure is not replayed as context."""
        if self._messages and self._messages[-1]["role"] == "user":
            self._messages.pop()

    def reset(self) -> None:
        self._messages.clear()


def parse_args(argv: list[str] | None = None) -> Settings:
    parser = argparse.ArgumentParser(
        prog="cli",
        description="Chat with the Baymax medical agent.",
    )
    parser.add_argument("--url", default=None, help=f"API base url (default {DEFAULT_BASE_URL})")
    parser.add_argument("--model", default=None, help=f"model name (default {DEFAULT_MODEL})")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--session", type=uuid.UUID, default=None, help="resume a session uid")
    parser.add_argument("--user", default=None, help="user identifier sent with each request")
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument(
        "--raw", action="store_true", help="print replies verbatim instead of rendering markdown"
    )
    args = parser.parse_args(argv)

    settings = Settings()
    if args.url:
        settings.base_url = args.url
    if args.model:
        settings.model = args.model
    if args.api_key:
        settings.api_key = args.api_key
    if args.session:
        settings.session_uid = args.session
    if args.user:
        settings.user = args.user
    if args.timeout:
        settings.timeout = args.timeout
    settings.markdown = not args.raw
    return settings


async def _handle_command(
    command: str, settings: Settings, conversation: Conversation, client: ChatClient
) -> bool:
    """Run a slash command. Returns False when the user asked to leave."""
    name = command.split()[0].lower()

    if name in {"/quit", "/exit", "/q"}:
        return False
    if name == "/help":
        render.help_panel()
    elif name == "/new":
        conversation.reset()
        settings.session_uid = uuid.uuid4()
        render.info(f"new session {settings.session_uid}")
    elif name == "/clear":
        render.console.clear()
    elif name == "/session":
        render.info(f"session {settings.session_uid}")
    elif name == "/raw":
        settings.markdown = not settings.markdown
        render.info(f"markdown {'on' if settings.markdown else 'off'}")
    elif name == "/models":
        try:
            models = await client.list_models()
        except ChatError as exc:
            render.error(str(exc))
        else:
            render.info(", ".join(models) or "the endpoint advertises no models")
    else:
        render.error(f"unknown command {name} — try /help")
    return True


async def run(settings: Settings) -> int:
    conversation = Conversation()
    client = ChatClient(settings)
    render.banner(settings)

    try:
        while True:
            try:
                # input() blocks, so keep it off the event loop.
                line = (await asyncio.to_thread(input, render.prompt_text())).strip()
            except EOFError, KeyboardInterrupt:
                render.console.print()
                render.info("bye")
                return 0

            if not line:
                continue
            if line.startswith("/"):
                if not await _handle_command(line, settings, conversation, client):
                    render.info("bye")
                    return 0
                continue

            render.echo_user(line)
            conversation.add_user(line)
            try:
                stats = await render.stream_reply(
                    client.stream(conversation.messages), markdown=settings.markdown
                )
            except ChatError as exc:
                render.error(str(exc))
                conversation.drop_last_user()
                continue
            except KeyboardInterrupt:
                render.console.print()
                render.info("interrupted — the server may still finish and store this turn")
                conversation.drop_last_user()
                continue

            if stats.text:
                conversation.add_assistant(stats.text)
            else:
                conversation.drop_last_user()
    finally:
        await client.aclose()


def main(argv: list[str] | None = None) -> int:
    settings = parse_args(argv)
    try:
        return asyncio.run(run(settings))
    except KeyboardInterrupt:
        return 130

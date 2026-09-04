"""Chat domain configuration.

No prompt or user-visible text lives here — all of it is versioned in Phoenix
and fetched by :mod:`hiro.chat.prompts`. What remains is the retrieval and
identity configuration the workflow needs.
"""

import uuid

from dynaconf import Dynaconf

from hiro.common.env import dynaconf_kwargs


class ChatConfig(Dynaconf):
    """How the assistant behaves in a conversation."""

    def __init__(self) -> None:
        super().__init__(**dynaconf_kwargs())

    # --- OpenAI-compatible API -------------------------------------------

    @property
    def agent_model_name(self) -> str:
        """Model id advertised by ``GET /v1/models``."""
        return str(self.get("CHAT_AGENT_MODEL_NAME", "baymax"))

    @property
    def session_namespace(self) -> uuid.UUID:
        """Namespace used to derive stable user and conversation UUIDs."""
        return uuid.UUID(
            str(
                self.get(
                    "CHAT_SESSION_NAMESPACE",
                    "e4c72588-f732-4bc8-8a20-0a73ae40bc5e",
                )
            )
        )

    # --- retrieval --------------------------------------------------------

    @property
    def retrieval_top_k(self) -> int:
        """Knowledge base entries to retrieve for a question."""
        return int(self.get("CHAT_RETRIEVAL_TOP_K", 5))

    @property
    def history_turns(self) -> int:
        """Earlier user questions to include as context."""
        return int(self.get("CHAT_HISTORY_TURNS", 5))

    # --- prompts ----------------------------------------------------------
    #
    # Which Phoenix prompt each step fetches. The text itself is never here —
    # see hiro/chat/prompts.py. Renaming a prompt in Phoenix means changing the
    # matching variable, and reseeding with scripts/seed_prompts.py.

    @property
    def prompt_answer(self) -> str:
        """Persona and answering rules. Variables: instructions, documents, history, question."""
        return str(self.get("CHAT_PROMPT_ANSWER", "hiro-answer"))

    @property
    def prompt_answer_tag(self) -> str:
        return str(self.get("CHAT_PROMPT_ANSWER_TAG", ""))

    @property
    def prompt_guardrail(self) -> str:
        """Medical-topic classifier. Variable: question. Must answer a single 1 or 0."""
        return str(self.get("CHAT_PROMPT_GUARDRAIL", "hiro-guardrail"))

    @property
    def prompt_guardrail_tag(self) -> str:
        return str(self.get("CHAT_PROMPT_GUARDRAIL_TAG", ""))

    @property
    def prompt_blocked(self) -> str:
        """Sent verbatim when the guardrail rejects a question. No variables."""
        return str(self.get("CHAT_PROMPT_BLOCKED", "hiro-blocked"))

    @property
    def prompt_blocked_tag(self) -> str:
        return str(self.get("CHAT_PROMPT_BLOCKED_TAG", ""))

    @property
    def prompt_no_instructions(self) -> str:
        """Stands in for the instruction block when nothing matched. No variables."""
        return str(self.get("CHAT_PROMPT_NO_INSTRUCTIONS", "hiro-no-instructions"))

    @property
    def prompt_no_instructions_tag(self) -> str:
        return str(self.get("CHAT_PROMPT_NO_INSTRUCTIONS_TAG", ""))

    @property
    def prompt_no_documents(self) -> str:
        """Stands in for the document block when retrieval found nothing. No variables."""
        return str(self.get("CHAT_PROMPT_NO_DOCUMENTS", "hiro-no-documents"))

    @property
    def prompt_no_documents_tag(self) -> str:
        return str(self.get("CHAT_PROMPT_NO_DOCUMENTS_TAG", ""))

    @property
    def prompt_no_history(self) -> str:
        """Stands in for the history block on the first turn. No variables."""
        return str(self.get("CHAT_PROMPT_NO_HISTORY", "hiro-no-history"))

    @property
    def prompt_no_history_tag(self) -> str:
        return str(self.get("CHAT_PROMPT_NO_HISTORY_TAG", ""))

    @property
    def prompt_probe(self) -> str:
        """A bare question, for driving the agent from the Phoenix playground.

        Never fetched by the workflow — the agent supplies its own prompt. It is
        seeded so that running something in the playground sends a question, not
        a rendered prompt that the agent would then wrap a second time.
        """
        return str(self.get("CHAT_PROMPT_PROBE", "hiro-probe"))

    @property
    def prompt_probe_tag(self) -> str:
        return str(self.get("CHAT_PROMPT_PROBE_TAG", ""))

    def prompt_tag(self, identifier: str) -> str:
        """Return the independently configured version tag for a prompt."""
        return {
            self.prompt_answer: self.prompt_answer_tag,
            self.prompt_guardrail: self.prompt_guardrail_tag,
            self.prompt_blocked: self.prompt_blocked_tag,
            self.prompt_no_instructions: self.prompt_no_instructions_tag,
            self.prompt_no_documents: self.prompt_no_documents_tag,
            self.prompt_no_history: self.prompt_no_history_tag,
            self.prompt_probe: self.prompt_probe_tag,
        }.get(identifier, "")

    # --- instructions -----------------------------------------------------

    @property
    def instruction_collection(self) -> str:
        """Qdrant collection holding the operator's answering instructions.

        Written outside this service; hiro only reads it, and it must use the
        same embedding model and width as the knowledge base.
        """
        return str(self.get("CHAT_INSTRUCTION_COLLECTION", "hiro_instructions"))

    @property
    def instruction_top_k(self) -> int:
        """Instructions to retrieve for a question."""
        return int(self.get("CHAT_INSTRUCTION_TOP_K", 5))

    @property
    def instruction_payload_field(self) -> str:
        """Payload key the instruction text is stored under."""
        return str(self.get("CHAT_INSTRUCTION_PAYLOAD_FIELD", "instruction"))


class McpConfig(Dynaconf):
    """Where the dobby MCP server serving the external medical tools lives."""

    def __init__(self) -> None:
        super().__init__(**dynaconf_kwargs())

    @property
    def url(self) -> str:
        """Streamable HTTP endpoint, including the path."""
        return str(self.get("MCP_URL", "http://localhost:8090/mcp"))

    @property
    def timeout(self) -> float:
        """Seconds for a request to the server, tool call included."""
        return float(self.get("MCP_TIMEOUT", 30))

    @property
    def read_timeout(self) -> float:
        """Seconds to wait for the next event on the response stream."""
        return float(self.get("MCP_READ_TIMEOUT", 60))

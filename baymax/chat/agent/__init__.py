"""The agentic workflow behind a chat reply.

    guardrail ──blocked──> constant refusal
              └─allowed──> retrieve_documents ┐
                           retrieve_history   ┘──> answer

The two retrieval steps run concurrently, because neither depends on the other
and both must finish before the prompt can be assembled.

Import ``baymax.chat.agent.graph`` directly; this package exports nothing so
that importing the state or prompts never builds the graph.
"""

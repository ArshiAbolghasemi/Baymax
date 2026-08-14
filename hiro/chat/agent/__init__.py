"""The agentic workflow behind a chat reply.

    guardrail ──blocked──> constant refusal
              └─allowed──> retrieve_documents ┐
                           retrieve_history   ┘──> answer ⇄ external tools

The two internal retrieval steps run concurrently. The answer model can then
select any external medical tool and iterate until it has enough information.

Import ``chat.agent.graph`` directly; this package exports nothing so
that importing the state or prompts never builds the graph.
"""

"""Streaming chat: sessions, message history, and token streaming over WebSocket.

Layering, outermost first: ``router`` -> ``service`` -> ``repository`` ->
``models``, with ``connections`` holding the open sockets and ``llm`` talking to
the model.

Deliberately empty of imports, like the other packages here: ``baymax.config``
imports ``baymax.chat.config`` while composing itself.
"""

"""OpenAPI customisation.

OpenAPI 3.1 has no way to describe a WebSocket, and FastAPI therefore leaves
``@router.websocket`` routes out of the schema entirely — so the one endpoint
that carries every assistant reply would be invisible in Swagger UI. We document
it by hand: the handshake as a GET returning 101, and the frame shapes as
components so a reader can see exactly what arrives on the socket.
"""

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from baymax.chat.schemas import DoneFrame, ErrorFrame, TokenFrame

WEBSOCKET_PATH = "/ws"

WEBSOCKET_DESCRIPTION = """\
**This is a WebSocket, not a callable HTTP endpoint** — "Try it out" cannot
open it. Connect with `ws://<host>/ws?user_uid=<uuid>`.

The channel is **receive-only**: the server pushes assistant replies down it and
ignores anything the client sends. Chat messages are sent with
`POST /sessions/{session_uid}/messages`, which returns `202` and streams the
reply here.

The socket must already be open when that POST is made, otherwise it fails with
`409 no active websocket connection`.

Every frame carries `session_uid`, because one user has one socket that may be
receiving streams for several sessions at once. Frames arrive in this order:

1. `token` — one chunk of the reply. Concatenate `data` across frames.
2. `done` — the reply is complete and has been persisted.

`error` replaces `done` if generation fails part-way; whatever text was produced
before the failure is still stored.

```json
{"session_uid": "3f2a9c14-...", "type": "token", "data": "A fever "}
{"session_uid": "3f2a9c14-...", "type": "token", "data": "is a rise..."}
{"session_uid": "3f2a9c14-...", "type": "done"}
```
"""


def _websocket_path_item() -> dict[str, Any]:
    return {
        "get": {
            "tags": ["chat"],
            "summary": "WebSocket: stream of assistant replies (receive-only)",
            "description": WEBSOCKET_DESCRIPTION,
            "operationId": "chat_websocket",
            "parameters": [
                {
                    "name": "user_uid",
                    "in": "query",
                    "required": True,
                    "description": "Owner of this socket. Replies for any of "
                    "this user's sessions arrive here.",
                    "schema": {"type": "string", "format": "uuid"},
                }
            ],
            "responses": {
                "101": {
                    "description": "Switching Protocols — the socket is open and "
                    "registered against user_uid. Frames follow the schemas "
                    "below.",
                    "content": {
                        "application/json": {
                            "schema": {
                                "oneOf": [
                                    {"$ref": "#/components/schemas/TokenFrame"},
                                    {"$ref": "#/components/schemas/DoneFrame"},
                                    {"$ref": "#/components/schemas/ErrorFrame"},
                                ]
                            }
                        }
                    },
                },
                "403": {"description": "Rejected before the upgrade completed."},
            },
        }
    }


def build_openapi(app: FastAPI) -> dict[str, Any]:
    """Generate the schema, then add what FastAPI cannot describe."""
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
    )

    schema.setdefault("paths", {})[WEBSOCKET_PATH] = _websocket_path_item()

    # The frame models are never used as a request or response body, so nothing
    # else pulls them into components.
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    for model in (TokenFrame, DoneFrame, ErrorFrame):
        components[model.__name__] = model.model_json_schema(
            ref_template="#/components/schemas/{model}"
        )

    app.openapi_schema = schema
    return schema

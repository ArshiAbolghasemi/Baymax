"""Baymax medical knowledge base, agentic chat workflow, and HTTP API.

Deliberately empty of imports. Everything lives in a subpackage — ``hiro.api``
(HTTP), ``hiro.chat`` (agent), ``hiro.knowledge_base`` (documents and their
vector index), ``hiro.worker`` (Celery), ``hiro.db``, ``hiro.clients``,
``hiro.common`` — and ``hiro.config`` composes their configs into one object.
Import those directly; importing this package must stay free of side effects so
the Celery worker and Alembic can pull in one subpackage without the rest.

Not installed into site-packages (``package = false`` in pyproject.toml): the
project directory is on ``sys.path``, so ``hiro`` resolves from there.
"""

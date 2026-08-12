"""Background tasks.

Indexing runs here rather than in the request because embedding a batch of
pairs is slow and depends on vLLM being reachable — the API should not block
on either.
"""

import uuid

from celery import Task

from baymax.celery.app import celery_app
from baymax.clients.embedding import get_embedding_client
from baymax.common.logging import bind_correlation_id, get_logger, log_duration
from baymax.config import get_config
from baymax.db.session import session_scope
from baymax.knowledge_base import service
from baymax.knowledge_base.store import get_store

logger = get_logger(__name__)

_celery_config = get_config().celery


# Bound to celery_app rather than @shared_task: the API process imports this
# module only to call .delay(), and shared_task would resolve to Celery's
# default app (and its default AMQP broker) instead of our Redis one.
@celery_app.task(
    bind=True,
    name="baymax.knowledge_base.index_entry",
    autoretry_for=(Exception,),
    retry_backoff=_celery_config.task_retry_backoff,
    retry_backoff_max=_celery_config.task_retry_backoff_max,
    retry_jitter=True,
    max_retries=_celery_config.task_max_retries,
)
def index_knowledge_base_entry(
    self: Task, answer_uid: str, correlation_id: str | None = None
) -> dict[str, object]:
    """Embed an answer's pending question/answer pairs and upsert them to Qdrant.

    ``correlation_id`` is passed by the API so the task's log lines can be
    matched to the request that queued it.
    """
    with bind_correlation_id(correlation_id):
        attempt = self.request.retries + 1
        logger.info(
            "index task answer_uid=%s attempt=%d/%d",
            answer_uid,
            attempt,
            _celery_config.task_max_retries + 1,
        )

        vector_store = get_store()
        vector_store.ensure_collection()

        with (
            log_duration(logger, "index entry", answer_uid=answer_uid),
            session_scope() as session,
        ):
            indexed = service.index_entry(
                session,
                uuid.UUID(answer_uid),
                embedding_client=get_embedding_client(),
                vector_store=vector_store,
            )

        return {"answer_uid": answer_uid, "indexed_pairs": indexed}

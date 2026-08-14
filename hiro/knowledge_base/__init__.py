"""Knowledge base domain: answers, their questions, and their vector index.

Layering, outermost first: ``router`` -> ``service`` -> ``repository`` ->
``models``. ``tasks`` is a second entrypoint into ``service`` for work that
must not happen inside a request.

Deliberately empty of imports: the Celery worker loads ``tasks`` from here and
must not drag FastAPI (or a partially initialised router) in with it.
"""

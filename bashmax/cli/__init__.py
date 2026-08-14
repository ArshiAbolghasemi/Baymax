"""Terminal client for the Baymax chat API.

A pure client: it talks to ``/v1/chat/completions`` over HTTP and imports
nothing from :mod:`baymax`. That keeps it runnable against a remote deployment
without a database URL, a broker, or any other server-side configuration.

Run it with::

    uv run python -m cli
"""

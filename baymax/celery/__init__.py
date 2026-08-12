"""Celery infrastructure.

Deliberately free of imports: this package shadows the third-party ``celery``
name for anything doing a relative-looking import, and eagerly building the app
here would make ``baymax.celery.config`` expensive to import from the root
config. Import ``baymax.celery.app`` explicitly.
"""

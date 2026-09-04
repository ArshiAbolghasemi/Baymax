"""How every config class talks to the environment.

Configuration comes from the process environment only — there is no settings
file. ``.env`` is loaded for local development so a shell without exported vars
still works; in a container the environment is already populated and the file
is simply absent.

Env var names are unprefixed and flat (``DATABASE_URL``, ``QDRANT_URL``), which
is what a Kubernetes ConfigMap or a Compose ``environment:`` block produces
naturally.
"""

from pathlib import Path
from typing import Any

from dynaconf import Validator

#: hiro/common/env.py -> hiro/common -> hiro -> the project root holding .env.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"


def dynaconf_kwargs(validators: list[Validator] | None = None) -> dict[str, Any]:
    """Constructor arguments shared by every config class."""
    return {
        # False (not "") means: read env vars exactly as named, no prefix.
        "envvar_prefix": False,
        "load_dotenv": True,
        "dotenv_path": str(ENV_FILE),
        "environments": False,
        "settings_files": [],
        "validators": validators or [],
    }

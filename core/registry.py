from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Dict, Type
from .errors import ProviderNotFound

class Registry:
    """Discovers provider adapters and personalities at runtime."""

    def __init__(self):
        self._providers: Dict[str, ModuleType] = {}

    def load_providers(self, root: Path):
        for path in (root / "providers").glob("*.py"):
            if path.name in {"__init__.py", "base.py"}:
                continue
            mod = import_module(f"agent_shell.providers.{path.stem}")
            self._providers[path.stem] = mod.Provider  # type: ignore[attr-defined]

    def get_provider(self, name: str):
        try:
            return self._providers[name]()
        except KeyError as exc:  # noqa: EM101
            raise ProviderNotFound(name) from exc
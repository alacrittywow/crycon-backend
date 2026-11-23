"""One environment boundary, with process variables taking precedence over .env."""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from dotenv import dotenv_values


@dataclass(frozen=True)
class Settings:
    # Never include credentials in repr or conversion errors.
    values: Mapping[str, str] = field(repr=False)

    def text(self, name: str, default: str = "") -> str:
        return self.values.get(name, default).strip()

    def require(self, name: str) -> str:
        value = self.text(name)
        if not value:
            raise RuntimeError(f"{name} is required; set it in the environment or .env")
        return value

    def integer(self, name: str, default: int) -> int:
        try:
            return int(self.text(name) or default)
        except ValueError:
            raise ValueError(f"{name} must be an integer") from None

    def number(self, name: str, default: float) -> float:
        try:
            return float(self.text(name) or default)
        except ValueError:
            raise ValueError(f"{name} must be a number") from None

    def list(self, name: str, default: list[str]) -> list[str]:
        items = [item.strip() for item in re.split(r"[|,]", self.text(name)) if item.strip()]
        return items or list(default)


def load_settings(
    env_file: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Settings:
    """Read a snapshot without modifying os.environ or requiring credentials.

    Default: repository .env, independent of the CLI working directory.
    CRYCON_ENV_FILE overrides it; an empty string disables file loading.
    Explicit environ makes tests independent of the developer's environment.
    Dotenv interpolation is disabled so credentials containing $ remain literal.
    """
    environment = dict(os.environ if environ is None else environ)
    if env_file is None:
        env_file = environment.get("CRYCON_ENV_FILE", str(Path(__file__).resolve().parents[2] / ".env"))
    file_values = dotenv_values(env_file, interpolate=False) if env_file else {}
    merged = {key: value for key, value in file_values.items() if value is not None}
    merged.update(environment)
    return Settings(MappingProxyType(merged))

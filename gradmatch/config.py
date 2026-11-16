"""Server-side configuration; secrets never enter exported settings or events."""

from dataclasses import dataclass, field
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import tomllib

from dotenv import dotenv_values

from gradmatch.storage import PROJECT_ROOT


class ConfigurationError(RuntimeError):
    """Safe to show without exposing file contents or secret values."""


@dataclass(frozen=True)
class ModelSettings:
    provider: str
    model: str
    enabled: bool
    api_key: str = field(repr=False)
    limits: dict = field(default_factory=dict)

    @property
    def ready(self):
        return self.enabled and self.provider == "openai" and bool(self.api_key)

    def public(self):
        return {"provider": self.provider, "model": self.model, "enabled": self.enabled,
                "key_configured": bool(self.api_key), "ready": self.ready,
                "config_hash": hashlib.sha256(json.dumps({"provider": self.provider, "model": self.model,
                    "limits": self.limits}, sort_keys=True).encode()).hexdigest()}


def load_settings(root: Path = PROJECT_ROOT) -> ModelSettings:
    # Local .env < Streamlit secrets < process environment. Do not modify os.environ.
    try:
        values = dict(dotenv_values(root / ".env"))
        secrets = root / ".streamlit" / "secrets.toml"
        if secrets.exists():
            values.update(tomllib.loads(secrets.read_text(encoding="utf-8")))
        limits = json.loads((root / "config" / "app.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise ConfigurationError("The server model configuration could not be read. Please ask the app owner to check the Secrets format.") from None
    values.update({key: os.environ[key] for key in
        ["MODEL_PROVIDER", "MODEL_NAME", "MODEL_API_KEY", "OPENAI_API_KEY", "MODEL_ENABLED"] if key in os.environ})
    return ModelSettings(provider=values.get("MODEL_PROVIDER") or "openai",
        model=values.get("MODEL_NAME") or "gpt-5.4-mini-2026-03-17",
        enabled=str(values.get("MODEL_ENABLED", "false")).lower() == "true",
        api_key=values.get("MODEL_API_KEY") or values.get("OPENAI_API_KEY") or "", limits=limits)


def estimate_cost(settings: ModelSettings, model: str, input_tokens, output_tokens, cached_tokens):
    price = settings.limits["pricing"]
    if model != price["model"] or any(value is None for value in [input_tokens, output_tokens, cached_tokens]):
        return None
    return ((Decimal(input_tokens - cached_tokens) * Decimal(price["input_usd_per_million"])
        + Decimal(cached_tokens) * Decimal(price["cached_input_usd_per_million"])
        + Decimal(output_tokens) * Decimal(price["output_usd_per_million"])) / Decimal(1000000))

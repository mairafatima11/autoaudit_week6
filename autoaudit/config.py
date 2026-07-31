from dataclasses import dataclass


@dataclass
class Config:
    app_name: str = "AutoAudit AI"
    version: str = "0.1.0"


def load_config() -> Config:
    """Return default project configuration."""
    return Config()
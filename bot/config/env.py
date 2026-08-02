from os import getenv


def required(name: str) -> str:
    value = getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def optional(name: str, default: str | None = None) -> str | None:
    value = getenv(name)
    return value if value else default


def optional_first(*names: str) -> str | None:
    for name in names:
        value = optional(name)
        if value is not None:
            return value
    return None

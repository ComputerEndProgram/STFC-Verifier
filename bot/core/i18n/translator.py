import json
from pathlib import Path

from bot.core.i18n.formatter import safe_format
from bot.core.i18n.locale import normalize_locale


class Translator:
    def __init__(self, default_language: str = "en") -> None:
        self.default_language = normalize_locale(default_language)
        self._cache: dict[str, dict[str, str]] = {}
        self._i18n_dir = Path(__file__).resolve().parents[2] / "i18n"

    def _load_language(self, language: str) -> dict[str, str]:
        normalized = normalize_locale(language)
        cached = self._cache.get(normalized)
        if cached is not None:
            return cached

        path = self._i18n_dir / f"{normalized}.json"
        if not path.exists():
            self._cache[normalized] = {}
            return {}

        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)

        if not isinstance(data, dict):
            raise TypeError(f"Translation file {path} must contain a JSON object")

        parsed = {str(key): str(value) for key, value in data.items()}
        self._cache[normalized] = parsed
        return parsed

    def t(self, language: str | None, key: str, **kwargs: object) -> str:
        requested = normalize_locale(language)
        requested_messages = self._load_language(requested)
        default_messages = self._load_language(self.default_language)

        template = requested_messages.get(key)
        if template is None:
            template = default_messages.get(key)
        if template is None:
            return key

        return safe_format(template, kwargs)

def normalize_locale(value: object) -> str:
    if not value:
        return "en"

    lowered = str(value).strip().lower().replace("_", "-")
    language = lowered.split("-", maxsplit=1)[0]

    aliases = {
        "nb": "no",
    }
    return aliases.get(language, language)

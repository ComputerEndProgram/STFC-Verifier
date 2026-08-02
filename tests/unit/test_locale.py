from bot.core.i18n.locale import normalize_locale


def test_normalize_locale_reduces_region_to_language() -> None:
    assert normalize_locale("en-US") == "en"
    assert normalize_locale("es-419") == "es"


def test_normalize_locale_aliases_nb_to_no() -> None:
    assert normalize_locale("nb") == "no"

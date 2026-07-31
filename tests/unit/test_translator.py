from bot.core.i18n.translator import Translator


def test_translator_interpolates_values() -> None:
    translator = Translator(default_language="en")
    message = translator.t(
        "en",
        "verification.support_ticket",
        support_channel_mention="<#123>",
    )
    assert message == "Open a support ticket in <#123>."


def test_translator_falls_back_to_english() -> None:
    translator = Translator(default_language="en")
    message = translator.t("nonexistent_lang", "verification.complete")
    assert message == "Verification complete."

from dataclasses import dataclass

from bot.bootstrap import restore_runtime_state
from bot.config.settings import Settings
from bot.core.bot_base import BaseBot
from bot.core.i18n.translator import Translator
from bot.core.sessions.store import SessionStore


@dataclass(slots=True)
class Application:
    settings: Settings
    translator: Translator
    session_store: SessionStore
    bot: BaseBot

    def run(self) -> None:
        restore_runtime_state(self.session_store)
        self.bot.run(self.settings.discord_token)


def build_app() -> Application:
    settings = Settings.from_env()
    translator = Translator(default_language=settings.default_language)
    session_store = SessionStore(settings.database_path)
    bot = BaseBot(settings)
    return Application(
        settings=settings,
        translator=translator,
        session_store=session_store,
        bot=bot,
    )

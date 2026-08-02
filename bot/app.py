from dataclasses import dataclass
from threading import Thread

from bot.config.settings import Settings
from bot.core.bot_base import BaseBot
from bot.core.i18n.translator import Translator


@dataclass(slots=True)
class Application:
    settings: Settings
    translator: Translator
    bot: BaseBot

    def run(self) -> None:
        self._start_admin_web()
        self.bot.run(self.settings.discord_token)

    @staticmethod
    def _start_admin_web() -> None:
        """Serve the admin web UI in a background thread.

        The admin web UI is the only way to configure a guild now, so it is
        started alongside the bot. Each runs in its own event loop/thread to
        avoid asyncio and signal-handler conflicts.
        """
        import logging
        import uvicorn
        from admin_web.config import AdminWebConfig

        log = logging.getLogger("veil_bot")

        def _serve() -> None:
            try:
                cfg = AdminWebConfig.from_env()
            except Exception as e:
                log.error(f"[WEB] Admin web UI could not start (missing configuration?): {e}")
                return
            uvicorn.run("admin_web.app:app", host=cfg.host, port=cfg.port, log_level="info")

        thread = Thread(target=_serve, name="admin-web", daemon=True)
        thread.start()


def build_app() -> Application:
    settings = Settings.from_env()
    translator = Translator(default_language=settings.default_language)
    bot = BaseBot(settings)
    return Application(
        settings=settings,
        translator=translator,
        bot=bot,
    )

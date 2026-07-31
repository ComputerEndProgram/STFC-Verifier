from dotenv import find_dotenv, load_dotenv

from bot.app import build_app

load_dotenv(find_dotenv(usecwd=True))


def run_bot() -> None:
    app = build_app()
    app.run()


def run_selected_profile() -> None:
    run_bot()


if __name__ == "__main__":
    run_bot()

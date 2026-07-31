from datetime import UTC, datetime, timedelta
from uuid import uuid4

from bot.config.settings import Settings
from bot.core.sessions.models import WizardSession
from bot.core.sessions.store import SessionStore
from bot.profiles.base import VerificationProfile


def create_session(
    session_store: SessionStore,
    profile: VerificationProfile,
    guild_id: int,
    user_id: int,
    language: str,
    session_ttl_hours: int = 168,
) -> WizardSession:
    steps = profile.build_steps()
    expires_at = datetime.now(UTC) + timedelta(hours=session_ttl_hours)
    session = WizardSession(
        session_id=str(uuid4()),
        user_id=user_id,
        guild_id=guild_id,
        profile=profile.name,
        language=language,
        current_step=steps[0],
        expires_at=expires_at,
    )
    session_store.save_session(session)
    return session


def advance_session(
    session_store: SessionStore,
    session: WizardSession,
    next_step: str,
    answers: dict[str, str],
) -> WizardSession:
    session.current_step = next_step
    session.answers.update(answers)
    session_store.save_session(session)
    return session

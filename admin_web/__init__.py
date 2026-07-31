"""FastAPI admin web UI for the Merged-Verifier bot.

Served as a separate process from the bot. Reads/writes the same SQLite
database as the bot (via bot.core.store.ProfileStore) and relies on the
store's mtime-based cache invalidation so config edits take effect on the
running bot without a restart.
"""

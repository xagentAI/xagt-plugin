"""Cloudflare entrypoint. Persistent state lives in session-scoped Durable Objects."""

from workers import WorkerEntrypoint, asgi

from app._worker_build import REVIEW_COMMIT, SOURCE_HASH
from app.adapters.nexus import DisabledNexus
from app.main import create_app
from app.workers_storage import DurableStore, SessionStore  # noqa: F401


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        if not hasattr(self, "_app"):
            self._app = create_app(
                store=DurableStore(self.env.SESSIONS, self.env.SESSION_SECRET),
                nexus=DisabledNexus(),
                settings={
                    "PUBLIC_ORIGIN": str(getattr(self.env, "PUBLIC_ORIGIN", "")),
                    "COOKIE_SECURE": str(getattr(self.env, "COOKIE_SECURE", "true")),
                    "REVIEW_COMMIT": REVIEW_COMMIT,
                },
                source_hash=SOURCE_HASH,
                assets=self.env.ASSETS,
            )
        return await asgi.fetch(self._app, request, self.env)

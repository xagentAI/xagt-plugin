"""Explicit test bindings for the same application factory used by the Worker."""

from pathlib import Path

from app.adapters.nexus import DisabledNexus
from app.main import create_app
from app.source_version import source_digest
from support.storage import SQLiteTestStore

SOURCE = Path(__file__).resolve().parents[2]


class FixtureAssets:
    def __init__(self):
        self.requests = []

    async def fetch(self, url):
        self.requests.append(url)
        name = url.rsplit("/", 1)[-1]
        payload = (SOURCE / "web" / name).read_bytes()

        class Asset:
            status = 200

            async def bytes(self):
                return payload

        return Asset()


def make_app(path=None, *, store=None, nexus=None, settings=None, source_hash=None, assets=None):
    return create_app(
        store=SQLiteTestStore(path) if store is None else store,
        nexus=DisabledNexus() if nexus is None else nexus,
        settings={} if settings is None else settings,
        source_hash=source_digest(SOURCE) if source_hash is None else source_hash,
        assets=FixtureAssets() if assets is None else assets,
    )

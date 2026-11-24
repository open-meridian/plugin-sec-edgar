"""SEC EDGAR's filings as an Open Meridian data plugin: each company's
filings, recorded as `Filing` rows under its filer (contract v28's filings
slice), in one dataset, `edgar_filings`.

It runs its data role class, `Lake` (feed.py's `Feed`, with its lifecycle
here), with `meridian.run` on the sidecar it is launched beside, declaring
its catalogue, its storage and its settings (declaration.py); `meridian.run`
delivers the settings, serves its two pages (page.py), hands it what the
lake wants of it, and sets the data role's figures on each heartbeat. It
reads the watchlist's companies at start and every few minutes, recording
each new filing (feed.py), at the pace its settings allow (limits.py). What
SEC answered is kept in the storage the deployment grants (raw.py), and
moved past its window as the settings say. It reads which of its datasets a
deployment admin has licensed, on start and every minute. It holds nothing
else: a restart reads EDGAR again, and the lake answers what it recorded
before unchanged.

While the User-Agent setting is missing or malformed it asks SEC nothing,
and its status and figures name the setting.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

import meridian

from .declaration import DECLARATION, PORT
from .edgar import api
from .feed import Feed
from .limits import Limiter
from .page import figures, hold, pages
from .raw import RawStore
from .settings import Config, config_from

log = logging.getLogger("sec_edgar")

#: How often the companies kept current are read, in seconds.
CHECK_SECONDS = 300
#: How often storage is tended past its window, in seconds: daily.
TEND_SECONDS = 86_400
#: How often the datasets' licences are read again.
LICENCES_SECONDS = 60


class Lake(Feed):
    """The data role's class with its lifecycle: `meridian.run` delivers each
    settings to `on_settings` -- the first before anything is heard -- and
    starts `run`, again after a backoff should it fail."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.config = Config()
        self.limiter = Limiter()
        self.wake = asyncio.Event()

    async def on_settings(self, delivered: Any) -> None:
        """Apply each delivery of the settings: the User-Agent, the pace, the
        watchlist, sample data on or off, and the answers' window, tended at
        once."""
        config = config_from(delivered.values)
        self.config = config
        self.limiter.set_rate(config.per_second)
        if config.user_agent_problem and not config.sample_data:
            log.warning("waiting: edgar_user_agent %s", config.user_agent_problem)
        self.use(
            api(config.sample_data, config.user_agent, self.limiter),
            config.watchlist,
            config.user_agent_problem,
        )
        self.wake.set()
        await self.raw.tend(self.plugin, config.window_days, config.past_window, self.now())

    async def on_start(self) -> None:
        """Its storage read once registered: on an instance run as shards or
        with a standby pod, the shard's own folder."""
        await super().on_start()
        self.raw.open()

    async def on_stop(self) -> None:
        """Its storage forgotten: registered again, it is read afresh."""
        self.raw.close()
        await super().on_stop()

    async def run(self) -> None:
        """The companies kept current read, storage tended, the licences
        read, and the feed delay reported."""
        await asyncio.gather(self._check(), self._tend(), self._licences(), self.latency.run())

    async def _check(self) -> None:
        while True:
            self.wake.clear()
            try:
                await self.check()
            except meridian.MeridianError as failed:
                self.status.error = f"the deployment refused a recording: {failed}"
                log.warning("this check stopped: %s", failed)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.wake.wait(), timeout=CHECK_SECONDS)

    async def _tend(self) -> None:
        while True:
            await asyncio.sleep(TEND_SECONDS)
            config = self.config
            await self.raw.tend(self.plugin, config.window_days, config.past_window, self.now())

    async def _licences(self) -> None:
        while True:
            try:
                await self.wants.read_licences()
            except meridian.MeridianError as failed:
                log.warning("the datasets' licences were not read this time: %s", failed)
            await asyncio.sleep(LICENCES_SECONDS)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    limiter = Limiter()
    lake = Lake(api(False, "", limiter), RawStore(), waiting="is not set")
    lake.limiter = limiter
    hold(lake)
    meridian.run(
        declaration=DECLARATION,
        roles=[lake],
        pages=pages,
        port=PORT,
        on_settings=lake.on_settings,
        figures=lambda: figures(lake.status, lake),
    )


if __name__ == "__main__":
    main()

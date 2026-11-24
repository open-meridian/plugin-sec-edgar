"""The pace: never above the setting or SEC's 10 a second, one request at a
time, and a pause after a 429 or a 403."""

from __future__ import annotations

import asyncio

from sec_edgar.limits import FIRST_PAUSE, LONGEST_PAUSE, Limiter, per_second, retry_after

SECOND = 1_000_000_000


class Clock:
    """A clock that moves only when the limiter sleeps."""

    def __init__(self) -> None:
        self.now = 0
        self.slept: list[float] = []

    def __call__(self) -> int:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += int(seconds * 1e9)


def most_in_any_second(times: list[int]) -> int:
    return max(sum(1 for t in times if start <= t < start + SECOND) for start in times)


async def _sent(limiter: Limiter, clock: Clock, n: int) -> list[int]:
    times = []
    for _ in range(n):
        await limiter.wait()
        times.append(clock.now)
    return times


async def test_never_above_the_set_rate() -> None:
    for rate in (1, 3, 5, 7, 10):
        clock = Clock()
        limiter = Limiter(rate, clock=clock, sleep=clock.sleep)
        times = await _sent(limiter, clock, 60)
        assert most_in_any_second(times) <= rate
        assert most_in_any_second(times) == rate, "and no slower than it needs to be"


async def test_never_above_secs_ten_whatever_the_setting() -> None:
    clock = Clock()
    limiter = Limiter(25, clock=clock, sleep=clock.sleep)
    assert limiter.rate == 10
    assert most_in_any_second(await _sent(limiter, clock, 100)) <= 10
    limiter.set_rate(0)
    assert limiter.rate == 1
    assert per_second(11) == 10 and per_second(-3) == 1


async def test_tasks_asking_at_once_share_the_pace() -> None:
    clock = Clock()
    limiter = Limiter(5, clock=clock, sleep=clock.sleep)
    times: list[int] = []

    async def ask() -> None:
        await limiter.wait()
        times.append(clock.now)

    await asyncio.gather(*(ask() for _ in range(30)))
    assert most_in_any_second(sorted(times)) <= 5


async def test_a_429_pauses_and_the_pause_doubles() -> None:
    clock = Clock()
    limiter = Limiter(5, clock=clock, sleep=clock.sleep)
    await limiter.wait()
    limiter.answered(429)
    refused_at = clock.now
    await limiter.wait()
    assert clock.now - refused_at >= FIRST_PAUSE * SECOND
    limiter.answered(429)
    second_at = clock.now
    await limiter.wait()
    assert clock.now - second_at >= 2 * FIRST_PAUSE * SECOND
    assert limiter.refused == 2
    # An answer ends the pauses; the next refusal starts again at the first.
    limiter.answered(200)
    limiter.answered(429)
    third_at = clock.now
    await limiter.wait()
    assert FIRST_PAUSE * SECOND <= clock.now - third_at < 2 * FIRST_PAUSE * SECOND


async def test_a_403_pauses_as_a_429_does_and_retry_after_is_kept() -> None:
    clock = Clock()
    limiter = Limiter(5, clock=clock, sleep=clock.sleep)
    limiter.answered(403)
    assert limiter.paused_until_ns == FIRST_PAUSE * SECOND
    limiter.answered(429, retry_after("120"))
    assert limiter.paused_until_ns == 120 * SECOND
    for _ in range(20):
        limiter.answered(403)
    assert limiter.paused_until_ns <= clock.now + LONGEST_PAUSE * SECOND
    assert retry_after("Wed, 21 Oct 2026 07:28:00 GMT") is None and retry_after(None) is None

from __future__ import annotations

import hashlib
import threading
import unittest

from apps.node.clink_node.miniapp.traffic import (
    IP_GENERAL,
    IP_SESSION_EXCHANGE,
    MESSAGE_SUBMIT,
    OPERATION_LINK,
    STOP,
    SUBJECT_GENERAL,
    MemoryMiniAppTrafficGuard,
    MiniAppTrafficPolicy,
    MiniAppTrafficUnavailable,
    RedisMiniAppTrafficGuard,
)


class _Clock:
    def __init__(self, value: float = 1_000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class _FakeRedis:
    def __init__(self) -> None:
        self.eval_results: list[object] = []
        self.set_results: list[object] = []
        self.eval_calls: list[tuple[str, int, tuple[object, ...]]] = []
        self.set_calls: list[tuple[str, str, bool, int]] = []
        self.error: Exception | None = None

    def eval(self, script: str, numkeys: int, *args: object) -> object:
        if self.error is not None:
            raise self.error
        self.eval_calls.append((script, numkeys, args))
        if self.eval_results:
            return self.eval_results.pop(0)
        return 1

    def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool,
        px: int,
    ) -> object:
        if self.error is not None:
            raise self.error
        self.set_calls.append((key, value, nx, px))
        if self.set_results:
            return self.set_results.pop(0)
        return True


class MiniAppTrafficPolicyTests(unittest.TestCase):
    def test_guards_are_exported_from_miniapp_package(self) -> None:
        from apps.node.clink_node.miniapp import (
            MemoryMiniAppTrafficGuard as ExportedMemoryGuard,
        )
        from apps.node.clink_node.miniapp import (
            MiniAppTrafficPolicy as ExportedPolicy,
        )
        from apps.node.clink_node.miniapp import (
            RedisMiniAppTrafficGuard as ExportedRedisGuard,
        )

        self.assertIs(ExportedMemoryGuard, MemoryMiniAppTrafficGuard)
        self.assertIs(ExportedPolicy, MiniAppTrafficPolicy)
        self.assertIs(ExportedRedisGuard, RedisMiniAppTrafficGuard)

    def test_defaults_are_the_fixed_safe_policy(self) -> None:
        policy = MiniAppTrafficPolicy()

        self.assertEqual(policy.limit_for(IP_GENERAL), 240)
        self.assertEqual(policy.limit_for(IP_SESSION_EXCHANGE), 10)
        self.assertEqual(policy.limit_for(SUBJECT_GENERAL), 120)
        self.assertEqual(policy.limit_for(MESSAGE_SUBMIT), 12)
        self.assertEqual(policy.limit_for(OPERATION_LINK), 12)
        self.assertEqual(policy.limit_for(STOP), 12)
        self.assertEqual(policy.window_seconds, 60)
        self.assertEqual(policy.sse_lease_ttl_seconds, 960)

    def test_all_limits_are_injectable_strict_positive_bounded_integers(self) -> None:
        policy = MiniAppTrafficPolicy(
            ip_general_limit=7,
            session_exchange_limit=2,
            subject_general_limit=6,
            message_submit_limit=3,
            operation_link_limit=4,
            stop_limit=5,
            window_seconds=30,
            sse_lease_ttl_seconds=1_200,
        )

        self.assertEqual(policy.limit_for(IP_GENERAL), 7)
        self.assertEqual(policy.limit_for(IP_SESSION_EXCHANGE), 2)
        self.assertEqual(policy.limit_for(SUBJECT_GENERAL), 6)
        self.assertEqual(policy.limit_for(MESSAGE_SUBMIT), 3)
        self.assertEqual(policy.limit_for(OPERATION_LINK), 4)
        self.assertEqual(policy.limit_for(STOP), 5)
        self.assertEqual(policy.window_seconds, 30)
        self.assertEqual(policy.sse_lease_ttl_seconds, 1_200)

        fields = (
            "ip_general_limit",
            "session_exchange_limit",
            "subject_general_limit",
            "message_submit_limit",
            "operation_link_limit",
            "stop_limit",
            "window_seconds",
        )
        for field in fields:
            for invalid in (0, -1, True, 1_000_001):
                with self.subTest(field=field, invalid=invalid):
                    with self.assertRaises(ValueError):
                        MiniAppTrafficPolicy(**{field: invalid})
        for invalid_ttl in (0, 899, True, 86_401):
            with self.subTest(invalid_ttl=invalid_ttl):
                with self.assertRaises(ValueError):
                    MiniAppTrafficPolicy(
                        sse_lease_ttl_seconds=invalid_ttl,
                    )


class MemoryMiniAppTrafficGuardTests(unittest.TestCase):
    def test_sliding_window_expires_using_monotonic_time(self) -> None:
        clock = _Clock()
        guard = MemoryMiniAppTrafficGuard(
            policy=MiniAppTrafficPolicy(ip_general_limit=2),
            monotonic=clock,
        )

        self.assertTrue(guard.consume(IP_GENERAL, "198.51.100.7"))
        self.assertTrue(guard.consume(IP_GENERAL, "198.51.100.7"))
        self.assertFalse(guard.consume(IP_GENERAL, "198.51.100.7"))
        clock.value += 59.999
        self.assertFalse(guard.consume(IP_GENERAL, "198.51.100.7"))
        clock.value += 0.001
        self.assertTrue(guard.consume(IP_GENERAL, "198.51.100.7"))

    def test_concurrent_requests_cannot_exceed_the_limit(self) -> None:
        workers = 32
        guard = MemoryMiniAppTrafficGuard(
            policy=MiniAppTrafficPolicy(message_submit_limit=1),
        )
        barrier = threading.Barrier(workers)
        decisions: list[bool] = []
        decisions_lock = threading.Lock()

        def consume() -> None:
            barrier.wait(timeout=3)
            decision = guard.consume(MESSAGE_SUBMIT, "telegram:101")
            with decisions_lock:
                decisions.append(decision)

        threads = [threading.Thread(target=consume) for _ in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(decisions.count(True), 1)
        self.assertEqual(decisions.count(False), workers - 1)

    def test_bounded_cleanup_reclaims_expired_rate_and_lease_scopes(self) -> None:
        clock = _Clock()
        guard = MemoryMiniAppTrafficGuard(
            policy=MiniAppTrafficPolicy(
                ip_general_limit=1,
                sse_lease_ttl_seconds=900,
            ),
            monotonic=clock,
            max_rate_scopes=2,
            max_sse_scopes=2,
            cleanup_batch_size=2,
        )
        self.assertTrue(guard.consume(IP_GENERAL, "198.51.100.1"))
        self.assertTrue(guard.consume(IP_GENERAL, "198.51.100.2"))
        self.assertIsNotNone(guard.acquire_sse("telegram:1"))
        self.assertIsNotNone(guard.acquire_sse("telegram:2"))

        clock.value += 901

        self.assertTrue(guard.consume(IP_GENERAL, "198.51.100.3"))
        self.assertIsNotNone(guard.acquire_sse("telegram:3"))

    def test_capacity_exhaustion_fails_closed_without_evicting_live_scope(self) -> None:
        guard = MemoryMiniAppTrafficGuard(
            policy=MiniAppTrafficPolicy(ip_general_limit=1),
            max_rate_scopes=1,
            max_sse_scopes=1,
            cleanup_batch_size=1,
        )
        self.assertTrue(guard.consume(IP_GENERAL, "198.51.100.1"))
        first_lease = guard.acquire_sse("telegram:1")
        self.assertIsNotNone(first_lease)

        with self.assertRaisesRegex(
            MiniAppTrafficUnavailable,
            "^miniapp_unavailable$",
        ):
            guard.consume(IP_GENERAL, "198.51.100.2")
        with self.assertRaisesRegex(
            MiniAppTrafficUnavailable,
            "^miniapp_unavailable$",
        ):
            guard.acquire_sse("telegram:2")

        self.assertFalse(guard.consume(IP_GENERAL, "198.51.100.1"))
        self.assertIsNone(guard.acquire_sse("telegram:1"))

    def test_sse_lease_requires_exact_token_and_recovers_after_ttl(self) -> None:
        clock = _Clock()
        guard = MemoryMiniAppTrafficGuard(monotonic=clock)

        first = guard.acquire_sse("telegram:101")
        self.assertIsInstance(first, str)
        assert first is not None
        self.assertIsNone(guard.acquire_sse("telegram:101"))
        self.assertFalse(guard.release_sse("telegram:101", "wrong-token"))
        self.assertIsNone(guard.acquire_sse("telegram:101"))
        self.assertTrue(guard.release_sse("telegram:101", first))

        second = guard.acquire_sse("telegram:101")
        self.assertIsNotNone(second)
        clock.value += 960
        third = guard.acquire_sse("telegram:101")
        self.assertIsNotNone(third)
        assert second is not None
        self.assertFalse(guard.release_sse("telegram:101", second))


class RedisMiniAppTrafficGuardTests(unittest.TestCase):
    def test_rate_limit_is_one_atomic_redis_time_script_with_hashed_key(self) -> None:
        client = _FakeRedis()
        client.eval_results = [1, 0]
        guard = RedisMiniAppTrafficGuard(client=client)
        scope = "203.0.113.8"

        self.assertTrue(guard.consume(IP_GENERAL, scope))
        self.assertFalse(guard.consume(IP_GENERAL, scope))

        self.assertEqual(len(client.eval_calls), 2)
        script, numkeys, args = client.eval_calls[0]
        self.assertEqual(numkeys, 1)
        key = args[0]
        self.assertIsInstance(key, str)
        assert isinstance(key, str)
        self.assertIn(IP_GENERAL, key)
        self.assertIn(hashlib.sha256(scope.encode()).hexdigest(), key)
        self.assertNotIn(scope, key)
        self.assertNotIn("telegram", key)
        self.assertIn("redis.call('TIME')", script)
        self.assertIn("ZREMRANGEBYSCORE", script)
        self.assertIn("ZCARD", script)
        self.assertIn("ZADD", script)
        self.assertIn("PEXPIRE", script)
        self.assertEqual(args[1], 240)
        self.assertEqual(args[2], 60_000_000)

    def test_sse_lease_uses_set_nx_px_and_atomic_compare_delete(self) -> None:
        client = _FakeRedis()
        client.set_results = [True, False]
        client.eval_results = [0, 1]
        guard = RedisMiniAppTrafficGuard(client=client)
        scope = "telegram:101"

        token = guard.acquire_sse(scope)
        self.assertIsInstance(token, str)
        self.assertIsNone(guard.acquire_sse(scope))
        assert token is not None
        self.assertFalse(guard.release_sse(scope, "wrong-token"))
        self.assertTrue(guard.release_sse(scope, token))

        key, stored_token, nx, px = client.set_calls[0]
        self.assertNotIn(scope, key)
        self.assertIn(hashlib.sha256(scope.encode()).hexdigest(), key)
        self.assertEqual(stored_token, token)
        self.assertTrue(nx)
        self.assertEqual(px, 960_000)
        release_script, numkeys, release_args = client.eval_calls[-1]
        self.assertEqual(numkeys, 1)
        self.assertEqual(release_args[0], key)
        self.assertEqual(release_args[1], token)
        self.assertIn("GET", release_script)
        self.assertIn("DEL", release_script)

    def test_redis_errors_are_redacted_fail_closed_and_never_fallback(self) -> None:
        marker = (
            "redis://user:password@cache.internal/0 "
            "telegram:999 198.51.100.99"
        )
        client = _FakeRedis()
        client.error = RuntimeError(marker)
        guard = RedisMiniAppTrafficGuard(client=client)

        calls = (
            lambda: guard.consume(IP_GENERAL, "198.51.100.99"),
            lambda: guard.acquire_sse("telegram:999"),
            lambda: guard.release_sse("telegram:999", "lease-token"),
        )
        for call in calls:
            with self.subTest(call=call):
                with self.assertRaises(MiniAppTrafficUnavailable) as captured:
                    call()
                error = captured.exception
                self.assertEqual(str(error), "miniapp_unavailable")
                self.assertNotIn(marker, repr(error))
                self.assertIsNone(error.__cause__)
                self.assertIsNone(error.__context__)


if __name__ == "__main__":
    unittest.main()

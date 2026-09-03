from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from review_triage.demo.app import create_app
from review_triage.demo.rate_limit import RateLimiter

from tests.test_demo_api import REQUEST, StubService, routed_state


def build_client(limit: int) -> TestClient:
    service = StubService(routed_state())
    app = create_app(
        service_provider=lambda: service,
        rate_limiter=RateLimiter(limit=limit, window_seconds=60),
    )
    return TestClient(app)


class RateLimitTests(unittest.TestCase):
    def test_requests_within_limit_succeed(self) -> None:
        client = build_client(limit=5)
        for _ in range(3):
            self.assertEqual(client.post("/api/review", json=REQUEST).status_code, 200)

    def test_exceeding_limit_returns_429(self) -> None:
        client = build_client(limit=2)
        self.assertEqual(client.post("/api/review", json=REQUEST).status_code, 200)
        self.assertEqual(client.post("/api/review", json=REQUEST).status_code, 200)
        response = client.post("/api/review", json=REQUEST)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error"]["code"], "RATE_LIMITED")

    def test_x_forwarded_for_is_used_as_client_key(self) -> None:
        service = StubService(routed_state())
        app = create_app(
            service_provider=lambda: service,
            rate_limiter=RateLimiter(limit=1, window_seconds=60),
        )
        client = TestClient(app)
        headers = {"X-Forwarded-For": "203.0.113.9"}
        self.assertEqual(
            client.post("/api/review", json=REQUEST, headers=headers).status_code, 200
        )
        self.assertEqual(
            client.post("/api/review", json=REQUEST, headers=headers).status_code, 429
        )
        # A different forwarded IP has its own budget.
        other = {"X-Forwarded-For": "203.0.113.10"}
        self.assertEqual(
            client.post("/api/review", json=REQUEST, headers=other).status_code, 200
        )

    def test_overlong_text_is_rejected_before_service(self) -> None:
        service = StubService(routed_state())
        client = TestClient(create_app(service_provider=lambda: service))
        long_text = "x" * 2001
        response = client.post(
            "/api/review",
            json={
                "source_text": long_text,
                "translation": "候选译文",
                "content_type": "UI",
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "TEXT_TOO_LONG")
        self.assertEqual(service.calls, [])


if __name__ == "__main__":
    unittest.main()

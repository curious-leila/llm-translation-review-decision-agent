from __future__ import annotations

import unittest

from fastapi import HTTPException

from review_triage.demo.live import SingleUseLiveProcessor


class _FakeService:
    def __init__(self) -> None:
        self.calls = 0

    def process_case(self, **kwargs):
        self.calls += 1
        return {"status": "ok"}


class LiveUsageCapTests(unittest.TestCase):
    def _run(self, processor: SingleUseLiveProcessor, n: int) -> None:
        for _ in range(n):
            processor.process_case(
                eval_run_id="run-1", raw_input=None, run_mode="DEVELOPMENT"
            )

    def test_default_cap_is_one(self) -> None:
        processor = SingleUseLiveProcessor(_FakeService())
        self._run(processor, 1)
        with self.assertRaises(HTTPException):
            self._run(processor, 1)

    def test_unlimited_when_max_uses_is_none(self) -> None:
        processor = SingleUseLiveProcessor(_FakeService(), max_uses=None)
        self._run(processor, 5)  # 不应抛错

    def test_cap_blocks_after_configured_count(self) -> None:
        processor = SingleUseLiveProcessor(_FakeService(), max_uses=3)
        self._run(processor, 3)
        with self.assertRaises(HTTPException):
            self._run(processor, 1)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import pytest

from app.services.run_executor import _TokenBatcher


class _FakeEvents:
    def __init__(self) -> None:
        self.items: list[tuple[str, dict, str | None]] = []

    async def emit(self, event_type: str, payload: dict, *, stage: str | None = None) -> dict:
        self.items.append((event_type, payload, stage))
        return {}


@pytest.fixture(autouse=True)
def _no_auto_flush(monkeypatch: pytest.MonkeyPatch):
    # 关掉按时间/长度自动 flush，测试只验证显式 flush 的合并结果
    monkeypatch.setattr("app.services.run_executor.TOKEN_FLUSH_INTERVAL", 10**9)
    monkeypatch.setattr("app.services.run_executor.TOKEN_FLUSH_CHARS", 10**9)


async def test_stage_started_emitted_once_and_tokens_merged() -> None:
    events = _FakeEvents()
    batcher = _TokenBatcher(events)  # type: ignore[arg-type]

    await batcher.add("analysis", "你")
    await batcher.add("analysis", "好")
    assert [item[0] for item in events.items] == ["stage_started"]
    assert events.items[0][1] == {"stage": "analysis"}

    await batcher.flush("analysis")
    assert events.items[-1] == ("llm_token", {"text": "你好"}, "analysis")

    await batcher.add("analysis", "！")
    assert [item[0] for item in events.items].count("stage_started") == 1
    await batcher.flush_all()
    assert events.items[-1] == ("llm_token", {"text": "！"}, "analysis")


async def test_unknown_stage_and_empty_text_ignored() -> None:
    events = _FakeEvents()
    batcher = _TokenBatcher(events)  # type: ignore[arg-type]

    await batcher.add(None, "x")
    await batcher.add("design", "")
    assert events.items == []


async def test_two_stages_flush_independently() -> None:
    events = _FakeEvents()
    batcher = _TokenBatcher(events)  # type: ignore[arg-type]

    await batcher.add("analysis", "A")
    await batcher.add("design", "B")
    await batcher.flush("analysis")
    assert events.items[-1] == ("llm_token", {"text": "A"}, "analysis")
    await batcher.flush_all()
    assert events.items[-1] == ("llm_token", {"text": "B"}, "design")

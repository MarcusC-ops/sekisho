"""SSE fan-out (GET /v1/stream): increasing ids, every subscriber gets every event,
Last-Event-ID replay, slow subscribers drop their oldest messages."""

from __future__ import annotations

import asyncio
import json

from gate_testkit import screen_body

from sekisho_gate.sse import Broker, parse_last_event_id


def drain(q) -> list:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def test_ids_increase_and_fan_out():
    b = Broker()
    q1, q2 = b.subscribe(), b.subscribe()
    b.publish("case.created", {"a": 1})
    b.publish("metrics.updated", {"b": 2})
    m1, m2 = drain(q1), drain(q2)
    assert [m.id for m in m1] == [1, 2] == [m.id for m in m2]
    assert m1[0].as_sse() == {"id": "1", "event": "case.created", "data": '{"a": 1}'}
    b.unsubscribe(q1)
    b.publish("case.updated", {})
    assert drain(q1) == [] and [m.id for m in drain(q2)] == [3]


def test_replay_after_last_event_id():
    b = Broker()
    for i in range(5):
        b.publish("chain.event", {"i": i})
    q = b.subscribe(last_event_id=3)
    assert [m.id for m in drain(q)] == [4, 5]
    assert parse_last_event_id("3") == 3 and parse_last_event_id("x") is None and parse_last_event_id(None) is None


def test_slow_subscriber_drops_oldest():
    b = Broker(queue_size=2)
    q = b.subscribe()
    for i in range(4):
        b.publish("case.updated", {"i": i})
    assert [json.loads(m.data)["i"] for m in drain(q)] == [2, 3]


async def test_stream_generator_yields_sse_dicts():
    b = Broker()
    gen = b.stream()
    first = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0)
    b.publish("case.created", {"case_id": "cs_1"})
    item = await asyncio.wait_for(first, 1.0)
    assert item["event"] == "case.created" and json.loads(item["data"]) == {"case_id": "cs_1"}
    await gen.aclose()
    assert b.subscriber_count == 0


async def test_stream_route_sends_events(gate):
    g = await gate()
    sent: list[dict] = []
    done = asyncio.Event()

    async def receive():
        await done.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)
        if message["type"] == "http.response.body" and b"event: case.created" in message.get("body", b""):
            done.set()

    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1",
             "method": "GET", "scheme": "http", "path": "/v1/stream", "raw_path": b"/v1/stream",
             "query_string": b"", "root_path": "", "headers": [(b"host", b"gate")],
             "client": ("127.0.0.1", 5000), "server": ("gate", 80)}
    task = asyncio.create_task(g.app(scope, receive, send))
    for _ in range(50):
        if g.svc.broker.subscriber_count:
            break
        await asyncio.sleep(0.01)
    await g.client.post("/v1/screen", json=screen_body())
    await asyncio.wait_for(task, 5.0)
    start = next(m for m in sent if m["type"] == "http.response.start")
    headers = dict(start["headers"])
    assert start["status"] == 200 and headers[b"content-type"].startswith(b"text/event-stream")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body").decode()
    assert "id: 1" in body and "event: case.created" in body
    data_line = next(line for line in body.splitlines() if line.startswith("data: "))
    assert json.loads(data_line[6:])["verdict"] == "ALLOW"

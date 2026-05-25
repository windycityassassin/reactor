"""Tests for KickChatMonitor's Pusher message parsing and velocity_curve.
We mock the WebSocketApp callbacks so no network is needed."""
import json
import time

from clipping.chat_kick import KickChatMonitor, CHAT_EVENT


class _DummyWS:
    """Stand-in for websocket.WebSocketApp; records sent subscribe frames."""
    def __init__(self):
        self.sent = []
    def send(self, frame: str):
        self.sent.append(frame)


def _make_monitor():
    m = KickChatMonitor(channel="someone", chatroom_id=12345)
    m._started_at = time.time()  # pretend start() ran
    return m


def test_pusher_connection_established_triggers_subscribe():
    m = _make_monitor()
    ws = _DummyWS()
    envelope = json.dumps({"event": "pusher:connection_established",
                           "data": json.dumps({"socket_id": "x.y", "activity_timeout": 120})})
    m._on_message(ws, envelope)
    assert m._connected.is_set()
    assert len(ws.sent) == 1
    parsed = json.loads(ws.sent[0])
    assert parsed["event"] == "pusher:subscribe"
    assert parsed["data"]["channel"] == "chatrooms.12345.v2"
    assert parsed["data"]["auth"] == ""


def test_chat_event_records_timestamp():
    m = _make_monitor()
    ws = _DummyWS()
    chat_envelope = json.dumps({
        "event": CHAT_EVENT,
        "data": json.dumps({"id": "1", "content": "POG", "chatroom_id": 12345}),
        "channel": "chatrooms.12345.v2",
    })
    assert len(m._timestamps) == 0
    m._on_message(ws, chat_envelope)
    m._on_message(ws, chat_envelope)
    m._on_message(ws, chat_envelope)
    assert len(m._timestamps) == 3


def test_non_chat_events_are_ignored():
    m = _make_monitor()
    ws = _DummyWS()
    m._on_message(ws, json.dumps({"event": "pusher:pong"}))
    m._on_message(ws, json.dumps({"event": "pusher:subscription_succeeded"}))
    m._on_message(ws, json.dumps({"event": "App\\Events\\StreamerIsLive", "data": "{}"}))
    assert len(m._timestamps) == 0


def test_garbage_payload_does_not_crash():
    m = _make_monitor()
    ws = _DummyWS()
    m._on_message(ws, "not json")
    m._on_message(ws, "")
    assert len(m._timestamps) == 0


def test_velocity_curve_bins_messages():
    m = _make_monitor()
    # Fake 10 messages at t=0..9
    m._timestamps.extend(float(i) for i in range(10))
    curve = m.velocity_curve(start=0.0, end=10.0, bin_seconds=2.0)
    # 5 bins of 2s each, each holding 2 messages
    assert [v for _, v in curve] == [2, 2, 2, 2, 2]
    # bin centers should be 1.0, 3.0, 5.0, 7.0, 9.0
    assert [round(t, 1) for t, _ in curve] == [1.0, 3.0, 5.0, 7.0, 9.0]


def test_messages_in_range():
    m = _make_monitor()
    m._timestamps.extend([1.0, 2.0, 3.0, 4.0, 5.0])
    # half-open [start, end): boundary on end is NOT counted
    assert m.messages_in_range(0.0, 3.5) == 3   # 1.0, 2.0, 3.0
    assert m.messages_in_range(2.0, 4.0) == 2   # 2.0, 3.0
    assert m.messages_in_range(10.0, 20.0) == 0

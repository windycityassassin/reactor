"""Anonymous Kick chat client over Pusher WebSocket.

Kick's chat is delivered via a Pusher (pusher-js compatible) WebSocket.
The Pusher app key is publicly embedded in Kick's web bundle; subscribing
to a public chatroom needs no auth token. The catch is that to *know* a
channel's chatroom_id you need the Cloudflare-protected REST endpoint at
`kick.com/api/v2/channels/<slug>`, which doesn't work from a normal
server. Therefore: pass the chatroom_id in from config, after looking it
up once in your browser's DevTools.

Public API mirrors `chat.ChatMonitor` so `score.py` and `cli.py` don't
need to know which platform they're talking to.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from bisect import bisect_left
from collections import deque

import websocket  # websocket-client

log = logging.getLogger(__name__)

PUSHER_URL = (
    "wss://ws-us2.pusher.com/app/{key}?protocol=7&client=clipping&version=0.1.0&flash=false"
)
# Kick's Pusher app key. Public, embedded in their JS bundle. If Kick rotates
# it the connection will fail with a clear error - update via config.
DEFAULT_PUSHER_KEY = "32cbd69e4b950bf97679"

CHAT_EVENT = "App\\Events\\ChatMessageEvent"


class KickChatMonitor:
    """Anonymous Pusher WS subscriber for a single Kick chatroom."""

    def __init__(
        self,
        channel: str,
        chatroom_id: int,
        history_seconds: int = 3600,
        pusher_key: str = DEFAULT_PUSHER_KEY,
    ):
        self.channel = channel
        self.chatroom_id = int(chatroom_id)
        self.history_seconds = history_seconds
        self.pusher_key = pusher_key
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()
        self._ws: websocket.WebSocketApp | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._connected = threading.Event()
        self._started_at: float = 0.0

    def started_at(self) -> float:
        return self._started_at

    def start(self) -> None:
        if self._thread is not None:
            return
        self._started_at = time.time()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self._connected.wait(timeout=10):
            log.warning("kick chat: did not see pusher:connection_established within 10s")
        else:
            log.info("kick chat connected to chatroom %s (#%s)", self.chatroom_id, self.channel)

    def stop(self) -> None:
        self._stop.set()
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        url = PUSHER_URL.format(key=self.pusher_key)
        while not self._stop.is_set():
            ws = websocket.WebSocketApp(
                url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
            )
            self._ws = ws
            try:
                ws.run_forever(ping_interval=60, ping_timeout=10)
            except Exception:
                log.exception("kick chat ws crashed")
            if self._stop.is_set():
                break
            log.info("kick chat reconnecting in 5s")
            time.sleep(5)

    # ---- pusher protocol ---------------------------------------------------

    def _on_open(self, _ws: "websocket.WebSocketApp") -> None:
        log.debug("kick chat ws open")

    def _on_error(self, _ws: "websocket.WebSocketApp", err: Exception) -> None:
        log.warning("kick chat ws error: %s", err)

    def _on_close(self, _ws: "websocket.WebSocketApp", code, reason) -> None:
        log.debug("kick chat ws closed: %s %s", code, reason)

    def _on_message(self, ws: "websocket.WebSocketApp", raw: str) -> None:
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError:
            log.debug("kick chat: non-json message: %s", raw[:200])
            return
        event = envelope.get("event")

        if event == "pusher:connection_established":
            self._connected.set()
            subscribe = {
                "event": "pusher:subscribe",
                "data": {"auth": "", "channel": f"chatrooms.{self.chatroom_id}.v2"},
            }
            ws.send(json.dumps(subscribe))
            return

        if event == "pusher:pong":
            return

        if event == CHAT_EVENT:
            self._record_message()
            return

    def _record_message(self) -> None:
        now = time.time() - self._started_at
        with self._lock:
            self._timestamps.append(now)
            cutoff = now - self.history_seconds
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()

    # ---- public query interface (matches chat.ChatMonitor) -----------------

    def velocity_curve(self, start: float, end: float, bin_seconds: float = 2.0) -> list[tuple[float, int]]:
        with self._lock:
            timestamps = list(self._timestamps)
        result: list[tuple[float, int]] = []
        t = start
        while t < end:
            bin_end = t + bin_seconds
            lo = bisect_left(timestamps, t)
            hi = bisect_left(timestamps, bin_end)
            result.append((t + bin_seconds / 2, hi - lo))
            t = bin_end
        return result

    def messages_in_range(self, start: float, end: float) -> int:
        with self._lock:
            timestamps = list(self._timestamps)
        return bisect_left(timestamps, end) - bisect_left(timestamps, start)

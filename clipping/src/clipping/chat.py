"""Anonymous Twitch IRC chat client.

Twitch's IRC bridge accepts an anonymous nickname of the form `justinfan{N}`
without an OAuth token, granting read access to chat channels. We use it to
track messages-per-second so that scoring can correlate chat spikes with
audio peaks.
"""
from __future__ import annotations

import logging
import random
import socket
import threading
import time
from bisect import bisect_left
from collections import deque

log = logging.getLogger(__name__)

IRC_HOST = "irc.chat.twitch.tv"
IRC_PORT = 6667


class ChatMonitor:
    """Connect anonymously to Twitch IRC and record PRIVMSG timestamps.
    Timestamps are seconds-since-start-of-monitor (monotonic-ish wall clock),
    matching the convention used by ingest.Capture.started_at()."""

    def __init__(self, channel: str, history_seconds: int = 3600):
        self.channel = channel.lower().lstrip("#")
        self.history_seconds = history_seconds
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._started_at: float = 0.0

    def started_at(self) -> float:
        return self._started_at

    def start(self) -> None:
        if self._thread is not None:
            return
        self._sock = socket.create_connection((IRC_HOST, IRC_PORT), timeout=10)
        nick = f"justinfan{random.randint(10000, 99999)}"
        self._send(f"NICK {nick}")
        self._send(f"JOIN #{self.channel}")
        self._started_at = time.time()
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        log.info("chat connected to #%s as %s", self.channel, nick)

    def stop(self) -> None:
        self._stop.set()
        if self._sock:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._sock.close()
        if self._thread:
            self._thread.join(timeout=2)

    def _send(self, line: str) -> None:
        assert self._sock is not None
        self._sock.sendall((line + "\r\n").encode("utf-8"))

    def _read_loop(self) -> None:
        assert self._sock is not None
        buf = b""
        while not self._stop.is_set():
            try:
                chunk = self._sock.recv(4096)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\r\n" in buf:
                line, buf = buf.split(b"\r\n", 1)
                self._handle(line.decode("utf-8", "ignore"))

    def _handle(self, line: str) -> None:
        if line.startswith("PING "):
            self._send("PONG " + line[5:])
            return
        # PRIVMSG format: ":nick!user@host PRIVMSG #channel :message"
        if " PRIVMSG " not in line:
            return
        now = time.time() - self._started_at
        with self._lock:
            self._timestamps.append(now)
            # drop expired
            cutoff = now - self.history_seconds
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()

    def velocity_curve(self, start: float, end: float, bin_seconds: float = 2.0) -> list[tuple[float, int]]:
        """Return [(bin_center_t, msg_count)] across [start, end), half-open bins."""
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
        """Count messages with start <= t < end."""
        with self._lock:
            timestamps = list(self._timestamps)
        return bisect_left(timestamps, end) - bisect_left(timestamps, start)

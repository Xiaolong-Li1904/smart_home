"""Message buses. Controller and nodes only see `publish` / `subscribe`, so they run unchanged on either.

- LocalBus: in-process, synchronous, deterministic. Used for fast offline simulation and tests.
- MqttBus:  a real MQTT broker. Used for live runs and, later, real hardware.
"""

from __future__ import annotations

import json
import threading
from collections import deque
from typing import Any, Callable

Payload = dict[str, Any]
Handler = Callable[[str, Payload], None]


def topic_matches(pattern: str, topic: str) -> bool:
    """MQTT wildcard match: '+' is one level, '#' is the rest."""
    p_parts, t_parts = pattern.split("/"), topic.split("/")
    for i, p in enumerate(p_parts):
        if p == "#":
            return True
        if i >= len(t_parts) or (p != "+" and p != t_parts[i]):
            return False
    return len(p_parts) == len(t_parts)


class LocalBus:
    """Delivers messages in publish order. Messages published from inside a handler are queued
    and delivered after it returns, like a broker would, so handlers never re-enter."""

    def __init__(self) -> None:
        self._subs: list[tuple[str, Handler]] = []
        self._retained: dict[str, Payload] = {}
        self._queue: deque[tuple[str, Payload, Handler | None]] = deque()
        self._delivering = False

    def subscribe(self, pattern: str, handler: Handler) -> None:
        self._subs.append((pattern, handler))
        for topic, payload in self._retained.items():
            if topic_matches(pattern, topic):
                self._queue.append((topic, payload, handler))
        self._drain()

    def publish(self, topic: str, payload: Payload, retain: bool = False) -> None:
        if retain:
            self._retained[topic] = payload
        self._queue.append((topic, payload, None))
        self._drain()

    def _drain(self) -> None:
        if self._delivering:
            return
        self._delivering = True
        try:
            while self._queue:
                topic, payload, only = self._queue.popleft()
                if only is not None:
                    only(topic, payload)
                    continue
                for pattern, handler in list(self._subs):
                    if topic_matches(pattern, topic):
                        handler(topic, payload)
        finally:
            self._delivering = False


class MqttBus:
    """Handlers run on paho's network thread; callers that also act from other threads must lock."""

    def __init__(self, host: str = "localhost", port: int = 1883, client_id: str = "") -> None:
        import paho.mqtt.client as mqtt

        self._subs: list[tuple[str, Handler]] = []
        self._connected = threading.Event()
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.connect(host, port)
        self._client.loop_start()
        if not self._connected.wait(5.0):
            self._client.loop_stop()
            raise ConnectionError(f"no MQTT broker at {host}:{port} (is `docker compose up -d` running?)")

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        for pattern, _ in self._subs:  # resubscribe after a reconnect
            client.subscribe(pattern)
        self._connected.set()

    def _on_message(self, client, userdata, msg) -> None:
        try:
            payload = json.loads(msg.payload)
        except ValueError:
            return
        for pattern, handler in list(self._subs):
            if topic_matches(pattern, msg.topic):
                handler(msg.topic, payload)

    def subscribe(self, pattern: str, handler: Handler) -> None:
        self._subs.append((pattern, handler))
        self._client.subscribe(pattern)

    def publish(self, topic: str, payload: Payload, retain: bool = False) -> None:
        self._client.publish(topic, json.dumps(payload), qos=0, retain=retain)

    def close(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

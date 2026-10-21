import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import reader


class ReaderTests(unittest.TestCase):
    def test_missing_removed_or_unavailable_sensor_is_unknown(self):
        for state in (None, {}, {"state": "unavailable"}, {"state": "unknown"}):
            self.assertEqual(reader.state_value(state), "unknown")

    def run_relay(self, messages, clock=None):
        entity = "binary_sensor.desk_presence"
        sent = []
        closed = []

        def receive():
            if messages:
                return json.dumps(messages.pop(0))
            raise reader.websocket.WebSocketConnectionClosedException()

        connection = SimpleNamespace(
            recv=receive, send=lambda message: sent.append(json.loads(message)), close=lambda: closed.append(True),
        )
        values = []
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "ha-token").write_text("test-token")
            with patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": directory}), \
                    patch.object(reader.websocket, "create_connection", return_value=connection), \
                    patch.object(reader.time, "monotonic", clock or (lambda: 0.0)):
                with self.assertRaises(reader.websocket.WebSocketConnectionClosedException):
                    reader.relay(SimpleNamespace(url="wss://example.test/api/websocket", entity=entity), values.append)
        self.assertEqual(closed, [True])
        return values, sent

    def test_entity_update_parses_subscribe_entities_events(self):
        entity = "binary_sensor.desk_presence"
        self.assertEqual(reader.entity_update({"a": {entity: {"s": "on", "a": {}}}}, entity), "on")
        self.assertEqual(reader.entity_update({"c": {entity: {"+": {"s": "off"}}}}, entity), "off")
        self.assertEqual(reader.entity_update({"c": {entity: {"+": {"s": "unavailable"}}}}, entity), "unknown")
        self.assertIsNone(reader.entity_update({"c": {entity: {"+": {"lc": 1.0, "a": {}}}}}, entity))
        self.assertEqual(reader.entity_update({"r": [entity]}, entity), "unknown")
        self.assertIsNone(reader.entity_update({"a": {}}, entity))

    def test_subscribes_to_one_entity_and_publishes_changes(self):
        entity = "binary_sensor.desk_presence"
        values, sent = self.run_relay([
            {"type": "auth_required"},
            {"type": "auth_ok"},
            {"id": 1, "type": "result", "success": True},
            {"id": 1, "type": "event", "event": {"a": {entity: {"s": "on"}}}},
            {"id": 2, "type": "pong"},
            {"id": 1, "type": "event", "event": {"c": {entity: {"+": {"lu": 2.0}}}}},
            {"id": 1, "type": "event", "event": {"c": {entity: {"+": {"s": "off"}}}}},
            {"id": 1, "type": "event", "event": {"r": [entity]}},
        ])
        # The pong does not republish an unchanged state inside the lease.
        self.assertEqual(values, ["on", "off", "unknown"])
        self.assertEqual([message["type"] for message in sent], ["auth", "subscribe_entities", "ping"])
        self.assertEqual(sent[1]["entity_ids"], [entity])

    def test_missing_entity_snapshot_publishes_unknown(self):
        values, _ = self.run_relay([
            {"type": "auth_required"},
            {"type": "auth_ok"},
            {"id": 1, "type": "event", "event": {"a": {}}},
        ])
        self.assertEqual(values, ["unknown"])

    def test_healthy_heartbeat_renews_the_presence_lease(self):
        entity = "binary_sensor.desk_presence"
        now = [0.0]

        def clock():
            return now[0]

        class Clocked(list):
            def pop(self, index):
                item = super().pop(index)
                if item.get("type") == "pong":
                    now[0] += reader.LEASE_REFRESH
                return item

        values, _ = self.run_relay(Clocked([
            {"type": "auth_required"},
            {"type": "auth_ok"},
            {"id": 1, "type": "event", "event": {"a": {entity: {"s": "on"}}}},
            {"id": 2, "type": "pong"},
        ]), clock)
        self.assertEqual(values, ["on", "on"])
        self.assertLess(reader.LEASE_REFRESH + 10, 45)


if __name__ == "__main__":
    unittest.main()

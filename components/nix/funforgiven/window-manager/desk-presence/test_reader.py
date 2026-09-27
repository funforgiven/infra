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

    def test_snapshot_events_heartbeats_and_disconnect(self):
        entity = "binary_sensor.desk_presence"
        messages = [
            {"type": "auth_required"},
            {"type": "auth_ok"},
            {"id": 1, "type": "result", "success": True},
            {"id": 2, "type": "result", "success": True, "result": [{"entity_id": entity, "state": "on"}]},
            {"id": 3, "type": "pong"},
            {"type": "event", "event": {"data": {"entity_id": "binary_sensor.other", "new_state": {"state": "off"}}}},
            {"type": "event", "event": {"data": {"entity_id": entity, "new_state": {"state": "off"}}}},
            {"type": "event", "event": {"data": {"entity_id": entity, "new_state": None}}},
        ]
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
            with patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": directory}), patch.object(reader.websocket, "create_connection", return_value=connection):
                with self.assertRaises(reader.websocket.WebSocketConnectionClosedException):
                    reader.relay(SimpleNamespace(url="wss://example.test/api/websocket", entity=entity), values.append)
        self.assertEqual(values, ["on", "on", "off", "unknown"])
        self.assertEqual([message["type"] for message in sent], ["auth", "subscribe_events", "get_states", "ping"])
        self.assertEqual(closed, [True])


if __name__ == "__main__":
    unittest.main()

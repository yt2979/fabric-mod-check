import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import app


class AppTests(unittest.TestCase):
    def test_catalog_returns_only_the_four_scoped_mods(self):
        response = TestClient(app.app).get("/catalog")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["minecraft"], "1.21.1")
        self.assertEqual({mod["slug"] for mod in response.json()["mods"]},
                         {"sodium", "iris", "indium", "continuity"})

    def test_chat_keeps_starter_response_shape(self):
        self.assertTrue(hasattr(app, "investigate"), "The app must call the research workflow.")
        with patch.object(app, "investigate", AsyncMock(return_value=(
            "Which versions?", [{"name": "read_version", "agent": "Version researcher", "args": {}, "result": "{}"}]
        ))):
            response = TestClient(app.app).post("/chat", json={"message": "Will it work?"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {"response", "session_id", "tool_calls"})
        self.assertEqual(response.json()["tool_calls"][0]["agent"], "Version researcher")

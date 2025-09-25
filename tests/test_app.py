import os
import unittest
from flask import url_for

import app as bot_app
import storage


class AppRoutesTestCase(unittest.TestCase):
    def setUp(self):
        bot_app.app.config["TESTING"] = True
        self.client = bot_app.app.test_client()
        storage.ensure_dirs()
        self._judging_fp = storage.JUDGING_FP
        if os.path.exists(self._judging_fp):
            with open(self._judging_fp, "rb") as fh:
                self._judging_backup = fh.read()
        else:
            self._judging_backup = None

    def tearDown(self):
        if self._judging_backup is None:
            if os.path.exists(self._judging_fp):
                os.remove(self._judging_fp)
        else:
            with open(self._judging_fp, "wb") as fh:
                fh.write(self._judging_backup)

    def test_robot_display_handles_invalid_weight_class(self):
        result = bot_app.robot_display("Unknown", "TestBot")
        self.assertEqual(result["name"], "TestBot")
        self.assertIsNone(result["rating"])
        self.assertEqual(result["wins"], 0)
        self.assertEqual(result["losses"], 0)
        self.assertEqual(result["draws"], 0)
        self.assertEqual(result["ko_wins"], 0)
        self.assertEqual(result["ko_losses"], 0)

    def test_robot_presence_invalid_weight_class_redirects(self):
        response = self.client.post(
            "/robot/presence",
            data={"wc": "Unknown", "name": "TestBot", "present": "1"},
        )
        self.assertEqual(response.status_code, 302)
        with bot_app.app.test_request_context():
            expected = url_for("index", wc=bot_app.WEIGHT_CLASSES[0], _external=False)
        self.assertEqual(response.headers.get("Location"), expected)

    def test_judge_state_api_includes_meta_version(self):
        response = self.client.get("/api/judge/state")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIsInstance(payload, dict)
        self.assertIn("meta", payload)
        self.assertIn("version", payload["meta"])
        self.assertIsInstance(payload["meta"]["version"], int)

    def test_judge_state_version_only_changes_when_mutated(self):
        first = self.client.get("/api/judge/state").get_json()
        base_version = first["meta"]["version"]

        second = self.client.get("/api/judge/state").get_json()
        self.assertEqual(second["meta"]["version"], base_version)

        def mutate(state):
            counter = int(state.get("_test_counter", 0))
            state["_test_counter"] = counter + 1
            return state

        storage.update_judging_state(mutate)

        third = self.client.get("/api/judge/state").get_json()
        self.assertGreater(third["meta"]["version"], base_version)

    def test_update_judging_state_noop_does_not_bump_version(self):
        original = self.client.get("/api/judge/state").get_json()
        original_version = original["meta"]["version"]

        storage.update_judging_state(lambda state: state)

        after = self.client.get("/api/judge/state").get_json()
        self.assertEqual(after["meta"]["version"], original_version)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

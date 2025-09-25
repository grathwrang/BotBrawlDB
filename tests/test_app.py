import os
import tempfile
import unittest
from unittest import mock

from flask import url_for

import app as bot_app
import storage


class AppRoutesTestCase(unittest.TestCase):
    def setUp(self):
        bot_app.app.config["TESTING"] = True
        self.client = bot_app.app.test_client()

        # Create an isolated temp directory for all storage files.
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)

        # Build patched file paths inside the temp directory.
        patched_judging_fp = os.path.join(self._tempdir.name, "judging.json")
        patched_lock_fp = os.path.join(self._tempdir.name, "judging.lock")
        patched_schedule_fp = os.path.join(self._tempdir.name, "schedule.json")
        patched_db_files = {
            wc: os.path.join(self._tempdir.name, f"{wc.lower()}_elo.json")
            for wc in storage.DB_FILES
        }

        # Patch storage module constants so all I/O is sandboxed.
        self._patches = [
            mock.patch.object(storage, "DATA_DIR", self._tempdir.name),
            mock.patch.object(storage, "SCHEDULE_FP", patched_schedule_fp),
            mock.patch.object(storage, "JUDGING_FP", patched_judging_fp),
            mock.patch.object(storage, "JUDGING_LOCK_FP", patched_lock_fp),
            mock.patch.object(storage, "DB_FILES", patched_db_files),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

        storage.ensure_dirs()

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

        storage.update_judging_state(lambda s: s)

        after = self.client.get("/api/judge/state").get_json()
        self.assertEqual(after["meta"]["version"], original_version)

    def test_public_schedule_empty(self):
        # Ensure schedule file is empty
        storage.save_schedule({"list": []})
        resp = self.client.get("/SchedulePublic")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"No fights are scheduled yet", resp.data)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
import unittest
from flask import url_for

import app as bot_app


class AppRoutesTestCase(unittest.TestCase):
    def setUp(self):
        bot_app.app.config["TESTING"] = True
        self.client = bot_app.app.test_client()

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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

"""Synthetic safety regression for generic skill discovery."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import search_skills


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, _limit):
        return self.payload


class SkillDiscovery(unittest.TestCase):
    def test_rejects_empty_control_and_oversized_queries(self):
        for query in ("", " \t\n", "a" * 101, "safe\x00query"):
            with self.subTest(query=repr(query)):
                with self.assertRaisesRegex(ValueError, "short generic task query"):
                    search_skills.search(query)

    def test_caps_response_and_never_executes_candidates(self):
        payload = json.dumps({"skills": [{"name": "x", "id": "y", "source": "z"}]}).encode()
        with patch.object(search_skills, "urlopen", return_value=FakeResponse(payload)) as opened:
            results = search_skills.search("spreadsheet chart")
        self.assertEqual(results[0]["name"], "x")
        request = opened.call_args.args[0]
        self.assertIn("q=spreadsheet+chart", request.full_url)
        self.assertEqual(opened.call_args.kwargs["timeout"], 12)

        with patch.object(
            search_skills, "urlopen",
            return_value=FakeResponse(b"{}"),
        ):
            with self.assertRaisesRegex(ValueError, "Unexpected search response"):
                search_skills.search("pdf table")

        with patch.object(
            search_skills, "urlopen",
            return_value=FakeResponse(b"x" * 524289),
        ):
            with self.assertRaisesRegex(ValueError, "exceeds size limit"):
                search_skills.search("ocr image")

    def test_truncates_untrusted_candidate_fields(self):
        payload = json.dumps({
            "skills": [{
                "name": "n" * 300,
                "id": "i" * 400,
                "source": "s" * 300,
                "installs": "untrusted",
            }]
        }).encode()
        with patch.object(search_skills, "urlopen", return_value=FakeResponse(payload)):
            result = search_skills.search("generic task")
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]["name"]), 160)
        self.assertEqual(len(result[0]["id"]), 250)
        self.assertEqual(len(result[0]["source"]), 200)
        self.assertEqual(result[0]["installs"], "untrusted")


if __name__ == "__main__":
    unittest.main()

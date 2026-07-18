import unittest

from autohedge.json_utils import JsonParseError, extract_json


class TestExtractJson(unittest.TestCase):
    def test_plain_json_object(self):
        self.assertEqual(extract_json('{"a": 1}'), {"a": 1})

    def test_plain_json_array(self):
        self.assertEqual(extract_json('["NVDA", "MSFT"]'), ["NVDA", "MSFT"])

    def test_markdown_fenced_json(self):
        text = '```json\n{"a": 1}\n```'
        self.assertEqual(extract_json(text), {"a": 1})

    def test_leading_commentary(self):
        text = 'Sure, here is the JSON:\n{"a": 1}'
        self.assertEqual(extract_json(text), {"a": 1})

    def test_duplicated_answer_is_not_corrupted(self):
        # Reproduces a real failure seen with a "thinking" model that
        # echoed its answer twice in one response ("Extra data" from a
        # naive json.loads, and a broken merge from a greedy first-to-
        # last-brace regex). Only the first value should be returned.
        text = '{"a": 1, "b": 2}\n{"a": 1, "b": 2}'
        self.assertEqual(extract_json(text), {"a": 1, "b": 2})

    def test_trailing_commentary_after_json(self):
        text = '{"a": 1}\n\nLet me know if you need anything else.'
        self.assertEqual(extract_json(text), {"a": 1})

    def test_no_json_raises(self):
        with self.assertRaises(JsonParseError):
            extract_json("no json here at all")


if __name__ == "__main__":
    unittest.main()

import unittest

from scripts.translate_finance import apply_translation


class ApplyTranslationTests(unittest.TestCase):
    def setUp(self):
        self.story = {
            "title": "Yields Reprice Higher",
            "transcript": [
                {"id": 1, "start": 0, "end": 2, "english": "Front-end pricing moved.", "chinese": ""},
                {"id": 2, "start": 2, "end": 4, "english": "Yields rose.", "chinese": ""},
            ],
        }

    def test_applies_all_translations_without_changing_timing(self):
        result = apply_translation(
            self.story,
            {
                "titleChinese": "收益率重新定价走高",
                "summary": "市场上调了利率预期。",
                "translations": [
                    {"id": 2, "chinese": "收益率上升。"},
                    {"id": 1, "chinese": "短端利率市场的定价发生变化。"},
                ],
            },
            "openai/gpt-4.1",
        )
        self.assertEqual(result["transcript"][0]["chinese"], "短端利率市场的定价发生变化。")
        self.assertEqual(result["transcript"][1]["start"], 2)
        self.assertEqual(result["translationKind"], "github-models")

    def test_rejects_missing_sentence(self):
        with self.assertRaisesRegex(RuntimeError, "ids do not match"):
            apply_translation(
                self.story,
                {
                    "titleChinese": "标题",
                    "summary": "摘要",
                    "translations": [{"id": 1, "chinese": "第一句"}],
                },
                "model",
            )


if __name__ == "__main__":
    unittest.main()

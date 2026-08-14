import unittest

from scripts.translate_finance import apply_translation, validate_translation_batch


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
            "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        )
        self.assertEqual(result["transcript"][0]["chinese"], "短端利率市场的定价发生变化。")
        self.assertEqual(result["transcript"][1]["start"], 2)
        self.assertEqual(result["translationKind"], "cloudflare-workers-ai-sentence-locked")

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


class SentenceLockTests(unittest.TestCase):
    def test_accepts_exact_source_binding(self):
        targets = [
            {"id": 7, "source": "Yields could approach 5.3%."},
            {"id": 8, "source": "That would become a cross-asset story."},
        ]
        result = validate_translation_batch(
            targets,
            {
                "translations": [
                    {
                        "id": 7,
                        "source": "Yields could approach 5.3%.",
                        "chinese": "收益率可能接近5.3%。",
                    },
                    {
                        "id": 8,
                        "source": "That would become a cross-asset story.",
                        "chinese": "这将演变为影响多类资产的市场主题。",
                    },
                ]
            },
        )
        self.assertEqual([item["id"] for item in result], [7, 8])

    def test_rejects_shifted_source(self):
        targets = [
            {"id": 1, "source": "The front end sold off."},
            {"id": 2, "source": "Payrolls were strong."},
        ]
        with self.assertRaisesRegex(RuntimeError, "source mismatch"):
            validate_translation_batch(
                targets,
                {
                    "translations": [
                        {
                            "id": 1,
                            "source": "Payrolls were strong.",
                            "chinese": "非农就业数据强劲。",
                        },
                        {
                            "id": 2,
                            "source": "The front end sold off.",
                            "chinese": "收益率曲线短端遭到抛售。",
                        },
                    ]
                },
            )

    def test_rejects_lost_number(self):
        targets = [{"id": 3, "source": "The yield rose to 5.3%."}]
        with self.assertRaisesRegex(RuntimeError, "lost numeric values"):
            validate_translation_batch(
                targets,
                {
                    "translations": [
                        {
                            "id": 3,
                            "source": "The yield rose to 5.3%.",
                            "chinese": "收益率有所上升。",
                        }
                    ]
                },
            )


if __name__ == "__main__":
    unittest.main()

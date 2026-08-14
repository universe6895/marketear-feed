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

    def test_rejects_incorrect_financial_term(self):
        targets = [{"id": 4, "source": "There is a real rate story."}]
        with self.assertRaisesRegex(RuntimeError, "incorrect term"):
            validate_translation_batch(
                targets,
                {
                    "translations": [
                        {
                            "id": 4,
                            "source": "There is a real rate story.",
                            "chinese": "这里存在一个名义利率主题。",
                        }
                    ]
                },
            )

    def test_rejects_literal_real_rate_story(self):
        source = "There is a real rate story driving the long end."
        with self.assertRaisesRegex(RuntimeError, "literal or incorrect term"):
            validate_translation_batch(
                [{"id": 9, "source": source}],
                {
                    "translations": [{
                        "id": 9,
                        "source": source,
                        "chinese": "收益率曲线长端受到一个实际利率故事的推动。",
                    }]
                },
            )

    def test_accepts_professional_real_rate_story(self):
        source = "There is a real rate story driving the long end."
        result = validate_translation_batch(
            [{"id": 10, "source": source}],
            {
                "translations": [{
                    "id": 10,
                    "source": source,
                    "chinese": "收益率曲线长端也受到实际利率因素的推动。",
                }]
            },
        )
        self.assertEqual(result[0]["id"], 10)

    def test_rejects_literal_market_idiom(self):
        source = "We need to play the ball, not the referee."
        targets = [{"id": 5, "source": source}]
        with self.assertRaisesRegex(RuntimeError, "literal or incorrect term"):
            validate_translation_batch(
                targets,
                {
                    "translations": [
                        {
                            "id": 5,
                            "source": source,
                            "chinese": "我们需要打球，而不是关注裁判和数据。",
                        }
                    ]
                },
            )


if __name__ == "__main__":
    unittest.main()

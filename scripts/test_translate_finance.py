import unittest

from scripts.translate_finance import (
    apply_source_conditioned_repairs,
    apply_translation,
    validate_translation_batch,
    validate_vocabulary,
)


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
        self.assertEqual(
            result["translationKind"],
            "cloudflare-workers-ai-sentence-locked-dual-pass",
        )
        self.assertEqual(
            result["translationReviewKind"],
            "independent-source-draft-context-review",
        )

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


class VocabularyTests(unittest.TestCase):
    def setUp(self):
        self.story = {
            "transcript": [
                {
                    "id": 1,
                    "start": 1.25,
                    "end": 4.5,
                    "english": "Rate wagers moved at the front end of the curve.",
                },
                {
                    "id": 2,
                    "start": 4.5,
                    "end": 8.0,
                    "english": "A hot NFP could trigger a cross-asset move.",
                },
            ]
        }

    def result(self):
        return {
            "vocabulary": [
                {"id": 1, "word": "Rate wagers", "phonetic": "/reɪt ˈweɪdʒərz/", "meaning": "利率路径押注"},
                {"id": 1, "word": "front end", "phonetic": "/frʌnt end/", "meaning": "收益率曲线短端"},
                {"id": 2, "word": "hot NFP", "phonetic": "/hɒt ˌen ef ˈpiː/", "meaning": "强于预期的非农数据"},
                {"id": 2, "word": "NFP", "phonetic": "/ˌen ef ˈpiː/", "meaning": "非农就业报告"},
                {"id": 2, "word": "cross-asset", "phonetic": "/krɒs ˈæset/", "meaning": "跨资产类别的"},
            ]
        }

    def test_enriches_vocabulary_from_matching_cue(self):
        items = validate_vocabulary(self.story, self.result())
        self.assertEqual(items[0]["word"], "Rate wagers")
        self.assertEqual(items[0]["start"], 1.25)
        self.assertEqual(items[0]["source"], self.story["transcript"][0]["english"])

    def test_rejects_phrase_not_in_bound_source(self):
        result = self.result()
        result["vocabulary"][0]["word"] = "Treasury yield"
        with self.assertRaisesRegex(RuntimeError, "not an exact source substring"):
            validate_vocabulary(self.story, result)


class SentenceLockTests(unittest.TestCase):
    def test_accepts_single_sentence_binding(self):
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
                        "chinese": "收益率可能接近5.3%。",
                    },
                    {
                        "id": 8,
                        "chinese": "这将演变为影响多类资产的市场主题。",
                    },
                ]
            },
        )
        self.assertEqual([item["id"] for item in result], [7, 8])

    def test_rejects_duplicate_ids(self):
        targets = [
            {"id": 1, "source": "The front end sold off."},
            {"id": 2, "source": "Payrolls were strong."},
        ]
        with self.assertRaisesRegex(RuntimeError, "repeats sentence"):
            validate_translation_batch(
                targets,
                {
                    "translations": [
                        {
                            "id": 1,
                            "chinese": "收益率曲线短端遭到抛售。",
                        },
                        {
                            "id": 1,
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
                            "chinese": "我们需要打球，而不是关注裁判和数据。",
                        }
                    ]
                },
            )

    def test_rejects_known_machine_translated_wording(self):
        with self.assertRaisesRegex(RuntimeError, "machine-translated wording"):
            validate_translation_batch(
                [{"id": 6, "source": "Financial conditions are still super easy."}],
                {"translations": [{"id": 6, "chinese": "金融条件仍然超级宽松。"}]},
            )

    def test_rejects_margin_account_for_at_the_margin(self):
        with self.assertRaisesRegex(RuntimeError, "machine-translated wording|incorrect term"):
            validate_translation_batch(
                [{"id": 11, "source": "I can put more money into bonds at the margin."}],
                {"translations": [{"id": 11, "chinese": "我可以在保证金账户中加仓债券。"}]},
            )

    def test_rejects_high_yield_for_yields_moving_higher(self):
        with self.assertRaisesRegex(RuntimeError, "incorrect term"):
            validate_translation_batch(
                [{"id": 41, "source": "This goes into the higher yield story."}],
                {"translations": [{"id": 41, "chinese": "这又回到了高收益逻辑。"}]},
            )

    def test_allows_rough_draft_before_final_review(self):
        result = validate_translation_batch(
            [{"id": 11, "source": "I can put more money into bonds at the margin."}],
            {"translations": [{"id": 11, "chinese": "我可以在保证金账户中加仓债券。"}]},
            enforce_fluency=False,
        )
        self.assertEqual(result[0]["id"], 11)

    def test_repairs_margin_only_when_source_licenses_it(self):
        result = apply_source_conditioned_repairs(
            [{"id": 11, "source": "I can put more money into bonds at the margin."}],
            {"translations": [{"id": 11, "chinese": "我可以在保证金账户中加仓债券。"}]},
        )
        self.assertEqual(result["translations"][0]["chinese"], "我现在可以适度增加债券配置了。")

    def test_repairs_yield_theme_and_ai_caption_errors(self):
        targets = [
            {"id": 41, "source": "This goes into the higher yield story."},
            {"id": 43, "source": "The I debt funding pressure is affecting the eye space."},
        ]
        result = apply_source_conditioned_repairs(
            targets,
            {"translations": [
                {"id": 41, "chinese": "这又回到了高收益逻辑。"},
                {"id": 43, "chinese": "投资级债务融资正在影响眼球空间。"},
            ]},
        )
        self.assertEqual(result["translations"][0]["chinese"], "这同样属于收益率上行的逻辑。")
        self.assertIn("AI债务融资", result["translations"][1]["chinese"])
        self.assertIn("AI板块", result["translations"][1]["chinese"])


if __name__ == "__main__":
    unittest.main()

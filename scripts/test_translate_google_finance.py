import unittest

from scripts.translate_google_finance import (
    apply_google_translation,
    translate_contents,
    validate_translations,
)


class FakeTranslation:
    def __init__(self, text):
        self.translated_text = text


class FakeResponse:
    def __init__(self, translations=None, glossary_translations=None):
        self.translations = [FakeTranslation(value) for value in translations or []]
        self.glossary_translations = [
            FakeTranslation(value) for value in glossary_translations or []
        ]


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.request = None

    def translate_text(self, request):
        self.request = request
        return self.response


class GoogleFinanceTranslationTests(unittest.TestCase):
    def story(self):
        return {
            "title": "Yields Reprice Higher",
            "transcript": [
                {"id": 1, "start": 0, "end": 2, "english": "Yields rose to 5.3%.", "chinese": ""},
                {"id": 2, "start": 2, "end": 4, "english": "The front end sold off.", "chinese": ""},
            ],
        }

    def test_keeps_positions_and_numbers_locked(self):
        result = apply_google_translation(
            self.story(),
            "收益率重新定价走高",
            ["收益率升至5.3%。", "收益率曲线短端遭到抛售。"],
            "marketear-project",
            "us-central1",
            "marketear-finance-en-zh",
        )
        self.assertEqual(result["transcript"][0]["id"], 1)
        self.assertEqual(result["transcript"][1]["chinese"], "收益率曲线短端遭到抛售。")
        self.assertEqual(result["summary"], "收益率升至5.3%。收益率曲线短端遭到抛售。")
        self.assertIn("contextual-glossary", result["translationKind"])

    def test_rejects_lost_number(self):
        with self.assertRaisesRegex(RuntimeError, "lost numeric values"):
            validate_translations(["Yields rose to 5.3%."], ["收益率上升。"])

    def test_uses_translation_llm_and_contextual_glossary(self):
        client = FakeClient(FakeResponse(glossary_translations=["收益率曲线短端。"]))
        result = translate_contents(
            client,
            "marketear-project",
            "us-central1",
            ["The front end."],
            "marketear-finance-en-zh",
        )
        self.assertEqual(result, ["收益率曲线短端。"])
        self.assertTrue(client.request["glossary_config"]["contextual_translation_enabled"])
        self.assertTrue(client.request["model"].endswith("/models/general/translation-llm"))


if __name__ == "__main__":
    unittest.main()

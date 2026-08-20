import unittest

from scripts.publish_feed import validate_story


def complete_story():
    cues = [
        {
            "id": index,
            "start": (index - 1) * 15,
            "end": index * 15,
            "english": f"Sentence {index} refers to 5.3%.",
            "chinese": f"第{index}句提到5.3%。",
        }
        for index in range(1, 6)
    ]
    return {
        "id": "bloomberg-test",
        "date": "2026-08-20",
        "title": "Markets in 3 Minutes",
        "titleChinese": "三分钟市场",
        "summary": "完整财经译文。",
        "durationSeconds": 75,
        "youtubeVideoID": "abcdefghijk",
        "sourceURL": "https://www.youtube.com/watch?v=abcdefghijk",
        "sourceName": "Bloomberg Television",
        "captionSource": "youtube-native-caption-test",
        "translationKind": "cloudflare-workers-ai-sentence-locked",
        "translationReviewKind": "independent-source-draft-context-review",
        "transcript": cues,
    }


class PublishValidationTests(unittest.TestCase):
    def test_accepts_complete_native_caption_story(self):
        result = validate_story(complete_story())
        self.assertEqual(result["quality"]["translationCoverage"], 1.0)
        self.assertEqual(result["quality"]["sentenceCount"], 5)
        self.assertIn("dual-pass-translation-review", result["quality"]["checks"])

    def test_rejects_partial_translation(self):
        story = complete_story()
        story["transcript"][2]["chinese"] = ""
        with self.assertRaisesRegex(RuntimeError, "no financial Chinese"):
            validate_story(story)

    def test_rejects_asr_source(self):
        story = complete_story()
        story["captionSource"] = "cloudflare-whisper-asr-caption"
        with self.assertRaisesRegex(RuntimeError, "not based on an existing caption"):
            validate_story(story)

    def test_rejects_shifted_ids(self):
        story = complete_story()
        story["transcript"][1]["id"] = 8
        with self.assertRaisesRegex(RuntimeError, "not consecutive"):
            validate_story(story)


if __name__ == "__main__":
    unittest.main()

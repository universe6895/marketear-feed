import unittest
from unittest.mock import patch

from scripts.generate_daily import (
    fetch_captioned_story,
    cues_from_vtt,
    normalize_whisper_text,
    sentence_cues,
    vtt_seconds,
)


class WhisperVTTTests(unittest.TestCase):
    @patch("scripts.generate_daily.supadata_fragments")
    @patch("scripts.generate_daily.transcript_dev_fragments")
    def test_uses_proven_transcript_dev_before_supadata(
        self, transcript_dev, supadata
    ):
        fragments = [
            {
                "id": 0,
                "start": (index - 1) * 15,
                "end": index * 15,
                "english": f"Sentence {index}.",
                "chinese": "",
            }
            for index in range(1, 6)
        ]
        transcript_dev.return_value = (
            fragments,
            "Markets in 3 Minutes",
            "youtube-manual-caption-youtubetranscript.dev",
        )
        candidate, cues, _, source = fetch_captioned_story(
            [{"video_id": "abcdefghijk", "title": "Markets in 3 Minutes"}],
            "transcript-dev-key",
            "supadata-key",
        )
        self.assertEqual(candidate["video_id"], "abcdefghijk")
        self.assertEqual(len(cues), 5)
        self.assertEqual(source, "youtube-manual-caption-youtubetranscript.dev")
        transcript_dev.assert_called_once_with("abcdefghijk", "transcript-dev-key")
        supadata.assert_not_called()

    def test_parses_vtt_and_merges_complete_sentences(self):
        vtt = """WEBVTT

00:00.120 --> 00:01.800
Adam, are we

00:01.800 --> 00:03.600
still thinking about the yen?

00:03.900 --> 00:06.400
The real rate story matters.
"""
        captions = cues_from_vtt(vtt)
        self.assertEqual(len(captions), 3)
        cues = sentence_cues(captions)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0]["english"], "Adam, are we still thinking about the yen?")
        self.assertEqual(cues[0]["start"], 0.12)
        self.assertEqual(cues[0]["end"], 3.6)
        self.assertEqual(cues[1]["english"], "The real rate story matters.")

    def test_supports_hour_and_comma_timestamps(self):
        self.assertEqual(vtt_seconds("01:02:03.500"), 3723.5)
        self.assertEqual(vtt_seconds("02:03,250"), 123.25)

    def test_rejects_vtt_without_timed_text(self):
        with self.assertRaisesRegex(RuntimeError, "no usable"):
            cues_from_vtt("WEBVTT\n\nNOTE no captions")

    def test_normalizes_only_high_confidence_caption_errors(self):
        source = (
            "Kevin Walsh discussed the front end. "
            "A strong non - farm report could send 30 - year yields to 5 .3 %."
        )
        self.assertEqual(
            normalize_whisper_text(source),
            "Kevin Warsh discussed the front end. "
            "A strong nonfarm report could send 30-year yields to 5.3%.",
        )


if __name__ == "__main__":
    unittest.main()

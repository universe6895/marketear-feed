import unittest

from scripts.generate_daily import (
    cues_from_vtt,
    normalize_whisper_text,
    sentence_cues,
    vtt_seconds,
)


class WhisperVTTTests(unittest.TestCase):
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

    def test_normalizes_only_high_confidence_finance_asr_errors(self):
        source = (
            "Kevin Walsh asked whether markets ramp up these wages at the front end. "
            "A strong non - farm report could send 30 - year yields to 5 .3 %."
        )
        self.assertEqual(
            normalize_whisper_text(source),
            "Kevin Warsh asked whether markets ramp up these wagers at the front end. "
            "A strong nonfarm report could send 30-year yields to 5.3%.",
        )


if __name__ == "__main__":
    unittest.main()

import unittest

from unittest.mock import patch

from scripts.generate_daily import asr_job_url, request_asr_transcript, sentence_cues


class AudioASRTests(unittest.TestCase):
    def test_merges_fragments_into_complete_sentences(self):
        captions = [
            {"english": "Adam, are we", "start": 0.12, "end": 1.8},
            {"english": "still thinking about the yen?", "start": 1.8, "end": 3.6},
            {"english": "The real rate story matters.", "start": 3.9, "end": 6.4},
        ]
        cues = sentence_cues(captions)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0]["english"], "Adam, are we still thinking about the yen?")
        self.assertEqual(cues[0]["start"], 0.12)
        self.assertEqual(cues[0]["end"], 3.6)
        self.assertEqual(cues[1]["english"], "The real rate story matters.")

    def test_builds_job_url_from_response(self):
        self.assertEqual(
            asr_job_url({"job_id": "job-123"}),
            "https://www.youtubetranscript.dev/api/v2/jobs/job-123?include_segments=true",
        )
        self.assertEqual(asr_job_url({"poll_url": "https://example.com/job"}), "https://example.com/job")

    @patch("scripts.generate_daily.http_json")
    def test_polls_asr_until_timestamped_transcript_is_ready(self, mock_http_json):
        mock_http_json.side_effect = [
            {"status": "processing", "job_id": "job-123"},
            {"status": "processing"},
            {
                "status": "completed",
                "data": {
                    "video_title": "Markets in 3 Minutes",
                    "transcript": {
                        "source": "asr",
                        "segments": [{"text": "Markets rallied.", "start": 0, "end": 1200}],
                    },
                },
            },
        ]
        transcript, title = request_asr_transcript(
            "abcdefghijk", "token", poll_interval=0, max_polls=2
        )
        self.assertEqual(title, "Markets in 3 Minutes")
        self.assertEqual(transcript["source"], "asr")
        request_payload = mock_http_json.call_args_list[0].kwargs["payload"]
        self.assertEqual(request_payload["source"], "asr")
        self.assertIn("nonfarm payrolls", request_payload["asr_options"]["keyTerms"])


if __name__ == "__main__":
    unittest.main()

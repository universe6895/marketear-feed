import json
import tempfile
import unittest
from pathlib import Path

from scripts.schedule_freshness import story_is_current, update_is_needed


class ScheduleFreshnessTests(unittest.TestCase):
    def story(self, date: str) -> Path:
        directory = Path(tempfile.mkdtemp())
        path = directory / "today.json"
        path.write_text(json.dumps({"date": date}), encoding="utf-8")
        return path

    def test_scheduled_retry_skips_current_story(self):
        path = self.story("2026-08-21")
        self.assertTrue(story_is_current(path, "2026-08-21"))
        self.assertFalse(update_is_needed("schedule", path, "2026-08-21"))

    def test_schedule_runs_when_story_is_stale(self):
        path = self.story("2026-08-20")
        self.assertTrue(update_is_needed("schedule", path, "2026-08-21"))

    def test_manual_run_always_runs(self):
        path = self.story("2026-08-21")
        self.assertTrue(update_is_needed("workflow_dispatch", path, "2026-08-21"))

    def test_missing_or_invalid_story_is_stale(self):
        path = Path(tempfile.mkdtemp()) / "missing.json"
        self.assertFalse(story_is_current(path, "2026-08-21"))
        path.write_text("not-json", encoding="utf-8")
        self.assertFalse(story_is_current(path, "2026-08-21"))


if __name__ == "__main__":
    unittest.main()

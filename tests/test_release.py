import tempfile
import unittest
from pathlib import Path

from scripts import release


class ReleaseScriptTests(unittest.TestCase):
    def test_select_release_label_skips_when_missing(self):
        self.assertIsNone(release.select_release_label(["docs"]))

    def test_select_release_label_fails_when_multiple_labels_present(self):
        with self.assertRaises(ValueError):
            release.select_release_label(["release:patch", "release:minor"])

    def test_build_release_plan_bumps_minor_version(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            pyproject_path = Path(tmp_dir) / "pyproject.toml"
            pyproject_path.write_text(
                '[project]\nname = "kage-ai"\nversion = "1.2.3"\n',
                encoding="utf-8",
            )
            plan = release.build_release_plan(["release:minor"], 42, pyproject_path)

        self.assertTrue(plan.release)
        self.assertEqual(plan.version, "1.3.0")
        self.assertEqual(plan.tag, "v1.3.0")
        self.assertEqual(plan.commit_message, "release: v1.3.0")

    def test_select_pending_release_label_uses_highest_priority_since_last_tag(self):
        merged_prs = [
            {
                "mergedAt": "2026-03-07T10:00:00Z",
                "labels": [{"name": "release:patch"}],
            },
            {
                "mergedAt": "2026-03-07T12:00:00Z",
                "labels": [{"name": "release:major"}],
            },
            {
                "mergedAt": "2026-03-06T09:00:00Z",
                "labels": [{"name": "release:minor"}],
            },
        ]

        label = release.select_pending_release_label(
            merged_prs,
            "2026-03-07T00:00:00+00:00",
        )

        self.assertEqual(label, "release:major")

    def test_apply_release_plan_updates_pyproject_version(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            pyproject_path = Path(tmp_dir) / "pyproject.toml"
            pyproject_path.write_text(
                '[project]\nname = "kage-ai"\nversion = "1.2.3"\n',
                encoding="utf-8",
            )
            plan = release.build_release_plan(["release:patch"], 7, pyproject_path)
            release.apply_release_plan(plan, pyproject_path)
            content = pyproject_path.read_text(encoding="utf-8")

        self.assertIn('version = "1.2.4"', content)


if __name__ == "__main__":
    unittest.main()

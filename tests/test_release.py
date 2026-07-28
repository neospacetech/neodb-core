import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.check_release_version import main, project_version, validate_release_tag


class ReleaseVersionTests(unittest.TestCase):
    def test_reads_project_version_and_accepts_exact_tag(self):
        with tempfile.TemporaryDirectory() as directory:
            pyproject = Path(directory) / "pyproject.toml"
            pyproject.write_text(
                '[project]\nname = "example"\nversion = "1.2.3rc1"\n',
                encoding="utf-8",
            )
            version = project_version(pyproject)
        self.assertEqual(version, "1.2.3rc1")
        validate_release_tag("v1.2.3rc1", version)

    def test_rejects_mismatched_or_unprefixed_tag(self):
        for tag in ("1.2.3", "v1.2.4"):
            with (
                self.subTest(tag=tag),
                self.assertRaisesRegex(ValueError, "expected 'v1.2.3'"),
            ):
                validate_release_tag(tag, "1.2.3")

    def test_cli_returns_failure_for_invalid_project_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            pyproject = Path(directory) / "pyproject.toml"
            pyproject.write_text("[project]\nname = 'example'\n", encoding="utf-8")
            with patch("sys.stderr"):
                status = main(["v1.0.0", "--pyproject", str(pyproject)])
        self.assertEqual(status, 1)


if __name__ == "__main__":
    unittest.main()

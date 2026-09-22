"""Regression tests for domain glossary sources."""
from pathlib import Path
import runpy
import unittest

ROOT = Path(__file__).resolve().parents[1]
M = runpy.run_path(str(ROOT / "scripts/20-build-glossary.py"))
HOTWORDS = ROOT / "hotwords"


class GlossaryTests(unittest.TestCase):
    def test_requested_work_tools_are_present(self):
        terms = M["merge_terms"]([
            HOTWORDS / "programming.txt",
            HOTWORDS / "work-tools.txt",
            HOTWORDS / "dental.txt",
        ])
        folded = {term.casefold() for term in terms}
        for expected in ("Stripe", "Linear", "Vercel", "AWS"):
            self.assertIn(expected.casefold(), folded)

    def test_requested_dental_distributors_are_present(self):
        terms = M["read_terms"](HOTWORDS / "dental.txt")
        folded = {term.casefold() for term in terms}
        for expected in ("Darby Dental", "Henry Schein", "DC Dental"):
            self.assertIn(expected.casefold(), folded)

    def test_programming_glossary_has_common_code_switch_terms(self):
        terms = M["read_terms"](HOTWORDS / "programming.txt")
        folded = {term.casefold() for term in terms}
        for expected in (
            "GitHub Actions",
            "pull request",
            "VS Code",
            "systemd",
            "Kubernetes",
            "PostgreSQL",
            "SwiftUI",
            "Claude Code",
        ):
            self.assertIn(expected.casefold(), folded)

    def test_merge_is_case_insensitive_and_stable(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.txt"
            b = Path(tmp) / "b.txt"
            a.write_text("GitHub\nStripe\n", encoding="utf-8")
            b.write_text("github\nAWS\n", encoding="utf-8")
            self.assertEqual(
                M["merge_terms"]([a, b]),
                ["GitHub", "Stripe", "AWS"],
            )


if __name__ == "__main__":
    unittest.main()

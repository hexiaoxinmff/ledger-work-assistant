"""Keep the repository landing-page version aligned with the installed skill."""
import re
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class ReleaseMetadata(unittest.TestCase):
    def test_readme_version_matches_skill_title(self):
        skill = (REPOSITORY_ROOT / "ledger-organizer" / "SKILL.md").read_text(encoding="utf-8")
        readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
        skill_versions = re.findall(r"^# 费用与收款台账整理助手 (v\d+\.\d+)$", skill, re.MULTILINE)
        readme_versions = re.findall(r"当前技能版本：(v\d+\.\d+)。", readme)
        self.assertEqual(len(skill_versions), 1, "SKILL.md must have exactly one versioned title")
        self.assertEqual(len(readme_versions), 1, "README.md must declare exactly one current skill version")
        self.assertEqual(readme_versions[0], skill_versions[0])


if __name__ == "__main__":
    unittest.main()

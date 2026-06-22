import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import nix_skills


class NixSkillsTests(unittest.TestCase):
    def test_parse_tree_url(self):
        parsed = nix_skills.parse_tree_url(
            "https://github.com/mattpocock/skills/tree/main/skills/engineering/grill-with-docs"
        )
        self.assertEqual(
            parsed,
            (
                "mattpocock",
                "skills",
                "main",
                "skills/engineering/grill-with-docs",
            ),
        )

    def test_cycle_detection(self):
        entries = {
            "a": { "dependencies": [ "b" ] },
            "b": { "dependencies": [ "a" ] },
        }
        with self.assertRaises(nix_skills.RegistryError):
            nix_skills.check_cycles(entries)

    def test_generated_registry_is_stable(self):
        entries = {
            "demo": {
                "slug": "demo",
                "displayName": "Demo",
                "description": "Demo skill.",
                "license": "MIT",
                "author": "Tester",
                "compatibleTargets": [ "agents" ],
                "source": {
                    "type": "github",
                    "owner": "owner",
                    "repo": "repo",
                    "rev": "0" * 40,
                    "path": "skills/demo",
                    "narHash": "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
                },
            }
        }
        first = nix_skills.generated_registry_nix(entries)
        second = nix_skills.generated_registry_nix(entries)
        self.assertEqual(first, second)

    def test_frontmatter_parser(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "SKILL.md"
            path.write_text("---\nname: demo\ndescription: Demo skill.\n---\nBody\n", encoding="utf-8")
            metadata = nix_skills.parse_frontmatter(path)
        self.assertEqual(metadata["name"], "demo")
        self.assertEqual(metadata["description"], "Demo skill.")


if __name__ == "__main__":
    unittest.main()

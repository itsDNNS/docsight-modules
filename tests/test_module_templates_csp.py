"""Module templates must work under a strict script-src CSP (no 'unsafe-inline')."""

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Script types the browser never executes, so CSP does not apply to them.
DATA_SCRIPT_TYPES = {"application/json", "application/ld+json"}
EVENT_HANDLER = re.compile(r"^on[a-z]+$")


class _InlineScriptFinder(HTMLParser):
    def __init__(self):
        super().__init__()
        self.problems = []

    def handle_starttag(self, tag, attrs):
        line = self.getpos()[0]
        values = dict(attrs)
        if tag == "script" and "src" not in values:
            script_type = (values.get("type") or "").strip().lower()
            if script_type not in DATA_SCRIPT_TYPES:
                self.problems.append(f"line {line}: inline <script>")
        for name, value in attrs:
            if EVENT_HANDLER.match(name):
                self.problems.append(f"line {line}: {name}= attribute on <{tag}>")
            elif value and value.strip().lower().startswith("javascript:"):
                self.problems.append(f"line {line}: javascript: URL in {name}=")


def inline_script_problems(source):
    finder = _InlineScriptFinder()
    finder.feed(source)
    finder.close()
    return finder.problems


def module_templates():
    return sorted(ROOT.glob("*/templates/**/*.html"))


class ModuleTemplatesCspTests(unittest.TestCase):
    def test_templates_have_no_inline_javascript(self):
        templates = module_templates()
        self.assertTrue(templates, "no module templates found")
        for path in templates:
            with self.subTest(template=str(path.relative_to(ROOT))):
                self.assertEqual(
                    inline_script_problems(path.read_text(encoding="utf-8")), []
                )

    def test_checker_flags_inline_javascript(self):
        self.assertEqual(len(inline_script_problems("<script>run()</script>")), 1)
        self.assertEqual(
            len(inline_script_problems('<script type="module">run()</script>')), 1
        )
        self.assertEqual(len(inline_script_problems('<button onclick="run()">')), 1)
        self.assertEqual(
            len(inline_script_problems('<script src="a.js" onerror="x()"></script>')), 1
        )
        self.assertEqual(len(inline_script_problems('<a href=" JavaScript:run()">')), 1)

    def test_checker_allows_external_and_data_scripts(self):
        self.assertEqual(inline_script_problems('<script src="static/main.js"></script>'), [])
        self.assertEqual(
            inline_script_problems('<script type="application/json">{"a": 1}</script>'), []
        )
        self.assertEqual(inline_script_problems('<button id="b" data-on="x">'), [])


if __name__ == "__main__":
    unittest.main()

import unittest
from src.Utils import stripDoc


class TestUtils(unittest.TestCase):
    def test_empty_docstring(self):
        """Test that empty docstring returns empty string."""
        self.assertEqual(stripDoc(""), "")
        self.assertEqual(stripDoc("   "), "")
        self.assertEqual(stripDoc("\n\n"), "")

    def test_single_line_docstring(self):
        """Test single line docstrings."""
        self.assertEqual(stripDoc("Hello"), "Hello")
        self.assertEqual(stripDoc("  Hello  "), "Hello")

    def test_multiline_consistent_indent(self):
        """Test multiline docstrings with consistent indentation."""
        docstring = """This is a docstring.
            With multiple lines.
            All indented the same."""
        expected = """This is a docstring.
With multiple lines.
All indented the same."""
        self.assertEqual(stripDoc(docstring), expected)

    def test_multiline_inconsistent_indent(self):
        """Test multiline docstrings with inconsistent indentation."""
        docstring = """This is a docstring.
            With multiple lines.
          Indented differently."""
        expected = """This is a docstring.
  With multiple lines.
Indented differently."""
        self.assertEqual(stripDoc(docstring), expected)

    def test_docstring_with_empty_lines(self):
        """Test docstrings with empty lines."""
        docstring = """This is a docstring.

            With an empty line."""
        expected = """This is a docstring.

With an empty line."""
        self.assertEqual(stripDoc(docstring), expected)

    def test_docstring_with_only_whitespace_lines(self):
        """Test docstrings with lines containing only whitespace."""
        docstring = """This is a docstring.

            Next line after whitespace."""
        expected = """This is a docstring.

Next line after whitespace."""
        self.assertEqual(stripDoc(docstring), expected)

    def test_docstring_with_special_characters(self):
        """Test docstrings with special characters and tabs."""
        docstring = """This is a docstring.
            \tWith a tab.
            *Special* characters!"""
        expected = """This is a docstring.
\tWith a tab.
*Special* characters!"""
        self.assertEqual(stripDoc(docstring), expected)


if __name__ == "__main__":
    unittest.main()

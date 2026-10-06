import unittest

from src.SafeDiagnostics import format_safe_exception_diagnostic


class TestSafeDiagnostics(unittest.TestCase):

    def test_diagnostic_keeps_exception_classes_and_frames_without_values(self):
        try:
            try:
                raise ValueError("Bearer temporary-secret-token")
            except ValueError as cause:
                raise RuntimeError("/private/vault/notes.md?token=temporary-secret-token") from cause
        except RuntimeError as error:
            diagnostic = format_safe_exception_diagnostic(error)

        self.assertIn("exception_chain=RuntimeError>ValueError", diagnostic)
        self.assertIn("SafeDiagnostics_test.py:", diagnostic)
        self.assertNotIn("Bearer", diagnostic)
        self.assertNotIn("temporary-secret-token", diagnostic)
        self.assertNotIn("/private/vault", diagnostic)
        self.assertNotIn("notes.md?token", diagnostic)

    def test_diagnostic_bounds_traceback_and_exception_chains(self):
        def recurse(depth):
            if depth == 0:
                raise ValueError("deep failure")
            recurse(depth - 1)

        try:
            recurse(50)
        except ValueError as error:
            diagnostic = format_safe_exception_diagnostic(error)

        frames = diagnostic.split("; frames=", 1)[1].split(",")
        self.assertLessEqual(len(frames), 20)
        self.assertLessEqual(diagnostic.count(">") + 1, 9)

    def test_cyclic_exception_context_terminates(self):
        error = RuntimeError("secret message")
        error.__cause__ = error

        diagnostic = format_safe_exception_diagnostic(error)

        self.assertEqual(diagnostic, "exception_chain=RuntimeError; frames=none")
        self.assertNotIn("secret message", diagnostic)


if __name__ == "__main__":
    unittest.main()

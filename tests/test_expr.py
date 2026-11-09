"""Expressions: a JavaScript / After Effects-like single expression, parsed and run by the program."""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kiasecut import expr  # noqa: E402


class ExprTests(unittest.TestCase):
    def v(self, text, **env):
        return expr.evaluate(text, env)

    def test_arithmetic_and_precedence(self):
        self.assertEqual(self.v("1 + 2 * 3"), 7)
        self.assertEqual(self.v("(1 + 2) * 3"), 9)
        self.assertEqual(self.v("2 ** 3 ** 2"), 512)
        self.assertEqual(self.v("-2 ** 2"), -4)
        self.assertEqual(self.v("7 % 4"), 3)
        self.assertEqual(self.v("1e2 + .5"), 100.5)

    def test_names_and_math(self):
        self.assertAlmostEqual(self.v("input * 2 + Math.sin(time * 3)", input=3, time=0), 6.0)
        self.assertAlmostEqual(self.v("Math.PI"), math.pi)
        self.assertEqual(self.v("Math.max(1, 5, 3)"), 5)
        self.assertEqual(self.v("clamp(input, 0, 1)", input=4), 1)

    def test_logic_and_ternary(self):
        self.assertEqual(self.v("input > 0.5 ? 10 : 20", input=1), 10)
        self.assertEqual(self.v("input > 0.5 ? 10 : 20", input=0), 20)
        self.assertEqual(self.v("a && b", a=0, b=5), 0)
        self.assertEqual(self.v("a || b", a=0, b=5), 5)
        self.assertTrue(self.v("!0"))

    def test_cubic_bezier(self):
        self.assertAlmostEqual(self.v("cubicBezier(0, 0, 1, 1, 0.3)"), 0.3, places=4)
        self.assertEqual(self.v("cubicBezier(0.42, 0, 0.58, 1, 0)"), 0)
        self.assertEqual(self.v("cubicBezier(0.42, 0, 0.58, 1, 1)"), 1)
        self.assertLess(self.v("cubicBezier(0.42, 0, 0.58, 1, 0.25)"), 0.25)       # ease-in-out starts slow

    def test_wiggle_is_repeatable_and_bounded(self):
        a = self.v("wiggle(2, 30)", time=1.3)
        self.assertEqual(a, self.v("wiggle(2, 30)", time=1.3))
        self.assertTrue(all(abs(self.v("wiggle(3, 30)", time=t / 10)) <= 30 for t in range(100)))
        self.assertNotEqual(self.v("wiggle(2, 30, 1)", time=1.3), a)

    def test_lists_strings_and_length(self):
        self.assertEqual(self.v("[1, 2, 3][1]"), 2)
        self.assertEqual(self.v("[1, 2, 3].length"), 3)
        self.assertEqual(self.v("'a' + 1"), "a1")

    def test_division_by_zero_is_not_an_error_but_not_a_number_either(self):
        self.assertEqual(self.v("1 / 0"), math.inf)
        self.assertEqual(expr.safe("1 / 0", default=7.0), 7.0)

    def test_what_has_no_number_is_not_an_error_either(self):
        """sin(Infinity), floor(1 / 0)…: Python's math raises there (ValueError, OverflowError), which safe() does not catch -
        the renderers would have stopped on it. As in JavaScript they are NaN, so safe() gives its default."""
        for text in ("sin(1 / 0)", "floor(1 / 0)", "round(0 / 0)", "noise(1 / 0)", "random(1 / 0)", "(1 / 0) % 2", "[1, 2][1 / 0]",
                     "[1, 2][0 / 0]", "wiggle(1 / 0, 1)", "trunc(0 / 0)"):
            self.assertEqual(expr.safe(text, {"time": 1.0}, default=7.0), 7.0 if text[0] != "[" else 0.0, text)
        self.assertEqual(expr.evaluate("'x' + 1 / 0"), "xinf")

    def test_names(self):
        self.assertEqual(expr.names("input * k + Math.sin(time) + pi"), {"input", "k", "time"})

    def test_bad_expressions(self):
        for bad in ("", "1 +", "1 2", "a.b", "foo(", "1 ? 2", "#"):
            self.assertIsNotNone(expr.check(bad), bad)
        for bad in ("nothing", "sin", "unknown(1)", "sin(1, 2)"):
            with self.assertRaises(expr.ExprError, msg=bad):
                self.v(bad)
        self.assertEqual(expr.safe("nothing", default=3.0), 3.0)

    def test_nothing_python_reaches(self):
        for bad in ("__import__('os')", "().__class__", "input.__class__", "open('x')", "[].append(1)"):
            self.assertTrue(expr.check(bad) is not None or self._fails(bad), bad)

    def _fails(self, text):
        try:
            self.v(text, input=1.0)
        except expr.ExprError:
            return True
        return False

    def test_limits(self):
        self.assertIsNotNone(expr.check("1+" * 2000 + "1"))
        self.assertIsNotNone(expr.check("(" * 100 + "1" + ")" * 100))


if __name__ == "__main__":
    unittest.main()

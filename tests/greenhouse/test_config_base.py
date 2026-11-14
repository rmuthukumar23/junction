"""The strict table reader and hidden-parameter resolution every schema builds on."""
import dataclasses
import tomllib
import unittest

from envkit.rng import Rng
from greenhouse.config.base import ConfigError, Range, Table, ranges, resolve

DOC = tomllib.loads("""
id = "x"
density = 20
area = {min = 10, max = 20}
[nested]
height = 4.5
""")


@dataclasses.dataclass(frozen=True)
class Inner:
    height: float


@dataclasses.dataclass(frozen=True)
class Spec:
    id: str
    density: float
    area: float | Range
    inner: Inner


def parse(raw: dict) -> Spec:
    t = Table(raw, "test.toml")
    spec = Spec(t.str("id"), t.num("density", lo=0), t.param("area", lo=0), Inner(t.num("nested.height")))
    t.done()
    return spec


class TableTests(unittest.TestCase):
    def test_reads_a_valid_document(self):
        spec = parse(DOC)
        self.assertEqual(spec.area, Range("area", 10.0, 20.0))
        self.assertEqual(spec.inner.height, 4.5)

    def test_missing_key_names_file_and_key(self):
        with self.assertRaisesRegex(ConfigError, r"test.toml: missing key 'nested.height'"):
            parse({**DOC, "nested": {}})

    def test_stray_key_is_rejected(self):
        with self.assertRaisesRegex(ConfigError, r"unknown key\(s\) \['nested.heigth'\]"):
            parse({**DOC, "nested": {"height": 4.5, "heigth": 5}})

    def test_out_of_range_and_wrong_type(self):
        with self.assertRaisesRegex(ConfigError, "'density' must be >= 0"):
            parse({**DOC, "density": -1})
        with self.assertRaisesRegex(ConfigError, "'density' must be a number"):
            parse({**DOC, "density": "20"})
        with self.assertRaisesRegex(ConfigError, "min <= max"):
            parse({**DOC, "area": {"min": 5, "max": 1}})


class ResolveTests(unittest.TestCase):
    def test_draws_are_seeded_and_within_range(self):
        spec = parse(DOC)
        a, b = resolve(spec, Rng(1)), resolve(spec, Rng(1))
        self.assertEqual(a, b)
        self.assertTrue(10 <= a.area <= 20)
        self.assertNotEqual(resolve(spec, Rng(2)).area, a.area)

    def test_a_draw_depends_only_on_its_own_key(self):
        """Adding a parameter elsewhere must not shift this one."""
        self.assertEqual(Range("area", 10, 20).draw(Rng(3)), Range("area", 10, 20).draw(Rng(3)))
        self.assertNotEqual(Range("area", 10, 20).draw(Rng(3)), Range("other", 10, 20).draw(Rng(3)))

    def test_published_ranges(self):
        self.assertEqual(ranges(parse(DOC)), {"area": (10.0, 20.0)})


if __name__ == "__main__":
    unittest.main()

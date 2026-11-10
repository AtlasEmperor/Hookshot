"""The shader list is made again only when the game files or the census it is made from changed. Game-free.

python -I -B tests/test_shader_list_reuse.py
"""
import ast
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / "nx2" / "make_game.py"
spec = importlib.util.spec_from_file_location("make_game_under_test", SOURCE)
make_game = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_game)


def census_step(source, filename):
    """main's own shader list statement: the one that runs shader_census_cmd"""
    main = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == "main")
    def census(node):
        return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "shader_census_cmd"
    step = next(node for node in main.body if isinstance(node, ast.If) and any(census(call) for call in ast.walk(node)))
    return compile(ast.Module(body=[step], type_ignores=[]), filename, "exec")


STEP = census_step(SOURCE.read_text(encoding="utf-8"), str(SOURCE))


class ShaderListReuseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="hookshot-shader-list-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.romfs, self.out = root / "romfs", root / "game"
        (self.romfs / "Pack").mkdir(parents=True)
        (self.romfs / "Pack" / "ZsDic.pack.zs").write_bytes(b"authored dictionaries")
        (self.romfs / "Shader").mkdir()
        self.archive = self.romfs / "Shader" / "authored.bfsha.zs"
        self.archive.write_bytes(b"authored shader archive")
        self.out.mkdir()
        self.censuses = 0
        self.census_fails = False

    def make(self):
        def run(cmd, check=True, output=None, **kwargs):
            self.assertTrue(cmd[-3].endswith(self.romfs.name))
            self.assertEqual(cmd[-2:], ["--out", str(self.out / make_game.SHADER_LIST)])
            self.censuses += 1
            if self.census_fails:
                (self.out / make_game.SHADER_LIST).write_bytes(b"HKSEED01 cut short")
                return 1
            (self.out / make_game.SHADER_LIST).write_bytes(b"HKSEED01 authored list %d" % self.censuses)
            return 0
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            exec(STEP, dict(make_game.__dict__, romfs=str(self.romfs), out=str(self.out), run=run))
        return printed.getvalue()

    def test_the_same_game_files_keep_the_list(self):
        self.make()
        said = self.make()
        self.assertEqual(self.censuses, 1)
        self.assertIn("making it again is skipped", said)

    def test_a_changed_archive_makes_the_list_again(self):
        self.make()
        self.archive.write_bytes(b"authored shader archive, another release")
        self.make()
        self.assertEqual(self.censuses, 2)

    def test_a_new_archive_makes_the_list_again(self):
        self.make()
        (self.romfs / "Shader" / "another.bfsha.zs").write_bytes(b"authored second archive")
        self.make()
        self.assertEqual(self.censuses, 2)

    def test_another_census_makes_the_list_again(self):
        self.make()
        real_open = open
        census = os.path.join(make_game.HERE, "shader_census.py")

        def edited(path, *args, **kwargs):   # (the census as if it had changed)
            if os.fspath(path) == census:
                return io.BytesIO(b"# an edit\n")
            return real_open(path, *args, **kwargs)
        with mock.patch("builtins.open", edited):
            self.make()
        self.assertEqual(self.censuses, 2)

    def test_a_list_rewritten_since_is_made_again(self):
        self.make()
        seed = self.out / make_game.SHADER_LIST
        seed.write_bytes(b"HKSEED01 another builder's list")
        os.utime(seed, ns=(1, 1))
        self.make()
        self.assertEqual(self.censuses, 2)

    def test_a_failed_census_is_not_vouched_for(self):
        self.make()
        self.archive.write_bytes(b"authored shader archive, another release")
        self.census_fails = True
        said = self.make()
        self.assertIn("the shader list was not made", said)
        self.assertFalse((self.out / make_game.SHADER_LIST_KEY).exists())
        self.census_fails = False
        self.make()
        self.assertEqual(self.censuses, 3)


if __name__ == "__main__":
    unittest.main()

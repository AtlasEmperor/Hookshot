"""Keeping all the build files after a build is one setting: --keep-build-files, else HOOKSHOT_KEEP_BUILD_FILES. Game-free.

python -I -B tests/test_keep_build_files.py
"""
import argparse
import ast
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / "nx2" / "make_game.py"
spec = importlib.util.spec_from_file_location("make_game_under_test", SOURCE)
make_game = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_game)


def cleanup_step(source, filename):
    """main's own end-of-build cleanup of the work folder: the statement that prunes the object cache"""
    main = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == "main")

    def prunes(node):
        return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "prune_object_cache"
    step = next(node for node in main.body if isinstance(node, ast.If) and any(prunes(call) for call in ast.walk(node)))
    return compile(ast.Module(body=[step], type_ignores=[]), filename, "exec")


CLEANUP = cleanup_step(SOURCE.read_text(encoding="utf-8"), str(SOURCE))


class KeepBuildFilesTests(unittest.TestCase):
    def test_the_flag_wins_over_the_variable(self):
        for variable, given, expected in ((None, None, False), ("", None, False), ("0", None, False), ("1", None, True),
                                          ("yes", None, True), ("1", False, False), ("0", True, True), (None, True, True)):
            with self.subTest(variable=variable, given=given):
                environment = {k: v for k, v in os.environ.items() if k != "HOOKSHOT_KEEP_BUILD_FILES"}
                if variable is not None:
                    environment["HOOKSHOT_KEEP_BUILD_FILES"] = variable
                with mock.patch.dict(os.environ, environment, clear=True):
                    self.assertEqual(make_game.keep_build_files(given), expected)

    def test_the_variable_says_whether_it_decides(self):
        for variable, expected in ((None, None), ("", None), ("0", False), ("1", True)):
            with self.subTest(variable=variable):
                environment = {k: v for k, v in os.environ.items() if k != "HOOKSHOT_KEEP_BUILD_FILES"}
                if variable is not None:
                    environment["HOOKSHOT_KEEP_BUILD_FILES"] = variable
                with mock.patch.dict(os.environ, environment, clear=True):
                    self.assertIs(make_game.keep_build_files_variable(), expected)

    def test_the_command_line_takes_both_forms(self):
        for argv, expected in ((["--keep-build-files"], True), (["--no-keep-build-files"], False), ([], None)):
            with self.subTest(argv=argv), mock.patch.object(sys, "argv", ["make_game.py", "--out", "authored"] + argv):
                self.assertIs(make_game.parse_args().keep_build_files, expected)


class CleanupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="hookshot-keep-build-files-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.work, self.exefs = self.root / "work", self.root / "work" / "exefs"
        for folder in (self.exefs, self.work / "sa" / "gen", self.work / "probe", self.work / "objcache"):
            folder.mkdir(parents=True)
        (self.work / "sa" / "gen" / "code_000.c").write_text("/* authored translation */\n")

    def clean(self, given):
        environment = {k: v for k, v in os.environ.items() if k != "HOOKSHOT_KEEP_BUILD_FILES"}
        printed = io.StringIO()
        with mock.patch.dict(os.environ, environment, clear=True), contextlib.redirect_stdout(printed):
            exec(CLEANUP, dict(make_game.__dict__, work=str(self.work), exefs=str(self.exefs), ROOT=str(self.root / "tools"),
                               a=argparse.Namespace(keep_build_files=given)))
        return printed.getvalue()

    def test_kept_build_files_stay_whole(self):
        self.clean(True)
        self.assertTrue((self.work / "sa" / "gen" / "code_000.c").is_file())
        self.assertTrue((self.work / "probe").is_dir())
        self.assertFalse(self.exefs.exists())

    def test_by_default_the_translation_goes(self):
        said = self.clean(None)
        self.assertFalse((self.work / "sa").exists())
        self.assertFalse((self.work / "probe").exists())
        self.assertIn("were deleted but this build's compiled objects", said)

    def test_files_still_in_use_are_said(self):
        remove = shutil.rmtree

        def held(path, *args, **kwargs):   # (a file of sa held by another program: ignore_errors leaves it)
            if Path(path) == self.work / "sa":
                return
            return remove(path, *args, **kwargs)
        with mock.patch.object(shutil, "rmtree", held):
            said = self.clean(False)
        self.assertIn("could not all be deleted (a file in use)", said)
        self.assertIn(str(self.work / "sa"), said)
        self.assertNotIn("were deleted", said)


if __name__ == "__main__":
    unittest.main()

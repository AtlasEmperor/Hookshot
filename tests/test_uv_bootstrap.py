"""nx2/bootstrap.py, game-free: shell paths, what downloads nothing, the release's tool parts and what may be extracted of them.

python -I -B tests/test_uv_bootstrap.py
"""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hookshot_bootstrap", ROOT / "nx2" / "bootstrap.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)
SETUP = bootstrap.setup_parts()   # (the Python builder's own setup module: its Part and its errors)
BUILDER_PARTS = "https://github.com/owner/repo/releases/download/builder-parts/"


def part(sha, name):
    """A setup list part line as setup_parts reads it"""
    if name == "llvm-mingw":
        return SETUP.Part(sha, 1, "HookshotBuilder/tools", "llvm-mingw-20261104-ucrt-x86_64", "llvm-mingw",
                          "https://github.com/mstorsjo/llvm-mingw/releases/download/20261104/llvm-mingw-20261104-ucrt-x86_64.zip")
    return SETUP.Part(sha, 1, ".", "-", "-", BUILDER_PARTS + "HookshotBuilder-%s-%s.zip" % (name, sha[:12]))


RELEASE = [part("%064x" % index, name)
           for index, name in enumerate(("app", "dotnet", "python", "emsdk", "cpm", "third_party", "wgpu-native", "llvm-mingw"), 1)]
ZIP_FILES = {
    "app": {"HookshotBuilder/HookshotBuilder.dll": b"builder", "HookshotBuilder/tools/nx2/make_game.py": b"the release's sources",
            "HookshotBuilder/tools/work/hot_funcs.txt": b"profile"},
    "cpm": {"HookshotBuilder/tools/cpm/vulkanheaders/v1/include/vulkan/vulkan.h": b"header"},
    "wgpu-native": {"HookshotBuilder/tools/wgpu-native/include/webgpu/webgpu.h": b"header"},
    "third_party": {"HookshotBuilder/tools/third_party/sdl2/SDL2.dll": b"sdl2",
                    "HookshotBuilder/tools/third_party/sdl2/SDL3.dll": b"sdl3",
                    "HookshotBuilder/tools/third_party/a64-kit/tools/toolchain.py": b"the release's sources"},
    "llvm-mingw": {"llvm-mingw-20261104-ucrt-x86_64/bin/clang.exe": b"compiler"},
}


class FakeSetup:
    """setup_parts' list reader and part downloader over authored zips; nothing leaves the machine"""
    SetupError = SETUP.SetupError

    def __init__(self, answers=True):
        self.answers, self.downloads = answers, []

    def read_manifest(self, status):
        if not self.answers:
            raise SETUP.SetupError("Could not reach GitHub (authored)")
        return "v2.0.14", RELEASE

    def download_part(self, status, progress, p, i, n, zpath, cancel):
        self.downloads.append(bootstrap.part_name(p))
        with zipfile.ZipFile(zpath, "w") as archive:
            for name, data in ZIP_FILES[bootstrap.part_name(p)].items():
                archive.writestr(name, data)


class BootstrapTests(unittest.TestCase):
    def test_paths_are_read_against_the_shell_folder(self):
        cwd = Path(tempfile.gettempdir(), "hookshot-shell").resolve()
        argv = ["--out", "game", "--work=cache", "--language", "fr", "--exefs", "../exefs", "--log", "build.log",
                "--game", "game.nup"]
        self.assertEqual(bootstrap.source_arguments(argv, cwd), [
            "--out", str(cwd / "game"), "--work=" + str(cwd / "cache"), "--language", "fr",
            "--exefs", str((cwd / "../exefs").resolve()), "--log", str(cwd / "build.log"), "--game", str(cwd / "game.nup")])

    def test_windows_absolute_paths_stay_as_given(self):
        cwd = Path(tempfile.gettempdir())
        self.assertEqual(bootstrap.absolute_path(r"G:\Games\Hookshot", cwd), r"G:\Games\Hookshot")
        self.assertEqual(bootstrap.absolute_path(r"\\server\share\game", cwd), r"\\server\share\game")

    def test_help_downloads_nothing(self):
        for argv in ([], ["--help"], ["-h"]):
            with self.subTest(argv=argv), patch.object(bootstrap, "windows_host", return_value=True), \
                    patch.object(bootstrap, "ensure_tools", side_effect=AssertionError("download")), \
                    patch.object(bootstrap, "run_builder", return_value=0) as run:
                self.assertEqual(bootstrap.main(argv), 0)
                run.assert_called_once()

    def test_a_windows_build_or_check_fetches_the_release_tools(self):
        # (--check tests the compiler before it reads the game: it needs the tools as a build does)
        for argv in (["--nup", "input.nup", "--out", "game"], ["--check", "--nup", "input.nup"]):
            with self.subTest(argv=argv), tempfile.TemporaryDirectory() as tmp:
                tools = {name: Path(tmp, name) for name in bootstrap.TOOL_PARTS}
                with patch.object(bootstrap, "windows_host", return_value=True), \
                        patch.dict(os.environ, {"LOCALAPPDATA": tmp}, clear=True), \
                        patch.object(bootstrap, "ensure_tools", return_value=tools) as ensure, \
                        patch.object(bootstrap, "stage_local_resources"), \
                        patch.object(bootstrap, "run_builder", return_value=0) as run:
                    self.assertEqual(bootstrap.main(argv), 0)
                self.assertEqual(ensure.call_args.args[0], Path(tmp) / "HookshotBuilder" / "deps")
                self.assertEqual(run.call_args.args[2]["RX_CPM"], str(Path(tmp, "cpm", "cpm")))

    def test_linux_builds_without_the_windows_tools(self):
        with patch.object(bootstrap, "windows_host", return_value=False), \
                patch.object(bootstrap, "ensure_tools", side_effect=AssertionError("download")), \
                patch.object(bootstrap, "run_builder", return_value=7):
            self.assertEqual(bootstrap.main(["--out", "game"]), 7)

    def test_the_callers_tools_and_msvc_are_kept(self):
        shell = Path(tempfile.gettempdir(), "shell")
        tools = {name: Path(tempfile.gettempdir(), "parts", name) for name in bootstrap.TOOL_PARTS}
        with patch.dict(os.environ, {"HOOKSHOT_MINGW": "custom", "RX_CPM": "cpm", "WGPU_NATIVE": "wgpu", "HOOKSHOT_NGX_SDK": "ngx",
                                     "HOOKSHOT_MSVC": "1", "PATH": "original"}, clear=True):
            env = bootstrap.build_environment(tools, shell)
        self.assertEqual(env["PATH"], "original")
        self.assertEqual(env["HOOKSHOT_MSVC"], "1")
        self.assertEqual(env["RX_CPM"], str((shell / "cpm").resolve()))
        self.assertEqual(env["HOOKSHOT_NGX_SDK"], str((shell / "ngx").resolve()))

    def test_the_visual_studio_route_is_never_given_the_release_compiler(self):
        # (CONTRIBUTING.md: HOOKSHOT_MSVC=1 forces the Visual Studio route; toolchain.py takes HOOKSHOT_MINGW whenever it is set)
        tools = {name: Path(tempfile.gettempdir(), "parts", name) for name in bootstrap.TOOL_PARTS}
        with patch.dict(os.environ, {"HOOKSHOT_MSVC": "1", "PATH": "original"}, clear=True):
            env = bootstrap.build_environment(tools, Path(tempfile.gettempdir(), "shell"))
        self.assertNotIn("HOOKSHOT_MINGW", env)
        self.assertEqual(env["PATH"], "original")
        self.assertEqual(env["RX_CPM"], str(tools["cpm"] / "cpm"))

    def test_the_release_compiler_is_the_default(self):
        tools = {name: Path(tempfile.gettempdir(), "parts", name) for name in bootstrap.TOOL_PARTS}
        with patch.dict(os.environ, {"PATH": "original"}, clear=True):
            env = bootstrap.build_environment(tools, Path(tempfile.gettempdir(), "shell"))
        self.assertEqual(env["HOOKSHOT_MINGW"], str(tools["llvm-mingw"] / "llvm-mingw"))
        self.assertEqual(env["WGPU_NATIVE"], str(tools["wgpu-native"] / "wgpu-native"))
        self.assertTrue(env["PATH"].startswith(str(tools["llvm-mingw"] / "llvm-mingw" / "bin") + os.pathsep))

    def test_the_build_driver_runs_in_utf8_mode_and_its_exit_code_is_returned(self):
        with patch.object(bootstrap.subprocess, "call", return_value=3) as call:
            self.assertEqual(bootstrap.run_builder(ROOT, ["--out", "game"]), 3)
        self.assertEqual(call.call_args.kwargs["cwd"], ROOT)
        self.assertEqual(call.call_args.args[0][:5], [bootstrap.sys.executable, "-I", "-u", "-X", "utf8"])

    def test_only_the_tool_parts_of_the_release_are_taken(self):
        self.assertEqual(sorted(bootstrap.tool_parts(RELEASE)), sorted(bootstrap.TOOL_PARTS))
        with self.assertRaisesRegex(bootstrap.BootstrapError, "no cpm part"):
            bootstrap.tool_parts([p for p in RELEASE if bootstrap.part_name(p) != "cpm"])

    def test_archive_paths_cannot_leave_their_folder(self):
        for name in ("../escape", "a/../b", "a/./b", "C:/escape", "bad:name", "a//b", "trailing.", "trailing "):
            with self.subTest(name=name), self.assertRaises(bootstrap.BootstrapError):
                bootstrap.safe_archive_path(name)

    def test_a_part_gives_only_the_folder_a_build_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "app.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                for name, data in ZIP_FILES["app"].items():
                    archive.writestr(name, data)
            dest = Path(tmp) / "dest"
            bootstrap.extract_part(zip_path, "HookshotBuilder/tools/work/", "work/", dest)
            self.assertEqual(sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()), ["work/hot_funcs.txt"])
            self.assertEqual((dest / "work/hot_funcs.txt").read_bytes(), b"profile")

    def test_names_that_differ_only_by_case_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "duplicate.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("tools/llvm-mingw/bin/clang.exe", b"a")
                archive.writestr("tools/llvm-mingw/bin/CLANG.exe", b"b")
            with self.assertRaisesRegex(bootstrap.BootstrapError, "Duplicate Windows filename"):
                bootstrap.extract_part(zip_path, "tools/", "", Path(tmp) / "dest")

    def test_the_tools_are_fetched_once_per_part_and_kept(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(bootstrap, "validate_tools"):
            deps, setup = Path(tmp) / "deps", FakeSetup()
            with patch.object(bootstrap, "setup_parts", return_value=setup):
                tools = bootstrap.ensure_tools(deps)
                self.assertEqual(sorted(setup.downloads), sorted(bootstrap.TOOL_PARTS))
                self.assertEqual((tools["llvm-mingw"] / "llvm-mingw/bin/clang.exe").read_bytes(), b"compiler")
                self.assertEqual((tools["third_party"] / "third_party/sdl2/SDL3.dll").read_bytes(), b"sdl3")
                self.assertFalse((tools["third_party"] / "third_party/a64-kit").exists())
                self.assertFalse((tools["app"] / "nx2").exists())
                self.assertEqual(list((deps / "downloads").iterdir()), [])
                again = bootstrap.ensure_tools(deps)
            self.assertEqual(again, tools)
            self.assertEqual(len(setup.downloads), len(bootstrap.TOOL_PARTS))

    def test_the_tools_taken_last_are_used_when_github_does_not_answer(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(bootstrap, "validate_tools"):
            deps = Path(tmp) / "deps"
            with patch.object(bootstrap, "setup_parts", return_value=FakeSetup(answers=False)), \
                    self.assertRaisesRegex(bootstrap.BootstrapError, "Could not reach GitHub"):
                bootstrap.ensure_tools(deps)
            with patch.object(bootstrap, "setup_parts", return_value=FakeSetup()):
                tools = bootstrap.ensure_tools(deps)
            with patch.object(bootstrap, "setup_parts", return_value=FakeSetup(answers=False)):
                self.assertEqual(bootstrap.ensure_tools(deps), tools)

    def test_the_clones_own_profile_files_are_kept_whole(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            tools = {"third_party": Path(tmp) / "third_party", "app": Path(tmp) / "app"}
            for root, names in ((tools["third_party"], bootstrap.SDL_FILES), (tools["app"], bootstrap.PROFILE_FILES)):
                for rel in names:
                    (root / rel).parent.mkdir(parents=True, exist_ok=True)
                    (root / rel).write_bytes(b"release")
            first = repo / bootstrap.PROFILE_FILES[0]
            first.parent.mkdir(parents=True, exist_ok=True)
            first.write_bytes(b"custom")
            bootstrap.stage_local_resources(repo, tools)
            self.assertEqual(first.read_bytes(), b"custom")
            self.assertFalse((repo / bootstrap.PROFILE_FILES[1]).exists())
            self.assertEqual((repo / bootstrap.SDL_FILES[0]).read_bytes(), b"release")


if __name__ == "__main__":
    unittest.main()

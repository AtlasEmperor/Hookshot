"""The update tracks (release, release candidate, nightly): which track a version is on and the version order, the same in
the game's update check (host/hos_update.c, compiled here from its own text), the setup (builder/setup/setup.c) and the
Linux updater (builder/linux/linux_update.py). Updater.cs has the same rules; tests/test_updater_cases.py runs it on these cases.
The cases of the three copies are in tests/update_cases.json: each says which copies it holds for."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "builder" / "linux"))
import linux_update  # noqa: E402

CC = "gcc"
CASES = json.loads((ROOT / "tests" / "update_cases.json").read_text(encoding="utf-8"))["cases"]
# (what each kind of case runs on: the game's C holds the track as the nightly flag, and the order of releases and release candidates)
DEFAULT_COPIES = {"track": ("python", "csharp", "c"), "newer": ("python", "csharp", "c"), "target": ("python", "csharp"),
                  "builds_here": ("csharp",), "game_needs_update": ("python", "csharp"), "offer": ("c",)}

# (version, track)
TRACKS = [
    ("v2.0.7", "release"), ("v2.1.0", "release"),
    ("v2.1.0-rc.1", "rc"), ("v2.1.0-rc.12", "rc"),
    ("v2.1.0-rc.1-3-g1a2b3c4", "nightly"), ("v2.1.0-rc.1-0-g1a2b3c4", "nightly"), ("v2.0.14-12-gabcdef01", "nightly"),
    ("v2.0.5-3-g1a2b3c4-dirty", "nightly"),
]
# newer, older (semver: a release candidate before its release, rc.N by number)
ORDER = [
    ("v2.1.0-rc.2", "v2.1.0-rc.1"), ("v2.1.0-rc.10", "v2.1.0-rc.9"), ("v2.1.0", "v2.1.0-rc.2"), ("v2.1.0-rc.1", "v2.0.14"),
    ("v2.0.10", "v2.0.9"), ("v3.0.0-rc.1", "v2.9.9"),
]

# (the rolling releases, nightly and rc, and the parts releases are not versions: every track's list leaves them out)
LIST = """[{"tag_name":"nightly","draft":false},{"tag_name":"rc","draft":false,"prerelease":true},
{"tag_name":"v2.1.0-rc.2","draft":false},{"tag_name":"linux-parts"},
{"tag_name":"v2.1.0-rc.10","draft":false},{"tag_name":"v2.0.14","draft":false},{"tag_name":"v2.1.0-rc.9"}]"""

FIXTURE = r"""
#include <stdio.h>
/* PORTABLE */
/* SETUP */
int main(int argc, char **argv) {
    if (argc == 3 && argv[1][0] == 'n') return printf("%d %d\n", nightly_version(argv[2]), nightly_tag(argv[2])), 0;
    if (argc == 4 && argv[1][0] == 'o') return printf("%d\n", newer_version(argv[2], argv[3])), 0;
    if (argc == 4 && argv[1][0] == 'p') return printf("%d\n", offer_wanted(argv[2], argv[3])), 0;
    if (argc == 3 && argv[1][0] == 'l') {
        char tag[128] = "";
        FILE *f = fopen(argv[2], "rb");
        static char body[1 << 16];
        body[fread(body, 1, sizeof body - 1, f)] = 0;
        fclose(f);
        return printf("%s\n", newest_tag(body, tag, sizeof tag) ? tag : "-"), 0;
    }
    return 2;
}
"""


def python_result(kind, args):
    """A case's answer from builder/linux/linux_update.py"""
    if kind == "track":
        return linux_update.track_of(args[0])
    if kind == "newer":
        newer, older = (linux_update.release_key(version) for version in args)
        return newer is not None and older is not None and newer > older
    if kind == "game_needs_update":
        return linux_update.game_needs_update(*args)
    latest, tools, track = args
    return linux_update.update_target(latest, tools, switch=track != linux_update.track_of(tools))


def portable(source):
    start = source.index("#if defined(_WIN32) || defined(__linux__)")
    end = source.index("#endif", source.index("static int newest_tag("))
    return source[start:end].replace("#if defined(_WIN32) || defined(__linux__)", "", 1)


def setup_part(source):
    start = source.index("static int nightly_tag(")
    return source[start:source.index("\n}\n", start) + 3]


class Tracks(unittest.TestCase):
    exe = None

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="hookshot-tracks-")
        folder = Path(cls.tmp.name)
        code = FIXTURE.replace("/* PORTABLE */", "#include <ctype.h>\n#include <stdlib.h>\n#include <string.h>\n" +
                               portable((ROOT / "host/hos_update.c").read_text(encoding="utf-8")))
        code = code.replace("/* SETUP */", setup_part((ROOT / "builder/setup/setup.c").read_text(encoding="utf-8")))
        (folder / "t.c").write_text(code, encoding="utf-8")
        cls.exe = str(folder / "t")
        subprocess.run([CC, "-std=c11", "-Wall", "-Wextra", "-Werror", str(folder / "t.c"), "-o", cls.exe], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def c(self, *args):
        return subprocess.run([self.exe, *args], capture_output=True, text=True, check=True).stdout.split()

    def test_the_cases_every_copy_holds(self):
        kinds = {"python": set(), "c": set()}
        for case in CASES:
            kind, args, expect = case["kind"], case["args"], case["expect"]
            copies = case.get("copies", DEFAULT_COPIES[kind])
            if "python" in copies:
                self.assertEqual(python_result(kind, args), expect, case)
                kinds["python"].add(kind)
            if "c" in copies:
                if kind == "track":
                    nightly = "1" if expect == "nightly" else "0"
                    self.assertEqual(self.c("n", args[0]), [nightly, nightly], case)
                else:
                    command = "p" if kind == "offer" else "o"
                    self.assertEqual(self.c(command, *args), ["1" if expect else "0"], case)
                kinds["c"].add(kind)
        self.assertEqual(kinds, {"python": {"track", "newer", "target", "game_needs_update"}, "c": {"track", "newer", "offer"}})

    def test_the_track_of_a_version(self):
        for version, track in TRACKS + [("nightly", "release"), ("rc", "release"), ("dev", "release")]:
            self.assertEqual(linux_update.track_of(version), track, version)
            nightly = "1" if track == "nightly" else "0"
            self.assertEqual(self.c("n", version), [nightly, nightly], version)

    def test_semver_order(self):
        for newer, older in ORDER:
            self.assertGreater(linux_update.release_key(newer), linux_update.release_key(older), (newer, older))
            self.assertEqual(self.c("o", newer, older), ["1"], (newer, older))
            self.assertEqual(self.c("o", older, newer), ["0"], (older, newer))
            self.assertEqual(self.c("o", newer, newer), ["0"])

    def test_the_newest_release_candidate_or_release(self):
        path = Path(self.tmp.name) / "list.json"
        path.write_text(LIST, encoding="utf-8")
        self.assertEqual(self.c("l", str(path)), ["v2.1.0-rc.10"])
        self.assertIsNone(linux_update.release_key("rc"))
        self.assertEqual(linux_update.newest_release(["rc", "nightly"]), None)
        get = lambda url: LIST.encode() if url == linux_update.RELEASES_API else b"{}"   # noqa: E731
        self.assertEqual(linux_update.latest_tag(get, "rc"), "v2.1.0-rc.10")
        # (its version's release ships: the release is the newest)
        released = LIST.replace("v2.0.14", "v2.1.0")
        path.write_text(released, encoding="utf-8")
        self.assertEqual(self.c("l", str(path)), ["v2.1.0"])
        self.assertEqual(linux_update.latest_tag(lambda url: released.encode(), "rc"), "v2.1.0")

    def test_each_track_asks_its_own_release(self):
        asked = []

        def get(url):
            asked.append(url)
            if url == linux_update.RELEASES_API:
                raise OSError("rate limited")
            if url == linux_update.LATEST_API:
                return b'{"tag_name": "v2.0.14"}'
            if url.endswith("/releases/download/nightly/hookshot-linux.txt"):
                return ("tag v2.1.0-rc.1-3-g1a2b3c4\npart %s 10 usr/share/hookshot https://example.invalid/a.zip\nfile x\n"
                        % ("a" * 64)).encode()
            raise OSError(url)
        self.assertEqual(linux_update.latest_tag(get), "v2.0.14")
        self.assertEqual(asked, [linux_update.LATEST_API])   # (a release: as before, the latest release only)
        self.assertEqual(linux_update.latest_tag(get, "rc"), "v2.0.14")   # (no API answer: the latest release)
        self.assertEqual(linux_update.latest_tag(get, "nightly"), "v2.1.0-rc.1-3-g1a2b3c4")
        self.assertEqual(linux_update.list_url("v2.1.0-rc.1-3-g1a2b3c4"),
                         "https://github.com/NotRexed/Hookshot/releases/download/nightly/hookshot-linux.txt")
        self.assertEqual(linux_update.list_url("v2.1.0-rc.2"),
                         "https://github.com/NotRexed/Hookshot/releases/download/v2.1.0-rc.2/hookshot-linux.txt")
        self.assertEqual(linux_update.list_url(None), linux_update.LATEST_LIST)

    def test_what_each_track_updates_to(self):
        target = linux_update.update_target
        # a release candidate is never taken back to an older release, and is offered the next one and its release
        self.assertEqual(target("v2.0.14", "v2.1.0-rc.1"), "v2.1.0-rc.1")
        self.assertEqual(target("v2.1.0-rc.2", "v2.1.0-rc.1"), "v2.1.0-rc.2")
        self.assertEqual(target("v2.1.0", "v2.1.0-rc.2"), "v2.1.0")
        # a nightly takes the nightly's build whenever it is another one
        self.assertEqual(target("v2.1.0-rc.1-5-gbbbbbbb", "v2.1.0-rc.1-3-gaaaaaaa"), "v2.1.0-rc.1-5-gbbbbbbb")
        # a switch of track takes its newest, an older version too
        self.assertEqual(target("v2.0.14", "v2.1.0-rc.1", switch=True), "v2.0.14")
        self.assertEqual(target("v2.0.14", "v2.1.0-rc.1-3-gaaaaaaa", switch=True), "v2.0.14")
        self.assertEqual(linux_update.choose_mode(None, "v2.1.0-rc.1", "v2.0.14", False, False), "build")
        self.assertEqual(linux_update.choose_mode(None, "v2.1.0-rc.1", "v2.0.14", False, False, True), "update-builder")
        self.assertEqual(linux_update.choose_mode("v2.1.0-rc.1", "v2.1.0-rc.1", "v2.1.0-rc.2", False, True), "update-game")

    def test_the_builders_offer_an_update_only_through_the_game_rule(self):
        window = (ROOT / "builder/HookshotBuilder/MainWindow.xaml.cs").read_text(encoding="utf-8")
        linux = (ROOT / "builder/linux/hookshot_builder.py").read_text(encoding="utf-8")
        # (the window and the launcher page offer the update by the same rule)
        self.assertEqual(window.count("Updater.GameNeedsUpdate(game, updateTarget, Switching)"), 3)
        self.assertNotIn("game != updateTarget", window)
        self.assertIn("offered = linux_update.game_needs_update(game, target, self.switching())", linux)
        self.assertNotIn("game != target", linux)

    def test_the_game_offers_a_release_or_a_candidate_only_a_newer_one(self):
        source = (ROOT / "host/hos_update.c").read_text(encoding="utf-8")
        guard = "if (!offer_wanted(have, tag)) return;"
        self.assertEqual(source.count(guard), 2)   # (Windows and Linux)
        self.assertEqual(source.count("if (!latest_tag(have, tag, sizeof tag)) {"), 2)


if __name__ == "__main__":
    if "--cc" in sys.argv:
        i = sys.argv.index("--cc")
        CC = sys.argv[i + 1]
        del sys.argv[i:i + 2]
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    unittest.main()

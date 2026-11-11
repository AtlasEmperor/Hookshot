"""The Linux builder's update from the game's offer (--update <folder> --tag <release>): the folder is built again only when these
tools build something the folder is not, a Track saved in the builder does not make the offer install another release, and the
builder's own updates (the Update button, the folder after a download) are left as they are. The real Builder.begin_update runs
with its collaborators replaced; no Tk is imported."""
import ast
from pathlib import Path
import queue
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "builder" / "linux"))
import linux_update  # noqa: E402

SOURCE = ROOT / "builder" / "linux" / "hookshot_builder.py"
builder = next(node for node in ast.parse(SOURCE.read_text(encoding="utf-8")).body
               if isinstance(node, ast.ClassDef) and node.name == "Builder")
begin_update = next(node for node in builder.body if isinstance(node, ast.FunctionDef) and node.name == "begin_update")
BEGIN_UPDATE = compile(ast.Module(body=[begin_update], type_ignores=[]), str(SOURCE), "exec")

TOOLS = "v2.1.0"


class Harness:
    """A Builder whose tools are TOOLS, started by an update of folder; folder_game is the version the folder was built as"""

    def __init__(self, folder_game, tag, fetched=False, switching=False, latest="v2.0.14", tools=TOOLS):
        self.manifest_tags = []
        self.started = []
        self.lines = queue.Queue()
        fake_linux_update = SimpleNamespace(
            game_needs_update=linux_update.game_needs_update, update_target=linux_update.update_target,
            track_of=linux_update.track_of, running_root=lambda: "root", tools_tag=lambda root: tools,
            game_version=lambda folder: (folder_game, True), startup_manifest=self.startup_manifest,
            read_manifest=lambda root: None, install=lambda manifest, root, source, note: "apprun")

        class Immediate:
            """A thread that runs where it is started: the update's work is done when begin_update returns"""
            def __init__(self, target, daemon):
                self.target = target

            def start(self):
                self.target()

        fake_os = SimpleNamespace(environ={}, execv=lambda program, args: self.started.append(args))
        namespace = {"linux_update": fake_linux_update, "threading": SimpleNamespace(Thread=Immediate), "os": fake_os}
        exec(BEGIN_UPDATE, namespace)
        self.gui = SimpleNamespace(
            update_folder="folder", update_tag=tag, fetched=fetched, tools=tools, latest=latest, lines=self.lines,
            switching=lambda: switching, show_progress=lambda title: None)
        self.begin_update = lambda: namespace["begin_update"](self.gui)

    def startup_manifest(self, root, tag=None):
        self.manifest_tags.append(tag)
        return SimpleNamespace(tag=TOOLS if tag is None else tag)

    def outcome(self):
        self.begin_update()
        return self.lines.get_nowait()


class UpdateFromTheGamesOffer(unittest.TestCase):
    def test_a_folder_that_is_what_the_tools_build_is_left_alone(self):
        # (GitHub's latest link lags right after a publish: the game offers a release older than the tools)
        self.assertEqual(Harness(TOOLS, "v2.0.14").outcome(), ("up-to-date", "folder"))

    def test_a_folder_newer_than_the_tools_is_not_built_back_to_them(self):
        self.assertEqual(Harness("v2.1.1", "v2.0.14").outcome(), ("up-to-date", "folder"))

    def test_an_older_folder_is_built_with_the_tools(self):
        self.assertEqual(Harness("v2.0.5", "v2.0.14").outcome(), ("do-build", "folder"))

    def test_a_folder_that_names_no_release_is_built_with_the_tools(self):
        self.assertEqual(Harness("dev", "v2.0.14").outcome(), ("do-build", "folder"))

    def test_a_saved_track_does_not_make_the_offer_install_another_release(self):
        harness = Harness(TOOLS, "v2.0.14", switching=True)
        self.assertEqual(harness.outcome(), ("up-to-date", "folder"))
        self.assertEqual(harness.manifest_tags, [None])

    def test_a_release_candidate_offer_names_its_release(self):
        harness = Harness("v2.1.0-rc.1", "v2.1.0-rc.2", tools="v2.1.0-rc.1")
        harness.begin_update()
        self.assertEqual(harness.manifest_tags, ["v2.1.0-rc.2"])
        self.assertEqual(harness.started, [["apprun", "--update", "folder", "--tag", "v2.1.0-rc.2", "--fetched"]])

    def test_the_builders_own_update_rebuilds_a_folder_at_the_tools(self):
        # (the DLSS tick rebuilds a folder that is already what the tools build: no offer, no tag)
        self.assertEqual(Harness(TOOLS, None).outcome(), ("do-build", "folder"))

    def test_the_folder_after_a_download_is_built_whatever_its_version(self):
        self.assertEqual(Harness("v2.1.1", "v2.0.14", fetched=True).outcome(), ("do-build", "folder"))


if __name__ == "__main__":
    unittest.main()

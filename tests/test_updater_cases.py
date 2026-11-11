"""The Windows builder's update rules (the real builder/HookshotBuilder/Updater.cs, compiled as tests/test_updater_asset_digest.py
compiles it) on the cases of tests/update_cases.json that name the C# copy: the track of a version, the version order, what the
builder updates to and when a folder is built with the installed tools. tests/test_update_tracks.py runs the same file on the
Linux updater and the game's C."""
import argparse
import importlib.util
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--dotnet", "{dotnet}"]
RUN_ALL_SKIP = {"linux": "Windows Builder update policy; .NET 8 fixture exercised on Windows"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--dotnet", default="dotnet")
    args = parser.parse_args()
    dotnet = shutil.which(args.dotnet)
    if not dotnet:
        parser.error(".NET 8 SDK is required")
    spec = importlib.util.spec_from_file_location("updater_asset_digest", ROOT / "tests" / "test_updater_asset_digest.py")
    digest = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(digest)
    run = digest.run_fixture(dotnet, args.source, extra_files=["updater_cases_test.cs"], startup_object="CasesFixture.Program",
                             program_arguments=[str(ROOT / "tests" / "update_cases.json")])
    sys.exit(run.returncode)


if __name__ == "__main__":
    main()

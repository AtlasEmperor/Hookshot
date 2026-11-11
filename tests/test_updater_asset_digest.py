"""Exercise the actual Windows updater with authored HTTP/launch/temp-directory boundaries only."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--dotnet", "{dotnet}"]


# Aliases replace only external boundaries, never the real class's control flow or validation.
ALIASES = """using HttpClient = DigestFixture.FakeHttpClient;
using Process = DigestFixture.FakeProcess;
using Environment = DigestFixture.FakeEnvironment;
using AppContext = DigestFixture.FakeAppContext;
"""


def run_fixture(dotnet, source_root, extra_files=(), startup_object=None, program_arguments=(), **run_options):
    """Compile the entire real Updater.cs with the authored boundaries of tests/updater_asset_digest_test.cs and run the
    project: the digest fixture's own Main, or startup_object's when another fixture file (extra_files, in tests/) adds one."""
    source = (source_root / "builder/HookshotBuilder/Updater.cs").read_text(encoding="utf-8")
    fixture = (ROOT / "tests/updater_asset_digest_test.cs").read_text(encoding="utf-8")
    startup = "<StartupObject>%s</StartupObject>" % startup_object if startup_object else ""
    with tempfile.TemporaryDirectory(prefix="updater-digest-build-") as folder:
        root = Path(folder)
        (root / "Updater.cs").write_text(ALIASES + source, encoding="utf-8")
        (root / "Program.cs").write_text(fixture, encoding="utf-8")
        for name in extra_files:
            shutil.copyfile(ROOT / "tests" / name, root / name)
        (root / "NuGet.Config").write_text("<configuration><packageSources><clear/></packageSources></configuration>", encoding="utf-8")
        (root / "Fixture.csproj").write_text("""<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>
<OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings>
<Nullable>enable</Nullable><TreatWarningsAsErrors>true</TreatWarningsAsErrors><NuGetAudit>false</NuGetAudit>
<UseSharedCompilation>false</UseSharedCompilation>%s
</PropertyGroup></Project>""" % startup, encoding="utf-8")
        return subprocess.run([dotnet, "run", "--project", str(root / "Fixture.csproj"), "--configuration", "Release",
                               "--disable-build-servers", "--", *program_arguments], **run_options)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--dotnet", default="dotnet")
    args = parser.parse_args()
    dotnet = shutil.which(args.dotnet)
    if not dotnet:
        parser.error(".NET 8 SDK is required")
    run_fixture(dotnet, args.source, check=True)


if __name__ == "__main__":
    main()

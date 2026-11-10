"""nx2/make_game.py from a clone, with the native tools a Windows build needs fetched once.

    uv run --python 3.12 --with-requirements requirements.txt nx2/bootstrap.py --nup <file.nup> --out <folder>

uv brings Python 3.12 and requirements.txt's packages. On Windows, the compiler, the CPM packages, wgpu-native, SDL and the
profile files come from the latest release's parts, unless the caller set a complete toolchain.
The parts are those Hookshot Builder installs, named with their size and SHA-256 by the release's hookshot-setup.txt.
The Python builder's setup (builder/py/hookshot_builder/setup_parts.py) reads that list and downloads them.
Only those tools are taken from them: the game's sources are always this clone's.
Help never downloads anything; --check does, as it tests the compiler before it reads the game.
Every argument goes to make_game.py as given; path arguments are made absolute against the shell's folder first.
"""
import hashlib
import ntpath
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

REPO = Path(__file__).resolve().parent.parent
# (each part a build reads: the folder taken from the part's zip, and the folder it is kept as; llvm-mingw's zip holds one folder
# named by its release, the part line's "from" folder)
TOOL_PARTS = {
    "llvm-mingw": (None, "llvm-mingw/"),
    "cpm": ("HookshotBuilder/tools/cpm/", "cpm/"),
    "wgpu-native": ("HookshotBuilder/tools/wgpu-native/", "wgpu-native/"),
    "third_party": ("HookshotBuilder/tools/third_party/sdl2/", "third_party/sdl2/"),
    "app": ("HookshotBuilder/tools/work/", "work/"),
}
COMPLETE = ".hookshot-part-complete"   # (in a part's folder: every file of it extracted)
RELEASE_FILE = "release.txt"   # (in the deps folder: the release the tools were last taken from, and its parts)
COPY_BLOCK_BYTES = 1 << 20
PROFILE_FILES = ("work/hot_funcs.txt", "work/hot_order.txt", "work/hookshot_pieces.prof", "work/image/chunks.txt")
OPTIONAL_FILES = PROFILE_FILES + ("work/hookshot.res",)
SDL_FILES = ("third_party/sdl2/SDL2.dll", "third_party/sdl2/SDL3.dll")
PATH_OPTIONS = frozenset({"--nup", "--romfs", "--exefs", "--out", "--update", "--work", "--game", "--log"})
HELP_OPTIONS = frozenset({"--help", "-h"})
ADDRESS_SPACE_32_BIT = 2 ** 32   # (a 32-bit Python's sys.maxsize is below it)
INTERRUPTED_EXIT_CODE = 130   # (the shell's code for a run stopped by Ctrl+C)


class BootstrapError(Exception):
    """A setup failure said in one line, without a traceback."""


def log(message):
    print("[hookshot] %s" % message, flush=True)


def setup_parts():
    """The Python builder's setup module: the reader of a release's setup list and the downloader of its parts."""
    sys.path.insert(0, str(REPO / "builder" / "py"))
    from hookshot_builder import setup_parts as module
    return module


def sha256_file(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def require_files(root, names):
    missing = [str(root / name) for name in names if not (root / name).is_file()]
    if missing:
        raise BootstrapError("Missing native dependency file(s):\n  " + "\n  ".join(missing))


def newest_version(folder):
    """The last version folder of a CPM package, as nx2/build.py takes it; None when there is none"""
    versions = sorted(folder.iterdir()) if folder.is_dir() else []
    return versions[-1] if versions else None


def validate_tools(tools):
    """The files nx2/build.py and nx2/make_game.py read from these tools (a folder per part), in the versions they pick."""
    require_files(tools["llvm-mingw"] / "llvm-mingw", ("bin/clang.exe", "bin/clang++.exe", "bin/ld.lld.exe"))
    require_files(tools["wgpu-native"] / "wgpu-native", ("include/webgpu/webgpu.h", "include/webgpu/wgpu.h",
                                                          "lib/wgpu_native.dll.lib", "lib/wgpu_native.dll"))
    require_files(tools["third_party"], SDL_FILES)
    cpm = tools["cpm"] / "cpm"
    for package, header in (("vulkanheaders", "include/vulkan/vulkan.h"), ("spirv-headers", "include/spirv/unified1/spirv.hpp11"),
                            ("vulkanmemoryallocator", "include/vk_mem_alloc.h")):
        version = newest_version(cpm / package)
        if version is None:
            raise BootstrapError("Missing CPM dependency: %s" % (cpm / package))
        require_files(version, (header,))
    folder = cpm / "ffmpeg"
    ffmpeg = next((path for path in (sorted(folder.iterdir()) if folder.is_dir() else [])
                   if (path / "lib").is_dir() and "linux" not in path.name.lower()), None)
    if ffmpeg is None:
        raise BootstrapError("Missing FFmpeg dependency: %s" % folder)
    require_files(ffmpeg, ("include/libavcodec/avcodec.h", "include/libswscale/swscale.h", "lib/avcodec.lib", "lib/swscale.lib",
                           "lib/swresample.lib", "lib/avutil.lib"))


def part_name(part):
    """The name a part is known by: llvm-mingw's the folder it becomes, a builder part's the one in its zip's name"""
    if part.to != "-":
        return part.to
    name = part.url.rsplit("/", 1)[-1]
    return name[len("HookshotBuilder-"):].rsplit("-", 1)[0] if name.startswith("HookshotBuilder-") else name


def tool_parts(parts):
    """The parts of a release a build reads, by name; every one of TOOL_PARTS must be there."""
    chosen = {part_name(part): part for part in parts if part_name(part) in TOOL_PARTS}
    missing = sorted(set(TOOL_PARTS) - set(chosen))
    if missing:
        raise BootstrapError("The release's setup list has no %s part." % ", ".join(missing))
    return chosen


def safe_archive_path(name):
    """An archive name as a relative path that cannot leave the folder it is extracted to, on Windows either."""
    name = name.replace("\\", "/")
    parts = name.rstrip("/").split("/")
    if any(not part or part in (".", "..") or any(char in part for char in ':<>"|?*') or part.endswith((" ", "."))
           for part in parts):
        raise BootstrapError("Unsafe path in archive: %r" % name)
    return PurePosixPath(*parts)


def extract_part(zip_path, take, keep, destination):
    """The files under take in the zip, kept under keep in destination.
    Nothing else of the part is extracted: the Hookshot sources the app part carries stay in the zip."""
    with zipfile.ZipFile(zip_path) as archive:
        seen = set()
        for entry in archive.infolist():
            name = entry.filename.replace("\\", "/")
            if entry.is_dir() or not name.startswith(take):
                continue
            path = safe_archive_path(keep + name[len(take):])
            if stat.S_ISLNK(entry.external_attr >> 16):
                raise BootstrapError("Unsupported symbolic link in a part: %s" % name)
            key = path.as_posix().casefold()
            if key in seen:
                raise BootstrapError("Duplicate Windows filename in a part: %s" % name)
            seen.add(key)
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output, length=COPY_BLOCK_BYTES)
        if not seen:
            raise BootstrapError("The part %s holds nothing under %s." % (zip_path.name, take))


def ensure_part(deps, setup, part, index, count):
    """The part's tools in deps/parts/<its SHA-256>: kept from an earlier run when complete.
    Otherwise downloaded and checked by the setup, extracted beside the folder, then moved in."""
    folder = deps / "parts" / part.sha
    if (folder / COMPLETE).is_file():
        return folder
    take, keep = TOOL_PARTS[part_name(part)]
    take = take or part.frm + "/"
    zip_path = deps / "downloads" / (part.sha + ".zip")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    folder.parent.mkdir(parents=True, exist_ok=True)
    try:
        if not (zip_path.is_file() and sha256_file(zip_path) == part.sha):
            setup.download_part(log, lambda fraction: None, part, index, count, str(zip_path), None)
    except setup.SetupError as error:
        raise BootstrapError(str(error)) from error
    with tempfile.TemporaryDirectory(prefix="hookshot-part-", dir=folder.parent) as staging:
        staged = Path(staging) / "part"
        extract_part(zip_path, take, keep, staged)
        (staged / COMPLETE).write_text(part.sha + "\n", encoding="ascii")
        try:
            staged.rename(folder)
        except OSError:
            if not (folder / COMPLETE).is_file():   # (else another run extracted the same part first)
                raise
    zip_path.unlink(missing_ok=True)
    return folder


def recorded_release(deps):
    """The release the tools were last taken from and its parts' folders, when they are all still complete; else None"""
    try:
        lines = (deps / RELEASE_FILE).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    tag, tools = (lines[0].strip() if lines else ""), {}
    for line in lines[1:]:
        name, _, sha = line.strip().partition(" ")
        if name in TOOL_PARTS and (deps / "parts" / sha / COMPLETE).is_file():
            tools[name] = deps / "parts" / sha
    return (tag, tools) if tag and set(tools) == set(TOOL_PARTS) else None


def ensure_tools(deps):
    """The latest release's tools, a folder per part in deps; the ones taken last time when GitHub cannot say which is latest."""
    setup = setup_parts()
    try:
        tag, parts = setup.read_manifest(log)
    except setup.SetupError as error:
        recorded = recorded_release(deps)
        if recorded is None:
            raise BootstrapError(str(error)) from error
        log("%s The tools of %s, taken before, are used." % (error, recorded[0]))
        return recorded[1]
    chosen = tool_parts(parts)
    tools = {name: ensure_part(deps, setup, chosen[name], index, len(chosen)) for index, name in enumerate(sorted(chosen), 1)}
    validate_tools(tools)
    (deps / RELEASE_FILE).write_text(tag + "\n" + "".join("%s %s\n" % (name, chosen[name].sha) for name in sorted(chosen)),
                                     encoding="utf-8")
    log("Native tools of %s ready: %s" % (tag, deps / "parts"))
    return tools


def copy_atomic(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=target.name + ".", dir=target.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        shutil.copyfile(source, temporary)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def stage_local_resources(repo, tools):
    """SDL into the clone, where nx2/build.py reads it, and the profile files when the clone has none of its own.
    A clone's own profile files are kept as a set: never mixed with the release's."""
    for name in SDL_FILES:
        source, target = tools["third_party"] / name, repo / name
        if not target.is_file() or sha256_file(source) != sha256_file(target):
            copy_atomic(source, target)
    work = tools["app"]

    def own(name):   # (a profile file of the clone that is not the release's)
        return (repo / name).exists() and (not (work / name).is_file() or sha256_file(repo / name) != sha256_file(work / name))
    custom_profiles = any(own(name) for name in PROFILE_FILES)
    if custom_profiles:
        log("Keeping the clone's own profile files: the release's were not copied.")
    for name in OPTIONAL_FILES:
        if custom_profiles and name in PROFILE_FILES:
            continue
        source, target = work / name, repo / name
        if source.is_file() and not target.exists():
            copy_atomic(source, target)


def absolute_path(value, cwd):
    """A command-line path read against the shell's folder, not the clone make_game.py runs in."""
    if os.path.isabs(value) or ntpath.isabs(value):
        return value
    return str((cwd / value).resolve())


def source_arguments(arguments, cwd):
    """The arguments in their order, only the path-valued options made absolute."""
    result = []
    index = 0
    while index < len(arguments):
        item = arguments[index]
        flag, sep, value = item.partition("=")
        if sep and flag in PATH_OPTIONS:
            result.append(flag + sep + (absolute_path(value, cwd) if value else value))
        elif item in PATH_OPTIONS and index + 1 < len(arguments) and not arguments[index + 1].startswith("--"):
            result.extend([item, absolute_path(arguments[index + 1], cwd)])
            index += 1
        else:
            result.append(item)
        index += 1
    return result


def native_tools_needed(arguments):
    return not any(arg in HELP_OPTIONS for arg in arguments)


def supplied_tools(repo, cwd, env):
    """True when the caller set a complete toolchain, SDL in the clone included: nothing is then fetched or copied."""
    keys = ("RX_CPM", "WGPU_NATIVE") if env.get("HOOKSHOT_MSVC") == "1" else ("HOOKSHOT_MINGW", "RX_CPM", "WGPU_NATIVE")
    return (all(env.get(k) and Path(absolute_path(env[k], cwd)).is_dir() for k in keys)
            and all((repo / name).is_file() for name in SDL_FILES))


def caller_environment(cwd):
    """The environment as the caller set it, its tool paths made absolute against the shell's folder."""
    env = os.environ.copy()
    for key in ("HOOKSHOT_MINGW", "RX_CPM", "WGPU_NATIVE", "HOOKSHOT_NGX_SDK", "HOOKSHOT_SYSROOT"):
        if env.get(key):
            env[key] = absolute_path(env[key], cwd)
    return env


def build_environment(tools, cwd):
    """The caller's environment with the release's tools wherever it set no path of its own.
    HOOKSHOT_MSVC=1, the Visual Studio route, is kept: the release's llvm-mingw is then neither named nor put first on PATH."""
    env = caller_environment(cwd)
    msvc = env.get("HOOKSHOT_MSVC") == "1"
    for name, part in (("HOOKSHOT_MINGW", "llvm-mingw"), ("RX_CPM", "cpm"), ("WGPU_NATIVE", "wgpu-native")):
        if not env.get(name) and not (msvc and name == "HOOKSHOT_MINGW"):
            env[name] = str(tools[part] / part)
    if not msvc:
        env["PATH"] = str(Path(env["HOOKSHOT_MINGW"]) / "bin") + os.pathsep + env.get("PATH", "")
    return env


def run_builder(repo, arguments, env=None):
    command = [sys.executable, "-I", "-u", "-X", "utf8", str(repo / "nx2" / "make_game.py"), *arguments]
    return subprocess.call(command, cwd=repo, env=env)


def windows_host():
    return os.name == "nt"


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    cwd = Path.cwd()
    try:
        arguments = source_arguments(arguments or ["--help"], cwd)
        if not native_tools_needed(arguments) or not windows_host() or supplied_tools(REPO, cwd, os.environ):
            return run_builder(REPO, arguments, caller_environment(cwd))
        if sys.maxsize <= ADDRESS_SPACE_32_BIT:
            raise BootstrapError("Building on Windows needs a 64-bit Python.")
        local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        tools = ensure_tools(local / "HookshotBuilder" / "deps")
        stage_local_resources(REPO, tools)
        return run_builder(REPO, arguments, build_environment(tools, cwd))
    except KeyboardInterrupt:
        print("\n[hookshot] Cancelled.", file=sys.stderr)
        return INTERRUPTED_EXIT_CODE
    except (BootstrapError, OSError, zipfile.BadZipFile) as error:
        print("[hookshot] %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

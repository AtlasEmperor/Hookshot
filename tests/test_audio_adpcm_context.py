"""Compile the real wave-buffer decoder against authored samples; no game or audio device.

python -I -B tests/test_audio_adpcm_context.py [--cc clang] [--source host/nn_audio.c]
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--source", type=Path, default=ROOT / "host/nn_audio.c")
    args = parser.parse_args()
    process_flags = (subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS) if os.name == "nt" else 0

    def run(command):
        result = subprocess.run(command, creationflags=process_flags, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", check=False)
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
        result.check_returncode()

    source = args.source.read_text(encoding="utf-8")
    # Use the production layouts and complete source-frame/queue implementation.
    # The fixture supplies only guest-address translation and its own wave data.
    start = source.index("#define FRAME")
    end = source.index("static CRITICAL_SECTION lock;")
    declarations = source[start:end]
    start = source.index("/* one source frame (all channels)")
    end = source.index("/* ---- I3DL2 reverb")
    decoder = source[start:end]
    with tempfile.TemporaryDirectory(prefix="audio-adpcm-") as temporary:
        folder = Path(temporary)
        (folder / "audio_adpcm.inc").write_text(declarations + "\n" + decoder, encoding="utf-8")
        executable = folder / "fixture.exe"
        run([args.cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-I" + str(folder),
             str(ROOT / "tests/audio_adpcm_context_test.c"), "-o", str(executable)])
        run([str(executable)])


if __name__ == "__main__":
    main()

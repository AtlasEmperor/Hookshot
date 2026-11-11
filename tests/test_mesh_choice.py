"""The task and mesh programs the device is made for, from the Insert menu's Mesh shaders row (gpu/vk/mesh_choice.h).

The real header is compiled and mesh_choice::requested run, no game or GPU:

- each of the row's three choices (Automatic, Native, Compute) is asked for as it is;
- a value out of the row's range (a hand-edited options file) is Automatic;
- RX_VK_FORCE_MESH_FALLBACK set to a number other than 0 is Compute over any row, and unset, 0 or not a number leaves the row.

In the source: gpu/vk/vk_main.cpp's make_device asks with the menu's row and that variable.

python -I -B tests/test_mesh_choice.py [--cxx g++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r"""
#include <cstdio>
#include "mesh_choice.h"
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); return 1; } } while (0)
using namespace mkwvk::mesh_choice;
int main() {
    CHECK(kAutomatic == 0 && kNative == 1 && kCompute == 2);   // (the row's values, as hookshot_options.ini saves them)
    for (int row = kAutomatic; row <= kCompute; row++) {
        CHECK(requested(row, nullptr) == row);
        CHECK(requested(row, "0") == row && requested(row, "") == row && requested(row, "no") == row);
        CHECK(requested(row, "1") == kCompute && requested(row, "2") == kCompute && requested(row, "-1") == kCompute);
    }
    CHECK(requested(-1, nullptr) == kAutomatic && requested(3, nullptr) == kAutomatic && requested(99, nullptr) == kAutomatic);
    CHECK(requested(99, "1") == kCompute);
    std::puts("ok");
    return 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    main_cpp = (ROOT / "gpu" / "vk" / "vk_main.cpp").read_text(encoding="utf-8")
    if 'mesh_choice::requested(opts.mesh_mode, getenv("RX_VK_FORCE_MESH_FALLBACK"))' not in main_cpp:
        raise SystemExit("FAIL: vk_main.cpp: the device is not made for the Mesh shaders row and RX_VK_FORCE_MESH_FALLBACK")
    with tempfile.TemporaryDirectory(prefix="mesh-choice-") as tmp:
        tmp = Path(tmp)
        source, exe = tmp / "fixture.cpp", tmp / "fixture.exe"
        source.write_text(FIXTURE, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "gpu" / "vk"), str(source),
                        "-o", str(exe)], check=True)
        out = subprocess.run([str(exe)], capture_output=True, text=True)
        if out.returncode:
            raise SystemExit(out.stdout + out.stderr)
    print("PASS: the Mesh shaders row asked for as chosen, out of range as Automatic, RX_VK_FORCE_MESH_FALLBACK as Compute "
          "over it")


if __name__ == "__main__":
    main()

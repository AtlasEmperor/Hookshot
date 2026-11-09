"""Exercise the real global-memory pass on synthetic address selections; no game or GPU.

python -I -B tests/test_storage_pointer_predicate.py --cxx clang++
GCC needs --std c++23 for the existing compatibility assertion header.
--pass-source can use an unpatched copy for a negative control.
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "clang++"]

ROOT = Path(__file__).resolve().parents[1]
SHADER = ROOT / "gpu/vk/eden/shader_recompiler"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    parser.add_argument("--std", default="c++20")
    parser.add_argument("--pass-source", type=Path,
                        default=SHADER / "ir_opt/global_memory_to_storage_buffer_pass.cpp")
    args = parser.parse_args()
    includes = [ROOT / p for p in ("gpu/vk/compat", "gpu/compat", "gpu/vk/eden", "gpu/third_party/suyu")]
    sources = [ROOT / "tests/storage_pointer_predicate_ir.cpp", args.pass_source,
               *sorted((SHADER / "frontend/ir").glob("*.cpp"))]
    with tempfile.TemporaryDirectory(prefix="storage-pointer-predicate-") as tmp:
        binary = Path(tmp) / "storage_pointer_predicate"
        subprocess.run([args.cxx, "-std=" + args.std, "-O1", "-w",
                        *("-I" + str(path) for path in includes),
                        *(str(path) for path in sources), "-o", str(binary)], check=True)
        env = dict(os.environ)
        for name in ("RX_VK_NO_FOLLOW", "RX_VK_FOLLOW_MESH", "RX_VK_PTR_SPLIT_FALLBACK",
                     "RX_VK_PTR_DIAG", "RX_VK_FOLLOW_STORES"):
            env.pop(name, None)
        subprocess.run([str(binary)], env=env, check=True)


if __name__ == "__main__":
    main()

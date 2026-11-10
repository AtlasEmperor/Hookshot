"""Compile and exercise the actual live diagnostic controller; no game or GPU required."""

import argparse
import os
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "g++"]

ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT_KEYS = ("RX_VK_LOG_SAMPLES", "RX_VK_EXPOSURE_LOG")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default=os.environ.get("CXX", "g++"), help="C++20 compiler for the controller test")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="hookshot-debug-controls-") as directory:
        executable = Path(directory) / "debug_controls.exe"
        subprocess.run(
            [args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-pthread",
             "-I", str(ROOT / "gpu/vk"), str(ROOT / "tests/debug_controls_test.cpp"), "-o", str(executable)],
            check=True,
        )
        env = {key: value for key, value in os.environ.items() if key not in ENVIRONMENT_KEYS}
        subprocess.run([str(executable)], env=env, check=True)
        subprocess.run([str(executable), "environment"],
                       env=dict(env, RX_VK_LOG_SAMPLES="600", RX_VK_EXPOSURE_LOG="2"), check=True)
        subprocess.run([str(executable), "invalid"],
                       env=dict(env, RX_VK_LOG_SAMPLES="bad", RX_VK_EXPOSURE_LOG="-2"), check=True)


if __name__ == "__main__":
    main()

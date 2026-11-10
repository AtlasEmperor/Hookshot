"""The frame log and the shots (SDR recordings) leave a PQ-coded picture out and say so once each; no game or GPU required."""

import argparse
import os
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "g++"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


FIXTURE = r"""
#include <atomic>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

std::vector<std::string> lines;
void logf(const char* format, ...) {
    char line[256];
    va_list args;
    va_start(args, format);
    std::vsnprintf(line, sizeof line, format, args);
    va_end(args);
    lines.emplace_back(line);
}
std::atomic<bool> present_native_pq{false};
@SKIP@
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "failed line %d: %s\n", __LINE__, #x); std::exit(1); } } while (0)

int main() {
    bool shots_told = false, framelog_told = false;
    CHECK(!skip_pq_picture("RX_VK_SHOTS", shots_told) && lines.empty());   // an SDR picture is recorded
    present_native_pq = true;
    CHECK(skip_pq_picture("RX_VK_SHOTS", shots_told) && lines.size() == 1);
    CHECK(lines[0] == "vk: HDR: RX_VK_SHOTS skips PQ10 pictures; it records SDR ones");
    CHECK(skip_pq_picture("RX_VK_SHOTS", shots_told) && lines.size() == 1);   // said once
    CHECK(skip_pq_picture("RX_VK_FRAMELOG", framelog_told) && lines.size() == 2);
    present_native_pq = false;
    CHECK(!skip_pq_picture("RX_VK_FRAMELOG", framelog_told));
    std::puts("PASS: PQ pictures left out of the shots and the frame log, said once each");
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default=os.environ.get("CXX", "g++"), help="C++20 compiler for the fixture")
    args = parser.parse_args()
    text = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    # The recorders must ask it: each call site reads the same function the fixture runs.
    for site in ('skip_pq_picture("RX_VK_SHOTS", shots_told)', 'skip_pq_picture("RX_VK_FRAMELOG", told)'):
        if site not in text:
            raise SystemExit("vk_replay.cpp no longer asks: " + site)
    fixture = FIXTURE.replace("@SKIP@", block(text, "bool skip_pq_picture("))
    with tempfile.TemporaryDirectory(prefix="hookshot-pq-skip-") as directory:
        source = Path(directory) / "fixture.cpp"
        executable = Path(directory) / "fixture.exe"
        source.write_text(fixture, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(executable)],
                       check=True)
        subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    main()

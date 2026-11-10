"""Game-free check of the actual sample-report trace and counter replay cases."""

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
#include <algorithm>
#include <charconv>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>
#include <unordered_map>
#include <vector>

std::vector<std::string> lines;
namespace mkwvk {
void logf(const char* format, ...) {
    char line[512];
    va_list args;
    va_start(args, format);
    std::vsnprintf(line, sizeof line, format, args);
    va_end(args);
    lines.emplace_back(line);
}
}
#include "vk_debug.cpp"
using namespace mkwvk;
#define CHECK(expr) do { if (!(expr)) { std::fprintf(stderr, "failed line %d: %s\n", __LINE__, #expr); std::exit(1); } } while (0)

// Keep the queue-generation members used by the current production replay
// (vk_state.h), while the fixture omits unrelated GPU descriptor fields.
constexpr int kNvnStages = 8;
struct NvnState {
    uint64_t samples_passed = 0, bind_gen = 0, rt_serial = 0;
    uint64_t tex_gen[kNvnStages]{}, ssbo_gen[kNvnStages]{};
};
NvnState state;
@TRACE@
@PAYLOAD@

constexpr uint64_t NVN_COUNTER_WRITTEN = 1ull << 32;
constexpr uint64_t NVN_COUNTER_TYPE_SAMPLES_PASSED = 1;
enum { NOP_REPORT_COUNTER, NOP_RESET_COUNTER };
struct nvn_p_counter { uint64_t type, addr; };
struct Host {
    std::map<uint64_t, uint64_t> words;
    int writes = 0;
    uint64_t ticks() { return 1000; }
    uint64_t gpu_guest(uint64_t addr) { return addr; }
} host_data;
Host* host = &host_data;
int guest_cpu_write(uint64_t addr, const void* data, uint64_t size) {
    ++host_data.writes;
    for (uint64_t i = 0; i < size; i += 8)
        std::memcpy(&host_data.words[addr + i], static_cast<const uint8_t*>(data) + i, 8);
    return 0;
}
void memory_cpu_owned(uint64_t, uint64_t) {}
bool dump_on() { return false; }
int dump_seq() { return 0; }
int64_t presents_now = 0;
uint64_t ts_anchor_ns = 0;
void counter(int op, uint64_t type = 1, uint64_t addr = 0x1000, bool worker = false) {
    const nvn_p_counter c{type, addr};
    const auto* a = reinterpret_cast<const uint8_t*>(&c);
    const uint32_t avail = sizeof c;
    NvnState& s = *cur_state;
    switch (op) {
        @REPORT@
        @RESET@
    }
}

int main() {
    CHECK(parse_nonnegative(nullptr) == -1);
    for (const char* invalid : {"", "-1", "bad", "1x", "9223372036854775808"})
        CHECK(parse_nonnegative(invalid) == -1);
    CHECK(parse_nonnegative("0") == 0);
    CHECK(parse_nonnegative("600") == 600);
    CHECK(parse_nonnegative("9223372036854775807") == INT64_MAX);
    debug_settings_init(0, 0);
    CHECK(debug_state().recording && debug_state().samples == 1);
    lines.clear();

    use_queue_state(0x111);
    counter(NOP_RESET_COUNTER);
    counter(NOP_RESET_COUNTER);
    presents_now = 9;
    cur_state->samples_passed = 48;
    counter(NOP_REPORT_COUNTER);
    CHECK(lines.empty() && debug_state().remaining == kDebugSampleReportLimit);
    CHECK(host_data.words[0x1000] == 48);
    presents_now = 10;
    debug_present(presents_now);
    counter(NOP_REPORT_COUNTER);
    CHECK(lines.back() == "vk: samples present 10 queue 0x111 reset 2 addr 0x1000 value 48 written 1");

    use_queue_state(0x222);
    counter(NOP_RESET_COUNTER);
    cur_state->samples_passed = 64;
    counter(NOP_REPORT_COUNTER, 1, 0x2000);
    CHECK(lines.back() == "vk: samples present 10 queue 0x222 reset 1 addr 0x2000 value 64 written 1");
    const auto logged = lines.size();
    const int writes = host_data.writes;
    counter(NOP_REPORT_COUNTER, 1, 0x2000, true);
    counter(NOP_RESET_COUNTER, 1, 0, true);
    CHECK(lines.size() == logged && host_data.writes == writes);
    counter(NOP_REPORT_COUNTER, 16);
    CHECK(lines.size() == logged); // Timestamp/control reports are not sample reports.

    use_queue_state(0x111);
    cur_state->samples_passed = 80;
    host_data.words[0x3000] = 999;
    counter(NOP_REPORT_COUNTER, 1 | NVN_COUNTER_WRITTEN, 0x3000);
    CHECK(host_data.words[0x3000] == 999);
    CHECK(lines.back() == "vk: samples present 10 queue 0x111 reset 2 addr 0x3000 value 80 written 0");

    debug_settings_set(0, 0);
    lines.clear();
    counter(NOP_RESET_COUNTER);
    cur_state->samples_passed = 96;
    counter(NOP_REPORT_COUNTER);
    CHECK(lines.empty() && !debug_state().recording && host_data.words[0x1000] == 96);

    debug_settings_set(1, 0);
    debug_recording_start();
    lines.clear();
    use_queue_state(0);
    cur_state->samples_passed = 96;
    for (uint32_t i = 0; i < kDebugSampleReportLimit + 2; ++i) counter(NOP_REPORT_COUNTER);   // two past the limit
    const size_t expected_lines = kDebugSampleReportLimit + 2;   // the reports, the limit notice, the recording stop
    CHECK(lines.size() == expected_lines && debug_state().remaining == 0 && !debug_state().recording);
    CHECK(lines.front() == "vk: samples present 10 queue 0 reset 0 addr 0x1000 value 96 written 1");
    CHECK(lines[kDebugSampleReportLimit] == "vk: samples trace stopped after " + std::to_string(kDebugSampleReportLimit) + " reports");
    counter(NOP_RESET_COUNTER);
    CHECK(lines.size() == expected_lines);
    debug_recording_start();
    counter(NOP_REPORT_COUNTER);
    CHECK(lines.back().find("reset 0") != std::string::npos);
    debug_recording_stop();
    CHECK(!debug_state().recording);
    std::puts("PASS: bounded sample trace, queue resets, threshold, workers and preserved report flags");
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default=os.environ.get("CXX", "g++"), help="C++20 compiler for the fixture")
    args = parser.parse_args()
    text = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    start = text.index("std::unordered_map<uint64_t, NvnState> qstates;")
    end = text.index("\ntemplate <class T>\nT payload(", start)
    fixture = FIXTURE.replace("@TRACE@", text[start:end])
    fixture = fixture.replace("@PAYLOAD@", block(text, "template <class T>\nT payload("))
    fixture = fixture.replace("@REPORT@", block(text, "case NOP_REPORT_COUNTER:"))
    fixture = fixture.replace("@RESET@", block(text, "case NOP_RESET_COUNTER:"))
    with tempfile.TemporaryDirectory(prefix="hookshot-sample-trace-") as directory:
        source = Path(directory) / "fixture.cpp"
        executable = Path(directory) / "fixture.exe"
        source.write_text(fixture, encoding="utf-8")
        subprocess.run(
            [args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror",
             "-I", str(ROOT / "gpu/vk"), str(source), "-o", str(executable)],
            check=True,
        )
        for queue_state in ("0", "1"):
            env = dict(os.environ, RX_VK_LOG_SAMPLES="10", RX_VK_QUEUE_STATE=queue_state, RX_VK_TS_SCALE="1",
                       RX_VK_OCC_FIXED="-1")
            subprocess.run([str(executable)], env=env, check=True)


if __name__ == "__main__":
    main()

"""A pool the background import thread makes is handed over inside the same use of the device, so a device rebuild's release
gives it back; and a range it holds is handed back to the lookups waiting for it while a rebuild holds the gate, so that none
waits for this thread at the gate (gpu/vk/vk_memory.cpp bg_main, memory_imports_give_back; no game/GPU).

The body of bg_main's loop is compiled as it is, beside stand-ins for the import and for the device's use: the stand-in's end
runs the memory module's release, as a rebuild waiting at the gate does the moment the last use ends. The pool made on the old
device must be given back by that release, never left for bg_drain to put in the table of the new one. With the gate closed,
the range must leave bg_inflight before the thread waits at the door.
python -I -B tests/test_import_rebuild.py [--cxx g++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r"""
#include <algorithm>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <cstdio>
#include <mutex>
#include <utility>
#include <vector>
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); return 1; } } while (0)
struct Pool { uint64_t buffer = 0; bool prefetched = false; };
std::mutex bg_mu;
std::condition_variable bg_done_cv;
std::deque<std::pair<uint64_t, uint64_t>> bg_queue;
std::vector<uint64_t> bg_inflight;
std::vector<std::pair<uint64_t, Pool>> bg_ready;
int64_t st_bg_imports = 0;
int made = 0, given_back = 0;
bool rebuild_waiting = false;   // (a rebuild at the gate: it runs the release once no use is left)
bool gate_closed = false;
int in_flight_at_door = 0;   // (the ranges still listed under way when the thread reached the gate)
bool device_gate_closed() { return gate_closed; }
bool import_pool(uint64_t, uint64_t, Pool& p) { return p.buffer = (uint64_t)++made, true; }
// (the memory module's release, as vk_memory.cpp's: what the thread handed over is given back with the old device)
void release() {
    std::lock_guard lk(bg_mu);
    bg_inflight.clear();
    for (auto& [lo, p] : bg_ready) given_back += p.buffer != 0;
    bg_ready.clear();
}
struct DeviceUse {
    DeviceUse() { in_flight_at_door = (int)bg_inflight.size(); }
    ~DeviceUse() {
        if (rebuild_waiting) rebuild_waiting = false, release();
    }
};
void import_one(std::pair<uint64_t, uint64_t> r) {
@BODY@
}
@GIVE_BACK@
int main() {
    // (no rebuild: the pool is handed over for bg_drain)
    bg_inflight = {0x1000};
    import_one({0x1000, 0x2000});
    CHECK(bg_ready.size() == 1 && bg_ready[0].second.prefetched && bg_inflight.empty() && st_bg_imports == 1);
    bg_ready.clear();
    // (a rebuild waiting while the import runs: its release, when the use ends, finds the new pool and gives it back)
    bg_inflight = {0x3000};
    rebuild_waiting = true;
    import_one({0x3000, 0x4000});
    CHECK(!rebuild_waiting && bg_ready.empty() && given_back == 1 && made == 2);
    // (the gate closed: the range handed back before the thread waits at the door; the rebuild hands back the others)
    bg_inflight = {0x5000};
    gate_closed = true;
    import_one({0x5000, 0x6000});
    CHECK(in_flight_at_door == 0);
    bg_queue = {{0x7000, 0x8000}}, bg_inflight = {0x7000, 0x9000};
    memory_imports_give_back();
    CHECK(bg_queue.empty() && bg_inflight.empty());
    std::puts("ok");
    return 0;
}
"""


def loop_body(memory):
    """bg_main's loop after the range is taken off the queue, to the loop's end"""
    start = memory.index("void bg_main() {")
    start = memory.index("bg_queue.pop_front();\n        }\n", start) + len("bg_queue.pop_front();\n        }\n")
    return memory[start:memory.index("\n    }\n}\n", start)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    memory = (ROOT / "gpu" / "vk" / "vk_memory.cpp").read_text(encoding="utf-8")
    release = memory[memory.index("// (a device rebuild: every import, mirror, shadow and capture buffer given back"):]
    release = release[:release.index("\n}\n")]
    if "for (auto& [lo, p] : bg_ready) destroy_pool(p);" not in release:
        raise SystemExit("vk_memory.cpp: the release does not give back the pools the import thread handed over")
    with tempfile.TemporaryDirectory(prefix="import-rebuild-") as tmp:
        tmp = Path(tmp)
        source, exe = tmp / "fixture.cpp", tmp / "fixture.exe"
        give_back = memory[memory.index("void memory_imports_give_back() {"):]
        give_back = give_back[:give_back.index("\n}\n") + 3]
        source.write_text(FIXTURE.replace("@BODY@", loop_body(memory)).replace("@GIVE_BACK@", give_back), encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-pthread", str(source), "-o", str(exe)], check=True)
        out = subprocess.run([str(exe)], capture_output=True, text=True)
        if out.returncode:
            raise SystemExit(out.stdout + out.stderr)
    print("PASS: a pool imported in the background is handed over inside its use of the device, given back by a rebuild; a "
          "range under way handed back while a rebuild holds the gate")


if __name__ == "__main__":
    main()

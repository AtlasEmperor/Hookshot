"""The Insert menu's GPU device and Robust buffers rows while the game runs, no game or GPU (gpu/vk/vk_menu.cpp saved_value,
hn_gpu, hn_robust and device_tick, gpu/vk/rows_script.h): the ini keeps the rows the device in use was made with; each row's
hint says why it went back after a failed change of it, and the Robust buffers hint says when the GPU in use offers no
robustness to turn on; a device rebuild is asked for at each change of the rows, so that it waits until they rest, never
while the start-up screen is up, and its outcome is kept or the rows put back; RX_VK_ROWS's entries come due at their frames, sizes read as written. The menu's
functions are compiled as they are, beside stand-ins for the menu's options, the device and the rebuild.

python -I -B tests/test_device_rows.py [--cxx g++]
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r"""
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "device_change.h"
#include "rows_script.h"
#include "robust_choice.h"
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); return 1; } } while (0)
using namespace mkwvk;
struct Row { int tab; const char* name; int* value; };
struct { int gpu_device = 0, robust = 0, framegen = 0; } opts;
struct { void* device = nullptr; bool robust_buffers = false, robust_offered = false; } dev;
struct DeviceRebuildOutcome {
    uint64_t seq = 0;
    bool ok = true, rebuilt = false;
    device_change::Change change = device_change::Change::None;
    int gpu_row = 0, robust_row = 0;
    const char* text = "";
};
DeviceRebuildOutcome outcome;
DeviceRebuildOutcome device_rebuild_outcome() { return outcome; }
int gpu_device_in_effect = -1, robust_in_effect = -1;
bool menu_refresh = false;
std::atomic<bool> startup_on{false};
int saves = 0, requests = 0;
void save() { saves++; }
void device_rebuild_request(int, int) { requests++; }
DeviceRebuildOutcome failed(uint64_t seq, device_change::Change change, const char* text) {
    DeviceRebuildOutcome o;
    o.seq = seq, o.ok = false, o.rebuilt = true, o.change = change, o.text = text;
    return o;
}
@HINT_IN@
@MENU@
int main() {
    // (the ini: the rows the device in use was made with; the live ones before the first device, and every other row's own)
    Row gpu{0, "GPU device", &opts.gpu_device}, robust{0, "Robust buffers", &opts.robust}, other{0, "Frame generation", &opts.framegen};
    opts.gpu_device = 2, opts.robust = 1, opts.framegen = 3;
    CHECK(saved_value(gpu) == 2 && saved_value(robust) == 1 && saved_value(other) == 3);
    gpu_device_in_effect = 1, robust_in_effect = 0;
    CHECK(saved_value(gpu) == 1 && saved_value(robust) == 0 && saved_value(other) == 3);

    // (Robust buffers: a GPU in use without VK_EXT_robustness2 runs it off; the row's own hint where it runs as asked, or Off
    // asked, and while a change to it is still to be made on a GPU that offers it)
    int device = 1;
    dev.device = &device, dev.robust_buffers = false, dev.robust_offered = false;
    const char* off = "Off: this GPU does not offer bounds-checked buffer access.";
    CHECK(!strcmp(hn_robust(0, -1), off) && !strcmp(hn_robust(2, -1), off) && strcmp(hn_robust(1, -1), off));
    dev.robust_offered = true;
    for (int v = 0; v <= 2; v++)
        CHECK(strcmp(hn_robust(v, -1), off) && !strcmp(hn_robust(v, 0), off) && hn_robust(v, 1) && hn_robust(v, 2));
    CHECK(!hn_robust(0, 3));

    // (why a row went back after a failed change of it, the longest of those measured first; the other row's hint its own)
    CHECK(hn_gpu(0, -1) && !strcmp(hn_gpu(0, -1), "The best dedicated GPU.") && !hn_gpu(1, -1));
    outcome = failed(1, device_change::Change::Gpu, "the GPU asked for failed to set up: the one before was set up again");
    CHECK(!strcmp(hn_gpu(1, -1), outcome.text) && !strcmp(hn_gpu(1, 0), outcome.text) && !hn_gpu(1, 1));
    CHECK(strcmp(hn_robust(0, -1), outcome.text));
    outcome = failed(2, device_change::Change::Robustness,
                     "the robust buffers asked for failed to set up: the device before was set up again");
    CHECK(!strcmp(hn_robust(0, -1), outcome.text) && !strcmp(hn_robust(0, 1), outcome.text) && !hn_gpu(1, -1));
    outcome.ok = true;
    CHECK(!hn_gpu(1, -1) && strcmp(hn_robust(0, -1), outcome.text));

    // (device_tick: a request at each change of the rows, so that the rebuild waits until they rest; none while they rest
    // or match the device in use; the rows in effect kept, or put back after a failure)
    outcome = DeviceRebuildOutcome{};
    gpu_device_in_effect = 0, robust_in_effect = 0, opts.gpu_device = 0, opts.robust = 0;
    device_tick();
    CHECK(requests == 0 && saves == 0);
    opts.gpu_device = 1;
    device_tick();
    device_tick();
    CHECK(requests == 1);
    opts.gpu_device = 2;   // (moved again before the outcome: the rebuild's wait starts again)
    device_tick();
    CHECK(requests == 2);
    opts.gpu_device = 0;   // (back to the device in use, then away again)
    device_tick();
    opts.gpu_device = 2;
    device_tick();
    CHECK(requests == 3);
    outcome.seq = 1, outcome.rebuilt = true, outcome.change = device_change::Change::Gpu, outcome.gpu_row = 2;
    device_tick();
    CHECK(gpu_device_in_effect == 2 && saves == 1 && menu_refresh && requests == 3);
    opts.robust = 1;
    device_tick();
    CHECK(requests == 4);
    outcome = failed(2, device_change::Change::Robustness, "x");
    outcome.gpu_row = 2, outcome.robust_row = 0;
    device_tick();
    CHECK(opts.robust == 0 && robust_in_effect == 0 && opts.gpu_device == 2 && saves == 2 && requests == 4);
    // (the start-up screen up: its shader workers use the device outside the gate, so the change is asked for once it is gone)
    startup_on = true;
    opts.robust = 1;
    device_tick();
    device_tick();
    CHECK(requests == 4);
    startup_on = false;
    device_tick();
    CHECK(requests == 5);

    // (RX_VK_ROWS: each entry at its shown frame, the list on after it, a malformed one left for the log)
    const char* next = "3:robust_buffers=1,5:gpu_device=2,5:output_res=3840x2160";
    rows_script::Entry e;
    CHECK(rows_script::take(2, next, e) == rows_script::Next::NotYet);
    CHECK(rows_script::take(3, next, e) == rows_script::Next::Due && e.frame == 3 && !strcmp(e.key, "robust_buffers") && e.value == 1);
    CHECK(rows_script::take(4, next, e) == rows_script::Next::NotYet);
    CHECK(rows_script::take(5, next, e) == rows_script::Next::Due && !strcmp(e.key, "gpu_device") && e.value == 2);
    CHECK(rows_script::take(5, next, e) == rows_script::Next::Due && !strcmp(e.key, "output_res") && !strcmp(e.text, "3840x2160") &&
          !next);
    CHECK(rows_script::take(9, next, e) == rows_script::Next::Done);
    const char* bad = "4:robust_buffers";
    CHECK(rows_script::take(9, bad, e) == rows_script::Next::Malformed && bad && !strcmp(bad, "4:robust_buffers"));
    std::puts("ok");
    return 0;
}
"""


def function(source, signature):
    """the definition that starts with signature, up to its closing brace at column 0"""
    start = source.index(signature)
    return source[start:source.index("\n}\n", start) + 3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")
    for name, value in (("GPU device", "gpu_device"), ("Robust buffers", "robust")):
        at = menu.index('"%s", &opts.%s,' % (name, value), menu.index("Row rows[] = {"))
        if "restart" in menu[at:menu.index("},", at)]:
            raise SystemExit("vk_menu.cpp: the %s row still says it takes a restart" % name)
    if not re.search(r"fprintf\(f, \"%s=%d\\n\", ini_key\(r\), saved_value\(r\)\);", menu):
        raise SystemExit("vk_menu.cpp: save does not write the rows as the device in use was made with them")
    code = "\n".join(function(menu, s) for s in ("int saved_value(const Row& r) {", "const char* hn_gpu(int v, int variant) {",
                                                 "const char* hn_robust(int v, int variant) {", "void device_tick() {"))
    hint_in = function(menu, "const char* hint_in(")
    with tempfile.TemporaryDirectory(prefix="device-rows-") as tmp:
        tmp = Path(tmp)
        source, exe = tmp / "fixture.cpp", tmp / "fixture.exe"
        source.write_text(FIXTURE.replace("@HINT_IN@", hint_in).replace("@MENU@", code), encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "gpu" / "vk"), str(source),
                        "-o", str(exe)], check=True)
        out = subprocess.run([str(exe)], capture_output=True, text=True)
        if out.returncode:
            raise SystemExit(out.stdout + out.stderr)
    print("PASS: the device rows saved as the device in use was made with them, their hints, a request at each change and the "
          "outcome kept or put back, RX_VK_ROWS's entries at their frames")


if __name__ == "__main__":
    main()

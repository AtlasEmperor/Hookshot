"""The Profile and the Output resolution applied while the game runs (host/nn_applet.c).

The menu's values reach the game through the notifications it polls each frame, once each and only on a change.
30 and 31 bring the operation and performance modes, 300 the graphics scale and the display size.
HOS_HANDHELD and HOS_OUTPUT_RES win over the menu.
An output the boot's window cannot show is left for the next start; the menu is told the size the running game has.

python -I -B tests/test_display_live.py [--cxx g++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def between(text, start, end):
    return text[text.index(start):text.index(end, text.index(start))]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    host = (ROOT / "host" / "nn_applet.c").read_text(encoding="utf-8")
    api = (ROOT / "gpu" / "vk" / "vk_api.h").read_text(encoding="utf-8")
    ids = between(api, "enum { HOS_OPT_OUTPUT_RES", "\n") + "\n"
    fixture = r'''
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include "host/hos_wide_size.h"   // (hos_output_parse's limits)

using DWORD = unsigned long;
using LONG = long;
constexpr int MAX_PATH = 260;
struct Ctx { uint64_t x[31]; uint64_t vreg[32][2]; };
#define HLE(sym) void imp_##sym(Ctx *c)
#define ARG(n) (c->x[n])
#define RET(v) (c->x[0] = (uint64_t)(v))
static uint8_t guest[4096];   // (guest memory: the display-size object at 0x100, the pop's output at 0x800)
#define GP(a) ((void *)(guest + (a)))
#define G32(a) (*(uint32_t *)GP(a))
static LONG InterlockedIncrement(volatile LONG *v) { return ++*v; }
static LONG InterlockedExchange(volatile LONG *v, LONG to) { const LONG was = *v; *v = to; return was; }
static int64_t InterlockedExchange64(volatile int64_t *v, int64_t to) { const int64_t was = *v; *v = to; return was; }
static LONG InterlockedCompareExchange(volatile LONG *v, LONG to, LONG want) {
    const LONG was = *v;
    if (was == want) *v = to;
    return was;
}
static void hos_sleep_ns(int64_t) { throw 0; }   // (PopNotificationMessage waiting: none is pending)
static void hos_log(const char *, ...) {}
DWORD hos_game_path_a(char *path, int size) { return snprintf(path, size, "./hookshot.exe"); }
volatile uint64_t hos_wide_out = 0;
static int menu_up, menu_output, menu_handheld, told_id = -1, told_value = -1, told_count;
''' + ids + r'''
int rx_option(int id, int otherwise) {
    if (!menu_up) return otherwise;
    return id == HOS_OPT_OUTPUT_RES ? menu_output : id == HOS_OPT_HANDHELD ? menu_handheld : otherwise;
}
void rx_option_set(int id, int value) { told_id = id, told_value = value, told_count++; }
''' + between(host, "int hos_ini_option(const char *key, int otherwise);", "HLE(_ZN2nn2oe20GetCurrentFocusStateEv)") + \
        between(host, "/* No system notifications arrive", "/* ---- nn::account") + \
        between(host, "/* nn::oe::GetCurrentGraphicsScale()", "HLE(_ZN2nn2oe31EnterExitRequestHandlingSectionEv)") + r'''
static void check(bool ok, const char *what) {
    if (!ok) {
        fprintf(stderr, "FAIL: %s\n", what);
        exit(1);
    }
}
static std::vector<uint32_t> pops() {   // (every notification the game's poll would find now)
    std::vector<uint32_t> out;
    for (;;) {
        Ctx c{};
        c.x[0] = 0x800;
        imp__ZN2nn2oe25TryPopNotificationMessageEPj(&c);
        if (!c.x[0]) return out;
        out.push_back(G32(0x800));
    }
}
static bool popped(std::vector<uint32_t> want) { return pops() == want; }
static int ask_mode() { Ctx c{}; imp__ZN2nn2oe16GetOperationModeEv(&c); return (int)c.x[0]; }
static int ask_performance() { Ctx c{}; imp__ZN2nn2oe18GetPerformanceModeEv(&c); return (int)c.x[0]; }
static int ask_scale() { Ctx c{}; imp__ZN2nn2oe23GetCurrentGraphicsScaleEv(&c); return (int)c.x[0]; }
static uint32_t base(int k) { return *(uint32_t *)GP(0x100 + 244 + 4 * k); }
static uint32_t& flags() { return *(uint32_t *)GP(0x100 + 8); }   // (the display-size object's flags: 0x80000 rebuild the frame)
static void tick(int output, int handheld) { menu_up = 1, menu_output = output, menu_handheld = handheld; hos_applet_presented(); }
static int size(int w, int h) { return w << 16 | h; }   // (the menu's form: vk_api.h HOS_OPT_OUTPUT_RES)
static const int GAME = size(2048, 1152);   // (the game's own)

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    const std::string mode = argv[1];
    *(uint32_t *)GP(0x100 + 244) = 2560, *(uint32_t *)GP(0x100 + 248) = 1440;   // (the game's base, as it made it at boot)
    if (mode != "nobase") hos_display_object = 0x100;
    if (mode == "docked") {
        hos_applet_presented();   // (no renderer yet)
        check(told_count == 0 && popped({}), "nothing is sent before the renderer answers");
        check(ask_mode() == 1 && ask_performance() == 1 && ask_scale() == 1, "the boot's docked answers, scale x0.8");
        tick(GAME, 0);
        check(popped({}), "the menu's values as booted send nothing");
        check(told_id == HOS_OPT_OUTPUT_RUNNING && told_value == GAME, "the menu is told the game runs at its own size");
        tick(GAME, 1);
        check(popped({30, 31}), "Handheld on sends the operation and performance modes once");
        check(ask_mode() == 0 && ask_performance() == 0 && ask_scale() == 1, "handheld answers after it");
        tick(GAME, 1);
        check(popped({}), "no change, no notification");
        tick(size(2560, 1440), 0);
        check(popped({30, 31, 300}), "Handheld off at 2560x1440 sends the modes and the graphics scale");
        check(ask_mode() == 1 && ask_scale() == 0 && base(0) == 2560 && base(1) == 1440, "docked, scale x1, display size as booted");
        check(flags() == 0 && told_value == size(2560, 1440), "no frame rebuild while the display size stays; 2560x1440 runs");
        tick(size(1920, 1080), 0);
        check(base(0) == 2560 && base(1) == 1440 && flags() == 0, "the display size waits for the game's own pop of 300");
        check(popped({300}), "1920x1080 sends the graphics scale");
        check(ask_scale() == 0 && base(0) == 1920 && base(1) == 1080, "the display size is 1920x1080");
        check(flags() == 0x80000, "2560x1440 to 1920x1080, the same scale: the game is asked to rebuild its frame");
        flags() = 0;   // (the game's frame maker clears it)
        tick(size(2304, 1296), 0);
        check(popped({300}) && base(0) == 2304 && base(1) == 1296, "a size of the player's own, smaller, applies at once");
        tick(size(3840, 2160), 0);
        check(popped({}) && base(0) == 2304 && told_value == size(2304, 1296), "3840x2160 waits for a restart");
        tick(GAME, 1);
        check(popped({30, 31, 300}) && base(0) == 2560 && base(1) == 1440, "the display size comes back with the game's pop of 300");
        tick(GAME, 0);
        check(popped({30, 31}) && ask_scale() == 1 && base(0) == 2560 && base(1) == 1440, "back to the game's 2048x1152");
        check(told_value == GAME && told_count == 5, "the running size is told on each change only");
    } else if (mode == "pinned") {
        tick(size(2560, 1440), 1);
        check(popped({}) && ask_mode() == 1 && ask_scale() == 1, "HOS_HANDHELD and HOS_OUTPUT_RES win over the menu");
    } else if (mode == "start1080") {
        tick(size(2560, 1440), 0);
        check(told_value == size(1920, 1080) && popped({}) && base(0) == 2560, "from a 1920x1080 start only 1920x1080 applies");
        tick(size(1920, 1080), 1);
        check(popped({30, 31, 300}) && ask_mode() == 0 && ask_scale() == 1, "Handheld still applies at once");
    } else if (mode == "start4k") {
        tick(GAME, 0);
        check(told_value == size(3840, 2160) && popped({}) && ask_scale() == 0, "from a 3840x2160 start only 3840x2160 applies");
    } else if (mode == "start5k") {
        tick(GAME, 0);
        check(told_value == size(5120, 1440) && popped({}) && ask_scale() == 0, "from a 5120x1440 start only 5120x1440 applies");
    } else if (mode == "wide") {
        hos_wide_out = (uint64_t)1440 << 32 | 3440;   // (host/hos_main.c: a 3440x1440 picture)
        tick(size(1920, 1080), 0);
        check(told_value == GAME && popped({}) && base(0) == 2560, "a widescreen picture keeps its own display size");
        tick(size(2560, 1440), 0);
        check(popped({300}) && ask_scale() == 0, "2560x1440 still applies at once with a widescreen picture");
    } else if (mode == "nobase") {
        tick(size(1920, 1080), 0);
        check(told_value == GAME && popped({}) && base(0) == 2560, "without the display-size object 1920x1080 waits");
    } else {
        return 2;
    }
    return 0;
}
'''
    cases = (
        ("docked", "output_res=0\nhandheld_profile=0\n", {}),
        ("pinned", "output_res=2560x1440\nhandheld_profile=1\n", {"HOS_HANDHELD": "0", "HOS_OUTPUT_RES": "0"}),
        ("start1080", "output_res=1920x1080\nhandheld_profile=0\n", {}),
        ("start4k", "output_res=3840x2160\nhandheld_profile=0\n", {}),
        ("nobase", "output_res=0\nhandheld_profile=0\n", {}),
        ("wide", "output_res=0\nhandheld_profile=0\n", {}),
        ("start5k", "output_res=5120x1440\nhandheld_profile=0\n", {}),
    )
    with tempfile.TemporaryDirectory(prefix="display-live-") as tmp:
        tmp = Path(tmp)
        src, exe = tmp / "fixture.cpp", tmp / "fixture.exe"
        src.write_text(fixture, encoding="utf-8")
        subprocess.run([a.cxx, "-std=c++17", "-I", str(ROOT), str(src), "-o", str(exe)], check=True)
        for name, ini, extra in cases:
            (tmp / "hookshot_options.ini").write_text(ini, encoding="ascii")
            env = {k: v for k, v in os.environ.items() if k not in ("HOS_HANDHELD", "HOS_OUTPUT_RES", "HOS_RT_POOL_MB")}
            subprocess.run([str(exe), name], cwd=tmp, env=env | extra, check=True)
    print("PASS: Profile and Output resolution reach the game by notifications once per change; overrides win; the rest waits")


if __name__ == "__main__":
    main()

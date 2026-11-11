"""The frame the game makes again keeps the Output resolution's size, 5120 x 1440 and 5120 x 2880 included.

The game caps a frame it makes again (f_806702e0, a Handheld switch back to docked) at f_8114c5e0's cap.
That cap comes from the game's table by display class and graphics scale: docked at x1 it is 3840 x 2160.
nx2/oot_patches.py passes it through host/nn_applet.c hos_frame_cap: the docked x1 cap holds every output, the others are the game's.

python -I -B tests/test_frame_cap.py [--cc gcc]
"""
import argparse
import contextlib
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import oot_patches  # noqa: E402

# (f_8114c5e0 as the lift writes it for Ocarina of Time 1.1.1)
LIFTED = '''#include "a64.h"
void f_8114c5e0(Ctx *__restrict A64_NOESC c) {
    c->x[9]=recomp_load8(c,c->x[0] + 1351);
    c->x[8]=recomp_load8(c,c->x[0] + 1354);
    { uint64_t _a=c->x[9], _b=1ULL; uint64_t _r=_a-_b; _r&=0xFFFFFFFFULL; { uint32_t _fa=(uint32_t)(_a),_fb=(uint32_t)(_b),_fr=(uint32_t)(_r); c->z=(_fr==0);    } }
if (!c->z) { goto L_8114c610; }
    { uint64_t _a=c->x[8], _b=2ULL; uint64_t _r=_a-_b; _r&=0xFFFFFFFFULL; { uint32_t _fa=(uint32_t)(_a),_fb=(uint32_t)(_b),_fr=(uint32_t)(_r); c->z=(_fr==0);  c->c=(_fa>=_fb);  } }
if (c->c) { goto L_8114c624; }
    c->x[8] = 0x4ULL;
    c->x[8] &= 0xFFFFFFFFULL;
L_8114c5fc:;
    c->x[9]=g_module_base + 0x8114c000ULL + (int64_t)48414720;
    { uint64_t _a=c->x[9], _b=1344ULL; uint64_t _r=_a+_b; c->x[9]=_r; }
    c->x[8] = recomp_load64(c,(c->x[9] + ((c->x[8]) << 3)));
    recomp_store64(c,c->x[1] + 0,c->x[8]);
L_8114c60c:;
return;
L_8114c610:;
    { uint64_t _a=c->x[9], _b=0ULL; uint64_t _r=_a-_b; _r&=0xFFFFFFFFULL; { uint32_t _fa=(uint32_t)(_a),_fb=(uint32_t)(_b),_fr=(uint32_t)(_r); c->z=(_fr==0);    } }
    { if (c->z) { uint64_t _a=c->x[8], _b=3ULL, _r=_a-_b; _r &= 0xFFFFFFFFULL; { uint32_t _fa=(uint32_t)(_a),_fb=(uint32_t)(_b),_fr=(uint32_t)(_r);   c->c=(_fa>=_fb);  } } else {   c->c=1;  } }
if (c->c) { { A64_POLL(c); goto L_8114c60c; } }
    c->x[9] = 0x6ULL;
    c->x[9] &= 0xFFFFFFFFULL;
goto L_8114c634;
L_8114c624:;
if (!c->z) { { A64_POLL(c); goto L_8114c60c; } }
    c->x[8]=recomp_load32(c,c->x[0] + 760);
    c->x[9] = 0x4ULL;
    c->x[9] &= 0xFFFFFFFFULL;
    { uint64_t _r = c->x[8] & 0x2ULL; c->x[8] = _r; }
L_8114c634:;
    { uint64_t _a=c->x[9],_b=((c->x[8]) << 0),_r=_a-_b; c->x[8]=_r; }
{ A64_POLL(c); goto L_8114c5fc; }
}
'''

FIXTURE = r'''#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "host/hos_wide_size.h"   /* (hos_output_parse's limits) */
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); exit(1); } } while (0)
typedef unsigned long DWORD;
#define MAX_PATH 260
static DWORD hos_game_path_a(char *path, int size) { return (DWORD)snprintf(path, (size_t)size, "./hookshot.exe"); }
static void hos_log(const char *fmt, ...) { (void)fmt; }
/* (the lift's machine, as far as f_8114c5e0 uses it: the game's frame cap table at its address, the display object, the answer) */
typedef struct { uint64_t x[32]; int z, c; } Ctx;
#define A64_NOESC
#define A64_POLL(c) ((void)(c))
static const uint64_t g_module_base = 0;
enum { TABLE = 0x83f78540, OBJECT = 0x1000, ANSWER = 0x2000 };
static uint8_t table[64], object[0x600], answer[8];
static uint8_t *at(uint64_t a) {
    if (a >= TABLE && a < TABLE + sizeof table) return table + (a - TABLE);
    if (a >= OBJECT && a < OBJECT + sizeof object) return object + (a - OBJECT);
    CHECK(a >= ANSWER && a < ANSWER + sizeof answer);
    return answer + (a - ANSWER);
}
static uint64_t recomp_load8(Ctx *c, uint64_t a) { (void)c; return *at(a); }
static uint64_t recomp_load32(Ctx *c, uint64_t a) { uint32_t v; (void)c; memcpy(&v, at(a), 4); return v; }
static uint64_t recomp_load64(Ctx *c, uint64_t a) { uint64_t v; (void)c; memcpy(&v, at(a), 8); return v; }
static void recomp_store64(Ctx *c, uint64_t a, uint64_t v) { (void)c; memcpy(at(a), &v, 8); }
/* (the display size the running game has, nn_applet.c's: the start's unless a check sets another) */
static uint32_t live_w, live_h;
uint32_t hos_output_size(int height);
uint32_t hos_live_output_size(int height) { return live_w ? (height ? live_h : live_w) : hos_output_size(height); }
@HOST@
@LIFTED@
static uint64_t cap(int display_class, int scale) {   /* (the cap f_806702e0 takes for that class and graphics scale) */
    Ctx c;
    memset(&c, 0, sizeof c);
    object[1351] = (uint8_t)display_class, object[1354] = (uint8_t)scale;
    c.x[0] = OBJECT, c.x[1] = ANSWER;
    f_8114c5e0(&c);
    return recomp_load64(&c, ANSWER);
}
static uint64_t size(uint32_t w, uint32_t h) { return (uint64_t)h << 32 | w; }
int main(void) {
    /* (the game's table at 0x83f78540, read from Ocarina of Time 1.1.1's image) */
    const uint64_t game[] = {size(640, 480), size(720, 480), size(1280, 720), size(1600, 900), size(1920, 1080), size(2560, 1440),
                             size(3840, 2160)};
    memcpy(table, game, sizeof game);
    const uint32_t w = hos_output_size(0), h = hos_output_size(1);
    const uint64_t docked = cap(0, 0);
    /* (the frame is the base, the output at scale x1, below the cap: f_806702e0 keeps the smaller of each) */
    CHECK((docked & 0xffffffffu) >= w && docked >> 32 >= h);
    CHECK(docked == (w > 3840 || h > 2160 ? size(w > 3840 ? w : 3840, h > 2160 ? h : 2160) : size(3840, 2160)));
    CHECK(cap(0, 1) == size(2560, 1440) && cap(0, 2) == size(1920, 1080));   /* (docked at x0.8 and x0.667: the game's) */
    CHECK(cap(1, 0) == size(1920, 1080) && cap(1, 1) == size(1920, 1080));   /* (handheld: the game's) */
    /* (an Output resolution changed while the game runs: the cap follows the running output, larger or smaller) */
    live_w = 5120, live_h = 2880;
    CHECK(cap(0, 0) == size(5120, 2880) && cap(0, 1) == size(2560, 1440));
    live_w = 1920, live_h = 1080;
    CHECK(cap(0, 0) == size(3840, 2160));
    live_w = live_h = 0;
    printf("PASS: output %ux%u, docked cap %llux%llu\n", w, h, (unsigned long long)(docked & 0xffffffffu),
           (unsigned long long)(docked >> 32));
    return 0;
}
'''


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()

    host = (ROOT / "host/nn_applet.c").read_text(encoding="utf-8")
    api = (ROOT / "gpu/vk/vk_api.h").read_text(encoding="utf-8")
    packing = api[api.index("enum { HOS_OUTPUT_WIDTH_SHIFT"):api.index(chr(10), api.index("enum { HOS_OUTPUT_WIDTH_SHIFT"))]
    start = host.index("int hos_ini_option(const char *key, int otherwise);")
    end = host.index("\n}\n", host.index("uint64_t hos_frame_cap(")) + 3
    with tempfile.TemporaryDirectory(prefix="frame-cap-") as tmp:
        work = Path(tmp)
        gen = work / "gen"
        gen.mkdir()
        (gen / "code_000.c").write_text(LIFTED, encoding="utf-8", newline="")
        with contextlib.redirect_stdout(io.StringIO()):   # (the other output size places are not in this lift: warned)
            oot_patches.apply_output_size(str(gen))
        lifted = (gen / "code_000.c").read_text(encoding="utf-8")
        check(lifted.count("hos_frame_cap(c->x[8])") == 1, "the cap is not passed through the host once")
        check(oot_patches.OUT_DECL in lifted, "the lifted file does not declare the host's functions")
        largest = [new for old, new in oot_patches.OUT_EDITS if "f_831cca50" in old or "3668" in old]
        check(len(largest) == 2 and all("hos_live_output_size(" in new and "hos_output_size(" not in new for new in largest),
              "the 3D's largest size does not follow the running output")
        source, exe = work / "fixture.c", work / "fixture.exe"
        source.write_text(FIXTURE.replace("@HOST@", packing + chr(10) + host[start:end]).replace("@LIFTED@", lifted.replace('#include "a64.h"\n', "")),
                          encoding="utf-8")
        subprocess.run([a.cc, "-std=c11", "-I", str(ROOT), str(source), "-o", str(exe)], check=True)
        for mode, w, h in (("2048x1152", 2560, 1440), ("2560x1440", 2560, 1440), ("3840x2160", 3840, 2160), ("1920x1080", 1920, 1080),
                           ("5120x1440", 5120, 1440), ("5120x2880", 5120, 2880), ("4608x2592", 4608, 2592), ("2", 3840, 2160)):
            (work / "hookshot_options.ini").write_text(f"output_res={mode}\nhandheld_profile=0\n", encoding="ascii")
            env = {k: v for k, v in os.environ.items() if k not in ("HOS_OUTPUT_RES", "HOS_HANDHELD")}
            run = subprocess.run([str(exe)], cwd=work, env=env, capture_output=True, text=True)
            check(run.returncode == 0, f"output_res={mode} ({w}x{h}): {run.stderr.strip()}")
            check(f"output {w}x{h}," in run.stdout, f"output_res={mode} is not {w}x{h}: {run.stdout.strip()}")
    print("PASS: the docked frame's cap holds every output, 5120 x 1440 and 5120 x 2880 included, and the running one; the other "
          "caps are the game's; the 3D's largest size follows the running output")


if __name__ == "__main__":
    main()

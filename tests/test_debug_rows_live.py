"""The Debug tab's Descriptor reuse and Sampler cache rows, read at each use while the game runs (gpu/vk/vk_draw.cpp).

The real desc_slotgen_on, desc_slotgen_generation and sampler_cache_on are compiled beside stand-ins for the menu's options and
the log, and run once per environment:

- each follows its row at every call, RX_VK_DESC_SLOTGEN and RX_VK_SAMPLER_CACHE over the rows (any value, 0 off);
- Descriptor reuse's generation moves at each change of the choice, and only then;
- each logs its ready line when it turns on, and a line when it turns off after it was on.

The menu's load of hookshot_options.ini (gpu/vk/vk_menu.cpp menu_init) and its ini_key are compiled with the rows' defaults
(gpu/vk/vk_menu.h) and ranges, then the readers above, and run over each options file: Descriptor reuse on by default since
options_version 4 (an older file wrote its 0 as the off default it then was), Sampler cache off by default, no version rule:

- no file: the default; a file without the line: the default;
- options_version 3 with descriptor_reuse=0: on (the old default, moved); 4 with 0: off (chosen); 4 with 1: on;
- RX_VK_DESC_SLOTGEN over all of it.

In the source: neither row says it takes a restart; a draw keeps its descriptors only when they were built under the Descriptor
reuse choice in effect (vk_draw.cpp's same_desc).

python -I -B tests/test_debug_rows_live.py [--cxx clang++]
"""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "g++"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r"""
#include <atomic>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); return 1; } } while (0)
struct { int descriptor_reuse = 1, sampler_cache = 0; } opts;
int lines = 0;
char last[256];
void logf(const char* fmt, ...) {
    va_list a;
    va_start(a, fmt);
    std::vsnprintf(last, sizeof last, fmt, a);
    va_end(a);
    lines++;
}
BODY
int main(int argc, char** argv) {
    if (argc != 2) return 2;
    const int env = std::atoi(argv[1]);   // (-1: neither variable set; 0 or 1: both set to it)
    if (env < 0) {
        // (Descriptor reuse: on by default, the ready line; the generation moves at the first look and at each change only)
        CHECK(desc_slotgen_on() && lines == 1 && std::strstr(last, "descriptor slotgen ready"));
        const uint64_t g = desc_slotgen_generation();
        CHECK(desc_slotgen_on() && desc_slotgen_generation() == g && lines == 1);
        opts.descriptor_reuse = 0;
        CHECK(!desc_slotgen_on() && desc_slotgen_generation() == g + 1 && lines == 2 && std::strstr(last, "descriptor slotgen off"));
        CHECK(!desc_slotgen_on() && desc_slotgen_generation() == g + 1 && lines == 2);
        opts.descriptor_reuse = 1;
        CHECK(desc_slotgen_on() && desc_slotgen_generation() == g + 2 && lines == 3 && std::strstr(last, "descriptor slotgen ready"));
        // (Sampler cache: off by default, without a line; on and off at each change of the row)
        CHECK(!sampler_cache_on() && lines == 3);
        opts.sampler_cache = 1;
        CHECK(sampler_cache_on() && lines == 4 && std::strstr(last, "sampler cache ready"));
        CHECK(sampler_cache_on() && lines == 4);
        opts.sampler_cache = 0;
        CHECK(!sampler_cache_on() && lines == 5 && std::strstr(last, "sampler cache off"));
    } else {
        // (the environment over the rows, whatever they say)
        for (int row = 0; row <= 1; row++) {
            opts.descriptor_reuse = opts.sampler_cache = row;
            CHECK(desc_slotgen_on() == (env != 0) && sampler_cache_on() == (env != 0));
        }
        CHECK(desc_slotgen_generation() == 1);
    }
    std::puts("ok");
    return 0;
}
"""

# (the menu's load over a hookshot_options.ini in the current folder, then the readers: argv the descriptor reuse and sampler
# cache wanted)
LOAD_FIXTURE = r"""
#include <algorithm>
#include <atomic>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
struct {
    int output_res = 0, vsync = 0, resolution = 0, fps_cap = 0, upscale = 0, dlss = 0, handheld = 0, mesh_mode = 0;
    int budget = 0, mic = 0, menu_size = 0, rumble = 0, realtime = 0;
    DEFAULTS
} opts;
struct Row {
    const char* name;
    int* value;
    int lo, hi;
};
Row rows[] = {{"Output resolution", &opts.output_res, 0, 0}, ROWS};
std::string mic_want;
std::string ini_path() { return "hookshot_options.ini"; }
int parse_output(const char*) { return 0; }
std::string mic_key(const char* name) { return name; }
void refresh_mics() {}
void mic_tell_host() {}
int rumble_step(int v) { return v; }
void logf(const char*, ...) {}
INI_KEY
READERS
int main(int argc, char** argv) {
    if (argc != 3) return 2;
    bool has_options = false;
    LOAD
    (void)has_options;
    const bool reuse = desc_slotgen_on(), sampler = sampler_cache_on();
    if (reuse != (std::atoi(argv[1]) != 0) || sampler != (std::atoi(argv[2]) != 0)) {
        std::fprintf(stderr, "FAIL: descriptor_reuse %d (want %s), sampler_cache %d (want %s)\n", reuse, argv[1], sampler, argv[2]);
        return 1;
    }
    return 0;
}
"""

# (hookshot_options.ini's text or None for no file, RX_VK_DESC_SLOTGEN or None, descriptor reuse, sampler cache)
CASES = (
    (None, None, 1, 0),
    ("output_res=1\noptions_version=4\n", None, 1, 0),
    ("descriptor_reuse=0\nsampler_cache=0\noptions_version=3\n", None, 1, 0),
    ("descriptor_reuse=0\nsampler_cache=1\n", None, 1, 1),
    ("descriptor_reuse=0\nsampler_cache=1\noptions_version=4\n", None, 0, 1),
    ("options_version=4\ndescriptor_reuse=1\n", None, 1, 0),
    ("descriptor_reuse=0\noptions_version=4\n", "1", 1, 0),
    ("descriptor_reuse=1\noptions_version=4\n", "0", 0, 0),
    (None, "0", 0, 0),
)


def need(text, pattern, what):
    found = re.search(pattern, text, re.S)
    if not found:
        raise SystemExit("FAIL: " + what)
    return found


def block(text, marker, after=0):
    start = text.index(marker, after)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def compile_fixture(cxx, source, exe, text):
    source.write_text(text, encoding="utf-8")
    subprocess.run([cxx, "-std=c++17", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(exe)], check=True)


def environment(desc_slotgen, sampler_cache):
    env = os.environ.copy()
    env.pop("RX_VK_DESC_SLOTGEN", None)
    env.pop("RX_VK_SAMPLER_CACHE", None)
    if desc_slotgen is not None:
        env["RX_VK_DESC_SLOTGEN"] = desc_slotgen
    if sampler_cache is not None:
        env["RX_VK_SAMPLER_CACHE"] = sampler_cache
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    menu = (ROOT / "gpu/vk/vk_menu.cpp").read_text(encoding="utf-8")
    header = (ROOT / "gpu/vk/vk_menu.h").read_text(encoding="utf-8")
    for name in ("Descriptor reuse", "Sampler cache"):
        at = menu.index('{TAB_DEBUG, "%s"' % name)
        if "restart" in menu[at:menu.index("},", at)]:
            raise SystemExit("FAIL: vk_menu.cpp: the %s row still says it takes a restart" % name)
    need(draw, r"const uint64_t slotgen_gen = desc_slotgen_generation\(\);.*?const bool same_desc = [^;]*"
               r"last_desc_slotgen_gen == slotgen_gen", "vk_draw.cpp: a draw keeps descriptors built under the other choice")
    need(draw, r"last_desc_slotgen_gen = slotgen_gen;", "vk_draw.cpp: the bound descriptors do not record their choice")
    start = draw.index("std::atomic<uint64_t> desc_slotgen_gen{0};")
    end = draw.index("\n}\n", draw.index("bool sampler_cache_on() {")) + 3
    readers = draw[start:end]
    defaults = " ".join(need(header, r"int %s = \d+;" % key, "vk_menu.h: no default for %s" % key).group(0)
                        for key in ("descriptor_reuse", "sampler_cache"))
    rows = ", ".join('{"%s", &opts.%s, %s, %s}' % ((name, key) + need(
        menu, r'\{TAB_DEBUG, "%s", &opts\.%s, (-?\d+), (-?\d+),' % (name, key), "vk_menu.cpp: no %s row" % name).groups())
        for name, key in (("Descriptor reuse", "descriptor_reuse"), ("Sampler cache", "sampler_cache")))
    load = block(menu, '    if (FILE* f = fopen(ini_path().c_str(), "r")) {', menu.index("void menu_init() {"))
    load_fixture = (LOAD_FIXTURE.replace("DEFAULTS", defaults).replace("ROWS", rows)
                    .replace("INI_KEY", block(menu, "const char* ini_key(const Row& r) {"))
                    .replace("READERS", readers).replace("LOAD", load))
    with tempfile.TemporaryDirectory(prefix="debug-rows-live-") as tmp:
        work = Path(tmp)
        exe, load_exe = work / "fixture.exe", work / "load.exe"
        compile_fixture(args.cxx, work / "fixture.cpp", exe, FIXTURE.replace("BODY", readers))
        compile_fixture(args.cxx, work / "load.cpp", load_exe, load_fixture)
        for value in (None, "0", "1"):
            out = subprocess.run([str(exe), "-1" if value is None else value], env=environment(value, value),
                                 capture_output=True, text=True)
            if out.returncode:
                raise SystemExit(out.stdout + out.stderr)
        ini = work / "hookshot_options.ini"
        for text, env_value, reuse, sampler in CASES:
            if ini.exists():
                ini.unlink()
            if text is not None:
                ini.write_text(text, encoding="ascii")
            out = subprocess.run([str(load_exe), str(reuse), str(sampler)], cwd=work, env=environment(env_value, None),
                                 capture_output=True, text=True)
            if out.returncode:
                raise SystemExit("FAIL: options file %r, RX_VK_DESC_SLOTGEN %r\n%s" % (text, env_value, out.stdout + out.stderr))
    print("PASS: Descriptor reuse and Sampler cache follow their rows at each use, the environment over them; Descriptor "
          "reuse's generation moves at each change only; on by default and for options files before version 4, a version 4 "
          "choice and the environment kept; Sampler cache off by default")


if __name__ == "__main__":
    main()

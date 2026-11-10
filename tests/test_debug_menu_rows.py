"""The Debug tab's diagnostics rows (gpu/vk/vk_menu.cpp) drive the live diagnostic controller (gpu/vk/vk_debug.cpp); no game or GPU.

The rows' declarations are checked in the source: on the Debug tab, exempt from the Quality preset and from restarts,
the two buttons without a saved value, and confirm dispatched to them before it can open the Controls page. The row
helpers (cell text, prompt, confirm, publishing) are compiled and run against the real controller.

    python -I -B tests/test_debug_menu_rows.py [--cxx g++]
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
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <string>
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
struct Options { int sample_log = 0, exposure_log = 0; } opts;
}
#include "vk_debug.cpp"
namespace mkwvk {
@ACTIONS@
@TEXT@
@CONFIRM@
@EXPOSURE@
@PRESS@
@PUBLISH@
}
using namespace mkwvk;
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "failed line %d: %s\n", __LINE__, #x); std::exit(1); } } while (0)

bool contains(const std::string& line, const char* text) { return line.find(text) != std::string::npos; }

int main(int argc, char**) {
    const bool confirm[8] = {false, false, false, false, false, false, false, true};
    const bool idle[8] = {};
    bool changed = false;
    if (argc > 1) {   // an environment override: RX_VK_EXPOSURE_LOG=2 over saved choices
        opts.sample_log = 1;
        publish_diagnostics();
        CHECK(debug_state().samples == 1 && debug_state().exposure == kDebugExposureEachReading && !debug_state().recording);
        CHECK(opts.exposure_log == kDebugExposureEachReading);   // the row shows what holds
        std::puts("PASS: the rows show the environment's override over the saved choices");
        return 0;
    }
    CHECK(kNoAction != kActionRecording && kNoAction != kActionMarkFlash && kActionRecording != kActionMarkFlash);
    CHECK(std::string(tx_exposure(0)) == "Off" && std::string(tx_exposure(1)) == "History");
    CHECK(std::string(tx_exposure(kDebugExposureEachReading)) == "Each reading" && std::string(tx_exposure(9)) == "Off");

    publish_diagnostics();   // nothing saved, no environment: both off
    CHECK(debug_state().samples == 0 && debug_state().exposure == 0);
    CHECK(debug_action_text(kActionRecording) == "Choose a report above");
    debug_action_press(kActionRecording, idle, changed);
    CHECK(!changed && lines.empty());   // only confirm acts
    debug_action_press(kActionRecording, confirm, changed);
    CHECK(changed && !debug_state().recording && contains(lines.back(), "not started: no report is selected"));

    opts.sample_log = 1;   // a changed row reaches the controller, which starts nothing by itself
    publish_diagnostics();
    CHECK(debug_state().samples == 1 && !debug_state().recording);
    CHECK(debug_action_text(kActionRecording) == "Start" && std::string(debug_action_confirm(kActionRecording)) == "Start");
    changed = false;
    debug_action_press(kActionRecording, confirm, changed);
    CHECK(changed && debug_state().recording);
    CHECK(debug_action_text(kActionRecording) == "Stop (" + std::to_string(kDebugSampleReportLimit) + " reports left)");
    CHECK(std::string(debug_action_confirm(kActionRecording)) == "Stop");
    debug_action_press(kActionRecording, confirm, changed);
    CHECK(!debug_state().recording && contains(lines.back(), "stopped (requested)"));

    debug_action_press(kActionRecording, confirm, changed);   // a changed choice ends a running recording
    CHECK(debug_state().recording);
    opts.sample_log = 0;
    publish_diagnostics();
    CHECK(!debug_state().recording && debug_state().samples == 0 && contains(lines.back(), "stopped (settings changed)"));

    CHECK(debug_action_text(kActionMarkFlash) == "Mark");
    debug_action_press(kActionMarkFlash, confirm, changed);
    CHECK(debug_state().flash_markers == 1 && debug_action_text(kActionMarkFlash) == "Mark (1 so far)");
    CHECK(std::string(debug_action_confirm(kActionMarkFlash)) == "Mark");
    std::puts("PASS: the diagnostics rows start, stop and mark through the controller and publish their choices");
}
"""


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def need(text, pattern, what):
    if not re.search(pattern, text, re.S):
        raise SystemExit("FAIL: vk_menu.cpp: " + what)


def check_source(menu, header):
    for key in ("sample_log", "exposure_log"):
        if "int %s = 0;" % key not in header:
            raise SystemExit("FAIL: vk_menu.h: Options has no %s" % key)
    developer = menu.index('{TAB_DEBUG, "Developer"')
    for name in ("Descriptor reuse", "Sampler cache", "Occlusion reports", "Exposure history", "Recording",
                 "Mark visual glitch"):
        at = menu.find('{TAB_DEBUG, "%s"' % name)
        if at < developer:
            raise SystemExit("FAIL: vk_menu.cpp: %s is not a Developer row of the Debug tab" % name)
    need(menu, r'\{TAB_DEBUG, "Occlusion reports", &opts\.sample_log, 0, 1, 1, tx_onoff,[^}]*nullptr, false, true\}',
         "Occlusion reports must be a saved on/off row, exempt from presets and restarts")
    need(menu, r'\{TAB_DEBUG, "Exposure history", &opts\.exposure_log, 0, kDebugExposureEachReading, 1, tx_exposure,[^}]*'
               r'nullptr, false, true\}', "Exposure history must span the controller's settings, exempt from presets and restarts")
    need(menu, r'\{TAB_DEBUG, "Recording", nullptr, 0, 0, 0, nullptr,[^}]*true, -1, false,\s*kActionRecording\}',
         "Recording must be a button with no saved value, exempt from presets")
    need(menu, r'\{TAB_DEBUG, "Mark visual glitch", nullptr, 0, 0, 0, nullptr,[^}]*true,\s*-1, false, kActionMarkFlash\}',
         "Mark visual glitch must be a button with no saved value, exempt from presets")
    tick = menu[menu.index("void menu_tick() {"):]
    cheat = tick.find("else if (r.cheat >= 0) cheat_press(r.cheat, press, changed)")
    action = tick.find("else if (r.action != kNoAction) debug_action_press(r.action, press, changed)")
    controls = tick.find("press[7] && !r.value && can_bind()) page = 1")
    if not 0 <= cheat < action < controls:
        raise SystemExit("FAIL: vk_menu.cpp: a diagnostics button's confirm must be dispatched before the Controls page opens")
    if "publish_diagnostics();" not in tick:
        raise SystemExit("FAIL: vk_menu.cpp: menu_tick no longer publishes the diagnostics rows")
    replay = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    if "debug_settings_init(opts.sample_log, opts.exposure_log);" not in block(replay, "bool replay_start()"):
        raise SystemExit("FAIL: vk_replay.cpp: replay_start must give the controller the saved choices first")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default=os.environ.get("CXX", "g++"), help="C++20 compiler for the fixture")
    args = parser.parse_args()
    menu = (ROOT / "gpu/vk/vk_menu.cpp").read_text(encoding="utf-8")
    header = (ROOT / "gpu/vk/vk_menu.h").read_text(encoding="utf-8")
    check_source(menu, header)
    actions_start = menu.index("constexpr signed char kNoAction")
    fixture = (FIXTURE.replace("@ACTIONS@", menu[actions_start:menu.index(";", actions_start) + 1])
               .replace("@TEXT@", block(menu, "std::string debug_action_text("))
               .replace("@CONFIRM@", block(menu, "const char* debug_action_confirm("))
               .replace("@EXPOSURE@", block(menu, "const char* tx_exposure("))
               .replace("@PRESS@", block(menu, "void debug_action_press("))
               .replace("@PUBLISH@", block(menu, "void publish_diagnostics()")))
    with tempfile.TemporaryDirectory(prefix="hookshot-debug-menu-") as directory:
        source = Path(directory) / "fixture.cpp"
        executable = Path(directory) / "fixture.exe"
        source.write_text(fixture, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-pthread",
                        "-I", str(ROOT / "gpu/vk"), str(source), "-o", str(executable)], check=True)
        env = {key: value for key, value in os.environ.items() if key not in ("RX_VK_LOG_SAMPLES", "RX_VK_EXPOSURE_LOG")}
        subprocess.run([str(executable)], env=env, check=True)
        subprocess.run([str(executable), "environment"], env=dict(env, RX_VK_EXPOSURE_LOG="2"), check=True)


if __name__ == "__main__":
    main()

"""The first start's Quality preset (gpu/vk/vk_menu.cpp menu_first_start_for_gpu) is taken for the GPU vk_main.cpp's
pick_device chooses, before the device is made, and once: a device rebuild picks a GPU again and leaves the options as the
player set them. No game or GPU: pick_device and menu_first_start_for_gpu are compiled as they are, beside stand-ins for
the GPUs, the menu's options and its preset helpers.

python -I -B tests/test_first_start_preset.py [--cxx g++] [--vulkan-include <dir>]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}", "--vulkan-include", "{vulkan_headers}"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r"""
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>
#include <vulkan/vulkan_core.h>
#include "gpu_choice.h"
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); return 1; } } while (0)
namespace mkwvk {
constexpr uint64_t MIB = 1ull << 20;
// (an integrated GPU, which would take Minimum, listed before a 6 GB card, which takes Low and which Auto chooses)
struct Gpu { VkPhysicalDeviceProperties props; VkPhysicalDeviceMemoryProperties memory; };
Gpu gpus[2];
struct { VkInstance instance = nullptr; } dev;
struct { int gpu_device = 0, preset = 0, budget = 0, upscale = 2, sharpness = 30, handheld = 0; } opts;
std::vector<std::string> gpu_device_names;
int presets_applied = 0, last_preset = -1, saves = 0;
const char* getenv(const char*) { return nullptr; }   // (no RX_VK_DEVICE, RX_VK_AUTO_PRESET, RX_VK_LOW_SPEC)
void logf(const char*, ...) {}
void menu_init() {}
void menu_set_gpu_count(int) {}
// (as the menu's: Minimum and Low take the handheld profile)
void apply_preset(int p) {
    presets_applied++, last_preset = p;
    if (p == 1 || p == 2) opts.handheld = 1;
}
void sync_preset_budgets(int) {}
void restart_init() {}
void save() { saves++; }
const char* tx_preset(int) { return ""; }
VkResult vkEnumeratePhysicalDevices(VkInstance, uint32_t* n, VkPhysicalDevice* out) {
    if (out)
        for (uint32_t i = 0; i < *n; i++) out[i] = reinterpret_cast<VkPhysicalDevice>(&gpus[i]);
    else
        *n = 2;
    return VK_SUCCESS;
}
void vkGetPhysicalDeviceProperties(VkPhysicalDevice gpu, VkPhysicalDeviceProperties* p) {
    *p = reinterpret_cast<Gpu*>(gpu)->props;
}
void vkGetPhysicalDeviceMemoryProperties(VkPhysicalDevice gpu, VkPhysicalDeviceMemoryProperties* m) {
    *m = reinterpret_cast<Gpu*>(gpu)->memory;
}
@FLAG@
@FIRST_START@
@PICK@
void make(Gpu& gpu, VkPhysicalDeviceType type, uint64_t vram, const char* name) {
    gpu = Gpu{};
    gpu.props.apiVersion = VK_API_VERSION_1_3;
    gpu.props.deviceType = type;
    std::snprintf(gpu.props.deviceName, sizeof gpu.props.deviceName, "%s", name);
    gpu.memory.memoryHeapCount = 1;
    gpu.memory.memoryHeaps[0] = {vram, VK_MEMORY_HEAP_DEVICE_LOCAL_BIT};
}
} // namespace mkwvk
int main() {
    using namespace mkwvk;
    make(gpus[0], VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU, 16384 * MIB, "integrated");
    make(gpus[1], VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU, 6144 * MIB, "6 GB card");
    // (the start, with no options file: menu_init leaves first_start set)
    first_start = true;
    CHECK(pick_device() == reinterpret_cast<VkPhysicalDevice>(&gpus[1]));
    CHECK(presets_applied == 1 && last_preset == 2 && opts.preset == 2 && opts.budget == 2);
    CHECK(saves == 1 && opts.handheld == 0);
    // (a device rebuild onto the other GPU, with the player's own preset since: nothing taken again, nothing saved)
    opts.gpu_device = 1, opts.preset = opts.budget = 4;
    CHECK(pick_device() == reinterpret_cast<VkPhysicalDevice>(&gpus[0]));
    CHECK(presets_applied == 1 && saves == 1 && opts.preset == 4 && opts.budget == 4);
    std::printf("PASS: the first start's preset for the chosen GPU, once\n");
    return 0;
}
"""


def function(source, head):
    """the function at head, up to its closing brace at the line start"""
    body = source[source.index(head):]
    return body[:body.index("\n}\n") + 3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    parser.add_argument("--vulkan-include", type=Path)
    args = parser.parse_args()
    vk = ROOT / "gpu" / "vk"
    main_src = (vk / "vk_main.cpp").read_text(encoding="utf-8")
    menu = (vk / "vk_menu.cpp").read_text(encoding="utf-8")
    init = function(menu, "void menu_init() {")
    if "first_start = !has_options;" not in init:
        raise SystemExit("menu_init: the first start is not the start with no options file")
    start = function(main_src, "const MkwVkRenderer* mkwvk_init(")
    if not -1 < start.find("pick_device()") < start.find("make_device(gpu, made)"):
        raise SystemExit("mkwvk_init: the device is made before the GPU is chosen, so before the first start's preset")
    flag = menu[menu.index("static bool first_start"):]
    fixture = (FIXTURE.replace("@FLAG@", flag[:flag.index("\n") + 1])
               .replace("@FIRST_START@", function(menu, "void menu_first_start_for_gpu("))
               .replace("@PICK@", function(main_src, "VkPhysicalDevice pick_device() {")))
    flags = [args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-DVK_NO_PROTOTYPES", "-I" + str(vk)]
    if args.vulkan_include:
        flags.append("-I" + str(args.vulkan_include))
    with tempfile.TemporaryDirectory(prefix="first-start-preset-") as tmp:
        src = Path(tmp) / "first_start_preset.cpp"
        src.write_text(fixture, encoding="utf-8")
        exe = Path(tmp) / "first-start-preset"
        subprocess.run(flags + [str(src), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()

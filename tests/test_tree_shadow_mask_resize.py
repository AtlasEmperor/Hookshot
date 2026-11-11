"""The tree-shadow mask pass across a change of the mask's size (gpu/vk/vk_draw.cpp mask_stabilize), no GPU required.

The mask is drawn at the scene's size, which the Render resolution row and the upscaler change while the game runs. At each
new size the pass makes its history pair again: the pair it replaces is given back once the GPU has passed the recordings
that may still read it (vk_retirement_value, vk_timeline_completed), never at once and never kept. The mask's storage view
is the mask texture's own (texture_level_storage_view), so none outlives the texture it views.

This builds the pass from its source with stand-ins for Vulkan, the allocator and the texture cache, and counts what is
alive.

python -I -B tests/test_tree_shadow_mask_resize.py [--cxx g++] [--vulkan-include <dir>] [--root <checkout>]
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}", "--vulkan-include", "{vulkan_headers}"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''
#define VK_NO_PROTOTYPES
#include <vulkan/vulkan.h>
#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <iterator>
#include <map>
#include <set>
#include <tuple>
#include <vector>

typedef struct VmaAllocation_T* VmaAllocation;
struct Texture {
    VkImage image = VK_NULL_HANDLE;
    VkFormat format = VK_FORMAT_R8G8B8A8_UNORM;
    VkImageUsageFlags usage = VK_IMAGE_USAGE_STORAGE_BIT;
    uint32_t width = 0, height = 0, id = 0;
    VkImageView own_view = VK_NULL_HANDLE;   // (the texture cache's: destroyed with the texture)
};
struct { VkDevice device = VK_NULL_HANDLE; bool push_descriptor = true; } dev;

uintptr_t next_handle = 1;
template <class H> H handle() { return (H)next_handle++; }
std::map<VkImageView, VkImage> live_views;   // (every view alive, and the image it views)
std::set<VkImage> live_history;              // (the images the pass made through the allocator)
uint64_t completed_value = 0, retirement_value = 1, frame = 1;
bool bad_destroy = false;

uint64_t vk_timeline_completed() { return completed_value; }
uint64_t vk_retirement_value() { return retirement_value; }
uint64_t texture_frame_no() { return frame; }
int mask_radius_env() { return 0; }
void end_pass(VkCommandBuffer) {}
void full_barrier(VkCommandBuffer) {}
void descriptors_disturbed() {}
void logf(const char*, ...) {}
const uint32_t SHADOW_STAB_COMP_SPV[1] = {0};

VkResult create_view(VkDevice, const VkImageViewCreateInfo* ci, const VkAllocationCallbacks*, VkImageView* v) {
    *v = handle<VkImageView>();
    live_views[*v] = ci->image;
    return VK_SUCCESS;
}
void destroy_view(VkDevice, VkImageView v, const VkAllocationCallbacks*) {
    if (!live_views.erase(v)) bad_destroy = true;
}
VkResult create_set_layout(VkDevice, const VkDescriptorSetLayoutCreateInfo*, const VkAllocationCallbacks*, VkDescriptorSetLayout* l) {
    *l = handle<VkDescriptorSetLayout>();
    return VK_SUCCESS;
}
VkResult create_layout(VkDevice, const VkPipelineLayoutCreateInfo*, const VkAllocationCallbacks*, VkPipelineLayout* l) {
    *l = handle<VkPipelineLayout>();
    return VK_SUCCESS;
}
VkResult create_module(VkDevice, const VkShaderModuleCreateInfo*, const VkAllocationCallbacks*, VkShaderModule* m) {
    *m = handle<VkShaderModule>();
    return VK_SUCCESS;
}
void destroy_module(VkDevice, VkShaderModule, const VkAllocationCallbacks*) {}
VkResult create_pipelines(VkDevice, VkPipelineCache, uint32_t n, const VkComputePipelineCreateInfo*, const VkAllocationCallbacks*,
                          VkPipeline* p) {
    for (uint32_t i = 0; i < n; i++) p[i] = handle<VkPipeline>();
    return VK_SUCCESS;
}
void barrier(VkCommandBuffer, const VkDependencyInfo*) {}
void bind(VkCommandBuffer, VkPipelineBindPoint, VkPipeline) {}
void push_set(VkCommandBuffer, VkPipelineBindPoint, VkPipelineLayout, uint32_t, uint32_t, const VkWriteDescriptorSet*) {}
void push_constants(VkCommandBuffer, VkPipelineLayout, VkShaderStageFlags, uint32_t, uint32_t, const void*) {}
void dispatch(VkCommandBuffer, uint32_t, uint32_t, uint32_t) {}
PFN_vkCreateImageView vkCreateImageView = create_view;
PFN_vkDestroyImageView vkDestroyImageView = destroy_view;
PFN_vkCreateDescriptorSetLayout vkCreateDescriptorSetLayout = create_set_layout;
PFN_vkCreatePipelineLayout vkCreatePipelineLayout = create_layout;
PFN_vkCreateShaderModule vkCreateShaderModule = create_module;
PFN_vkDestroyShaderModule vkDestroyShaderModule = destroy_module;
PFN_vkCreateComputePipelines vkCreateComputePipelines = create_pipelines;
PFN_vkCmdPipelineBarrier2 vkCmdPipelineBarrier2 = barrier;
PFN_vkCmdBindPipeline vkCmdBindPipeline = bind;
PFN_vkCmdPushDescriptorSetKHR vkCmdPushDescriptorSetKHR = push_set;
PFN_vkCmdPushConstants vkCmdPushConstants = push_constants;
PFN_vkCmdDispatch vkCmdDispatch = dispatch;

bool create_image(const VkImageCreateInfo&, VkImage& image, VmaAllocation& memory) {
    image = handle<VkImage>(), memory = handle<VmaAllocation>();
    live_history.insert(image);
    return true;
}
void destroy_image(VkImage image, VmaAllocation) {
    if (!live_history.erase(image)) bad_destroy = true;
}
// (the texture cache's views: one per texture here, destroyed with it)
VkImageView texture_level_storage_view(Texture* tex, uint32_t, uint32_t) {
    if (!tex->own_view) {
        VkImageViewCreateInfo ci{VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO};
        ci.image = tex->image;
        create_view(dev.device, &ci, nullptr, &tex->own_view);
    }
    return tex->own_view;
}
void texture_destroy(Texture& tex) {
    if (tex.own_view) destroy_view(dev.device, tex.own_view, nullptr);
    tex.own_view = VK_NULL_HANDLE;
}

@PASS@

int failed = 0;
void check(bool ok, const char* what) {
    if (!ok) printf("FAIL: %s\n", what), failed = 1;
}
size_t views_of(VkImage image) {
    size_t n = 0;
    for (const auto& [view, of] : live_views) n += of == image;
    return n;
}
size_t history_views() {
    size_t n = 0;
    for (const auto& [view, of] : live_views) n += live_history.count(of);
    return n;
}
Texture mask(uint32_t w, uint32_t h) {
    Texture t;
    t.image = handle<VkImage>(), t.width = w, t.height = h, t.id = (uint32_t)next_handle;
    return t;
}

int main() {
    const VkCommandBuffer cmd = handle<VkCommandBuffer>();
    Texture a = mask(1920, 1080);
    mask_stabilize(cmd, &a, 0, 0, 0.85f);
    check(live_history.size() == 2 && history_views() == 2, "the first size makes one history pair");
    // (the Render resolution changed: a mask of another size, the recordings of the first one not done)
    texture_destroy(a);
    check(views_of(a.image) == 0, "a view of a destroyed mask texture is kept");
    Texture b = mask(1440, 810);
    retirement_value = 5, completed_value = 4, frame++;
    mask_stabilize(cmd, &b, 0, 0, 0.85f);
    check(live_history.size() == 4, "the replaced pair is destroyed while the GPU may still read it, or not replaced");
    frame++;
    mask_stabilize(cmd, &b, 0, 0, 0.85f);
    check(live_history.size() == 4, "the replaced pair is destroyed before the GPU reached its recordings");
    completed_value = 5, frame++;
    mask_stabilize(cmd, &b, 0, 0, 0.85f);
    check(live_history.size() == 2 && history_views() == 2, "the replaced pair is kept after the GPU is done with it");
    // (sizes going back and forth: at most one pair a size the GPU has not passed)
    for (int i = 0; i < 10; i++) {
        texture_destroy(b);
        b = mask(i % 2 ? 1920 : 1280, i % 2 ? 1080 : 720);
        retirement_value++, frame++;
        mask_stabilize(cmd, &b, 0, 0, 0.85f);
        completed_value = retirement_value;
    }
    frame++;
    mask_stabilize(cmd, &b, 0, 0, 0.85f);
    check(live_history.size() == 2 && history_views() == 2, "history pairs pile up across size changes");
    check(live_views.size() == history_views() + 1, "a view the pass made outlives its image");
    check(!bad_destroy, "something destroyed twice, or never made");
    if (!failed) printf("PASS: the replaced history pairs given back once done, the mask's views the texture's\n");
    return failed;
}
'''


def section(text, start, end):
    first = text.index(start)
    return text[first:text.index(end, first)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--cxx", default="g++")
    parser.add_argument("--vulkan-include", type=Path)
    args = parser.parse_args()
    draw = (args.root / "gpu" / "vk" / "vk_draw.cpp").read_text(encoding="utf-8")
    # (from the end of mask_radius_env to the next function: the pass, with what it keeps beside it)
    radius = draw.index("int mask_radius_env() {")
    after = draw.index("\n}\n", radius) + 3
    passed = draw[after:draw.index("\nvoid draw(VkCommandBuffer cmd", after)]
    if "void mask_stabilize(" not in passed:
        raise SystemExit("vk_draw.cpp: mask_stabilize does not follow mask_radius_env")
    flags = [args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", "-Wno-missing-field-initializers"]
    if args.vulkan_include:
        flags.append("-I" + str(args.vulkan_include))
    with tempfile.TemporaryDirectory(prefix="tree-shadow-mask-resize-") as tmp:
        cpp, exe = Path(tmp) / "fixture.cpp", Path(tmp) / "fixture.exe"
        cpp.write_text(FIXTURE.replace("@PASS@", passed), encoding="utf-8")
        subprocess.run(flags + [str(cpp), "-o", str(exe)], check=True)
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        print(run.stdout, end="")
        if run.returncode:
            raise SystemExit("mask_stabilize across a size change: %s" % run.stdout.strip().splitlines()[0])


if __name__ == "__main__":
    main()

// The device made again while the game runs (vk_device_life.h): on another GPU, or with the other robustness or mesh shaders, on
// a thread of its own once the Insert menu's rows rest, every call into the renderer held meanwhile.
#include "vk_device_life.h"

#include <chrono>
#include <condition_variable>
#include <thread>

#include "device_change.h"
#include "mesh_choice.h"
#include "robust_choice.h"
#include "vk_internal.h"
#include "vk_jobs.h"
#include "vk_menu.h"
#include "vk_shader.h"
#include "vk_work.h"   // (last: the old device's destruction stops RX_VK_RECORDER=thread's recorder first)

namespace mkwvk {
namespace {

using Clock = std::chrono::steady_clock;
double ms_between(Clock::time_point a, Clock::time_point b) { return std::chrono::duration<double, std::milli>(b - a).count(); }
// (how long the rebuild waits for the uses in progress: a call of the game's that waits on another one's work, held at the
// gate, lets go then, and the rebuild is tried again kRetry later)
constexpr auto kGateDeadline = std::chrono::seconds(2);
constexpr auto kRetry = std::chrono::milliseconds(500);
// (how long the rebuild waits for the game's next frame to end before it holds the game anyway: a loading screen that shows
// no frame)
constexpr auto kFrameEndWait = std::chrono::milliseconds(500);
// (a change of the rows is acted on once they rest this long: a player stepping through the GPUs makes one device, not each)
constexpr auto kDebounce = std::chrono::milliseconds(300);
// (when the cost of the programs made again after a rebuild is logged)
constexpr std::chrono::seconds kCostWindows[] = {std::chrono::seconds(10), std::chrono::seconds(60)};

std::mutex request_mu;
std::condition_variable request_cv;
uint64_t requests = 0, handled = 0;   // (request_mu)
int request_gpu_in_use = 0, request_robust_in_use = 0, request_mesh_in_use = 0;   // (the rows that took effect, for the way back: request_mu)
Clock::time_point requested_at;
bool thread_started = false;
std::mutex outcome_mu;
DeviceRebuildOutcome last_outcome;

void publish(const DeviceRebuildOutcome& o) {
    std::lock_guard lk(outcome_mu);
    const uint64_t seq = last_outcome.seq + 1;
    last_outcome = o;
    last_outcome.seq = seq;
}

bool surface_supports(const DeviceFacts& d) {
    if (dev.offscreen || !dev.surface) return true;
    VkBool32 ok = VK_FALSE;   // (VUID-VkSwapchainCreateInfoKHR-surface-01270)
    return vkGetPhysicalDeviceSurfaceSupportKHR(d.physical, d.queue_family, dev.surface, &ok) == VK_SUCCESS && ok;
}
/// A device made by make_device and not adopted: destroyed through its own driver's entry point (the loaded commands are the
/// device in use's)
void destroy_unadopted(DeviceFacts& d) {
    if (!d.device) return;
    if (const auto destroy = (PFN_vkDestroyDevice)vkGetDeviceProcAddr(d.device, "vkDestroyDevice")) destroy(d.device, nullptr);
    d.device = VK_NULL_HANDLE;
}
/// The device in use given up: every module's objects (released: when they were all let go), then the device
void tear_down(Clock::time_point* released = nullptr) {
    device_life_release_all();
    if (released) *released = Clock::now();
    vkDestroyDevice(dev.device, nullptr);
    dev.device = VK_NULL_HANDLE;
}
/// The made device as the one in use, and every module's objects made again on it
bool bring_up(const DeviceFacts& d) {
    adopt_device(d);
    device_generation_advance();
    return device_life_rebuild_all();
}

/// One rebuild, the rows the menu shows now taken as asked. False: it could not start (a use held the gate past the deadline),
/// to be tried again
bool rebuild_once(int gpu_in_use, int robust_in_use, int mesh_in_use) {
    const Clock::time_point t0 = Clock::now();
    device_gate_close_at_frame_end(t0 + kFrameEndWait);
    memory_imports_give_back();
    const Clock::time_point t_held = Clock::now();   // (the game held from here)
    if (!device_gate_close(t_held + kGateDeadline)) {
        logf("vk: device rebuild: the renderer was still in use after %lld ms: tried again", (long long)
             std::chrono::duration_cast<std::chrono::milliseconds>(kGateDeadline).count());
        return false;
    }
    const Clock::time_point t_gate = Clock::now();
    // (every submission recorded and the background work done before the rows are read: the menu, drawn by the presents,
    // changes them no more until the gate opens)
    replay_quiesce();
    jobs_wait_idle();
    const Clock::time_point t_quiet = Clock::now();
    DeviceRebuildOutcome out;
    out.gpu_row = opts.gpu_device, out.robust_row = opts.robust, out.mesh_row = opts.mesh_mode;
    const VkPhysicalDevice want = pick_device();
    const GpuRobustness can = want ? gpu_robustness(want) : GpuRobustness{};
    const bool robust_want =
        robust_choice::effective(robust_choice::requested(opts.robust, getenv("RX_VK_ROBUST")), can.buffer_access2, can.buffer_access);
    const int mesh_want = mesh_choice::requested(opts.mesh_mode, getenv("RX_VK_FORCE_MESH_FALLBACK"));
    const auto change = device_change::needed(dev.physical, dev.robust_buffers, dev.mesh_mode, want, robust_want, mesh_want);
    out.change = change;
    const bool gpu = change == device_change::Change::Gpu, mesh = change == device_change::Change::MeshShaders;
    const Clock::time_point t_picked = Clock::now();
    if (change == device_change::Change::None) {
        device_gate_open();
        out.ok = true;
        out.text = want ? "the GPU device, robust buffers and mesh shaders in use are the ones asked for" : "no GPU with Vulkan 1.3 is listed";
        publish(out);
        return true;
    }
    const VkPhysicalDevice before = dev.physical;
    DeviceFacts made;
    const bool created = make_device(want, made);
    const Clock::time_point t_created = Clock::now();
    if (!created || !surface_supports(made)) {
        destroy_unadopted(made);
        opts.gpu_device = gpu_in_use, opts.robust = robust_in_use, opts.mesh_mode = mesh_in_use;
        device_gate_open();
        logf("vk: device rebuild: no device could be made %s: the device in use stays",
             gpu ? "on the GPU asked for" : mesh ? "with the mesh shaders asked for" : "with the robust buffers asked for");
        out.ok = false, out.gpu_row = gpu_in_use, out.robust_row = robust_in_use, out.mesh_row = mesh_in_use;
        out.text = gpu    ? "the GPU asked for could not be set up: the one in use stays"
                   : mesh ? "the mesh shaders asked for could not be set up: the device in use stays"
                          : "the robust buffers asked for could not be set up: the device in use stays";
        publish(out);
        return true;
    }
    const Clock::time_point t_made = Clock::now();
    Clock::time_point t_released;
    tear_down(&t_released);
    const Clock::time_point t_down = Clock::now();
    bool ok = bring_up(made);
    if (!ok) {   // (the whole device again on the GPU and with the robustness before)
        tear_down();
        opts.gpu_device = gpu_in_use, opts.robust = robust_in_use, opts.mesh_mode = mesh_in_use;
        DeviceFacts back;
        if (!make_device(before, back) || !bring_up(back))
            replay_fatal("device rebuild: neither the device asked for nor the one before could be set up again");
        out.gpu_row = gpu_in_use, out.robust_row = robust_in_use, out.mesh_row = mesh_in_use;
        out.text = gpu    ? "the GPU asked for failed to set up: the one before was set up again"
                   : mesh ? "the mesh shaders asked for failed to set up: the device before was set up again"
                          : "the robust buffers asked for failed to set up: the device before was set up again";
    } else {
        out.text = gpu    ? "the device was made again on the GPU asked for"
                   : mesh ? "the device was made again with the mesh shaders asked for"
                          : "the device was made again with the robust buffers asked for";
    }
    const Clock::time_point t_up = Clock::now();
    device_gate_open();
    out.ok = ok, out.rebuilt = true;
    out.pause_ms = ms_between(t_held, t_up);
    logf("vk: device rebuild (%s, robust buffers %s, mesh shaders %s): %s; %s, Vulkan %u.%u; frame end %.1f ms, then the game held: gate %.1f ms, "
         "work done %.1f ms, GPU picked %.1f ms, device made %.1f ms, surface checked %.1f ms, modules let go %.1f ms, device "
         "destroyed %.1f ms, set up %.1f ms: %.1f ms in all",
         gpu ? "another GPU" : "the same GPU", dev.robust_buffers ? "on" : "off",
         dev.mesh_mode == mesh_choice::kCompute ? "Compute" : dev.mesh_mode == mesh_choice::kNative ? "Native" : "Automatic",
         ok ? "done" : "failed, the device before set up again", dev.props.deviceName, VK_API_VERSION_MAJOR(dev.props.apiVersion),
         VK_API_VERSION_MINOR(dev.props.apiVersion), ms_between(t0, t_held), ms_between(t_held, t_gate), ms_between(t_gate, t_quiet),
         ms_between(t_quiet, t_picked), ms_between(t_picked, t_created), ms_between(t_created, t_made), ms_between(t_made, t_released),
         ms_between(t_released, t_down), ms_between(t_down, t_up), out.pause_ms);
    publish(out);
    return true;
}

void rebuild_main() {
    SetThreadDescription(GetCurrentThread(), L"mkw_vk device rebuild");
    for (;;) {
        int gpu_in_use = 0, robust_in_use = 0, mesh_in_use = 0;
        {
            std::unique_lock lk(request_mu);
            request_cv.wait(lk, [] { return requests != handled; });
            while (Clock::now() < requested_at + kDebounce) request_cv.wait_until(lk, requested_at + kDebounce);
            handled = requests;
            gpu_in_use = request_gpu_in_use, robust_in_use = request_robust_in_use, mesh_in_use = request_mesh_in_use;
        }
        while (!rebuild_once(gpu_in_use, robust_in_use, mesh_in_use)) std::this_thread::sleep_for(kRetry);
        if (!device_rebuild_outcome().rebuilt) continue;
        // (the programs made again in play since: translated, or read back from the program cache. Logged after kCostWindows,
        // or sooner when the rows change again)
        int64_t translated0 = 0, failed0 = 0;
        shader_stats(&translated0, &failed0);
        const double ms0 = shader_translate_ms();
        const int64_t hits0 = shader_cache_hits();
        const Clock::time_point since = Clock::now();
        for (const auto window : kCostWindows) {
            {
                std::unique_lock lk(request_mu);
                if (request_cv.wait_until(lk, since + window, [] { return requests != handled; })) break;
            }
            int64_t translated = 0, failed = 0;
            shader_stats(&translated, &failed);
            logf("vk: device rebuild: %.0f s since, %lld programs translated (%.0f ms of translation), %lld read back from the program "
                 "cache, %lld failed", ms_between(since, Clock::now()) / 1000.0, (long long)(translated - translated0),
                 shader_translate_ms() - ms0, (long long)(shader_cache_hits() - hits0), (long long)(failed - failed0));
        }
    }
}

} // namespace

void device_rebuild_request(int gpu_row_in_use, int robust_row_in_use, int mesh_row_in_use) {
    std::lock_guard lk(request_mu);
    requests++;
    requested_at = Clock::now();
    request_gpu_in_use = gpu_row_in_use, request_robust_in_use = robust_row_in_use, request_mesh_in_use = mesh_row_in_use;
    if (!thread_started) {
        thread_started = true;
        std::thread(rebuild_main).detach();
    }
    request_cv.notify_all();
}

DeviceRebuildOutcome device_rebuild_outcome() {
    std::lock_guard lk(outcome_mu);
    return last_outcome;
}

} // namespace mkwvk

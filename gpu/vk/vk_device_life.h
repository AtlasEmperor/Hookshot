// The VkDevice's lifetime (vk_device_life.cpp): its generation, each module's part in a rebuild on another GPU or with
// other device features, and the gate that holds the game's calls into the renderer while the device is replaced.
#pragma once

#include <atomic>
#include <chrono>
#include <cstdint>
#include <mutex>

#include "device_change.h"

namespace mkwvk {

/// The device's generation: 1 for the first VkDevice, one more for each rebuild
uint64_t device_generation();

/// A module's part in a device rebuild, registered at start-up by a namespace-scope object. order: modules are rebuilt
/// in increasing order and released in decreasing order (kDeviceOrder*). Each function may be null.
/// release: on the old device, every queue idle and nothing recording: the module's device objects destroyed, its tables
///   emptied and its latches reset, so that its next use makes them on the device then in use.
/// rebuild: on the new device, after its commands are loaded: what the module made at start-up and never makes on use.
///   False: the module could not (logged), and the rebuild fails.
/// thread: on a thread that records, at its first device use after a rebuild: that thread's thread_local caches reset.
struct DeviceLife {
    DeviceLife(int order, const char* module, void (*release)(), bool (*rebuild)(), void (*thread)());
};
// (the order of the modules: each one's objects may use those of a lower one, never of a higher one)
constexpr int kDeviceOrderAllocator = 0;   // (VMA: every buffer and image of the others)
constexpr int kDeviceOrderMemory = 10;     // (guest memory imports, mirrors, streams)
constexpr int kDeviceOrderTextures = 20;
constexpr int kDeviceOrderPrograms = 30;
constexpr int kDeviceOrderDraws = 40;      // (pipelines, samplers, draw buffers)
constexpr int kDeviceOrderReplay = 50;     // (recordings, frames, timelines)
constexpr int kDeviceOrderSwapchain = 55;  // (the window's swapchain: the presentation's views of its images go first)
constexpr int kDeviceOrderUpscaler = 58;   // (the upscalers' own state, NGX's: after the chains that drive them let go)
constexpr int kDeviceOrderPresent = 60;    // (presentation: frame generation, the overlays, the upscalers' chains, profiling)

// (the rebuild's own steps, vk_device_rebuild.cpp) the gate closed: true once no use is in progress, false when one still is
// at the deadline (the gate open again); the gate open; every module's release, in decreasing order; every module's rebuild,
// in increasing order (false: one failed, logged); the generation advanced, with the calling thread's caches
bool device_gate_close(std::chrono::steady_clock::time_point deadline);
/// A rebuild holds new uses at the gate (a use begun now waits for it)
bool device_gate_closed();
void device_gate_open();
void device_life_release_all();
bool device_life_rebuild_all();
void device_generation_advance();

/// The calling thread's thread_local caches reset when the device changed since its last device use (every module's
/// thread step). Called where a thread starts recording or building on the device.
void device_thread_sync();

/// A value worked out from the device in use (a fact of its GPU, a measured property, a lazily made object's handle):
/// worked out again at its first use on each device. Safe from any thread.
template <class T>
class DeviceLatch {
public:
    template <class Make>
    const T& get(Make&& make) {
        const uint64_t now = device_generation();
        if (seen_.load(std::memory_order_acquire) == now) return value_;
        std::lock_guard lk(mu_);
        if (seen_.load(std::memory_order_relaxed) != now) {
            value_ = make();
            seen_.store(now, std::memory_order_release);
        }
        return value_;
    }

private:
    std::mutex mu_;
    std::atomic<uint64_t> seen_{0};
    T value_{};
};

/// A thread's cache of what it found on the device (handles, entries of a module's tables), as a thread_local: emptied
/// at its first use after a rebuild
template <class T>
struct DeviceLocal {
    T& get() {
        const uint64_t now = device_generation();
        if (seen != now) value = T{}, seen = now;
        return value;
    }
    T* operator->() { return &get(); }
    uint64_t seen = 0;
    T value{};
};

/// Inside a DeviceUse, between two slices of a long wait (no lock held): a rebuild waiting for the gate runs now, and the wait
/// goes on after it, on the new device
void device_use_yield();

/// The Insert menu's GPU device or Robust buffers row changed (rows in use: what took effect, for the way back on a failure).
/// A thread of its own makes the device again once the rows rest, when the effective choice differs from the device in use
void device_rebuild_request(int gpu_row_in_use, int robust_row_in_use);
/// The last request's outcome: seq counts the outcomes (0: none yet); the rows that took effect (the ones asked for, or the
/// ones before on a failure), the change asked for, what the player is told, and the time the game was held when the device
/// was made again
struct DeviceRebuildOutcome {
    uint64_t seq = 0;
    bool ok = true, rebuilt = false;
    device_change::Change change = device_change::Change::None;
    int gpu_row = 0, robust_row = 0;
    const char* text = "";   // (a static string)
    double pause_ms = 0;
};
DeviceRebuildOutcome device_rebuild_outcome();

/// The renderer's use of the device by one caller (a call from the game, one step of a background thread): while a
/// rebuild runs, a new use waits for it to end; a rebuild starts only when no use is in progress. Nested uses on one
/// thread count once.
class DeviceUse {
public:
    DeviceUse();
    ~DeviceUse();
    DeviceUse(const DeviceUse&) = delete;
    DeviceUse& operator=(const DeviceUse&) = delete;
};

} // namespace mkwvk

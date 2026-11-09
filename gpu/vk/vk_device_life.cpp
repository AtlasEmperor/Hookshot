// The VkDevice's lifetime (vk_device_life.h): its generation, the modules' rebuild steps and the gate on device uses.
#include "vk_device_life.h"

#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <vector>

#include "vk_internal.h"

namespace mkwvk {
namespace {

struct Step {
    int order;
    const char* module;
    void (*release)();
    bool (*rebuild)();
    void (*thread)();
};
// (a function's static: the DeviceLife objects of the other files register during static initialization, in any order)
std::vector<Step>& steps() {
    static std::vector<Step> all;
    return all;
}

std::atomic<uint64_t> generation{1};
thread_local uint64_t thread_generation = 1;

// (the gate: users counts the uses in progress, closed holds new ones at the door. A use counts itself before it looks at
// closed, and the rebuild closes before it reads users, both sequentially consistent: one of them always sees the other)
std::atomic<int> users{0};
std::atomic<bool> closed{false};
std::mutex gate_mu;
std::condition_variable gate_cv;
thread_local int use_depth = 0;

void leave() {
    if (users.fetch_sub(1) == 1 && closed.load()) {
        std::lock_guard lk(gate_mu);
        gate_cv.notify_all();
    }
}
void enter() {
    for (;;) {
        users.fetch_add(1);
        if (!closed.load()) return;
        leave();
        std::unique_lock lk(gate_mu);
        gate_cv.wait(lk, [] { return !closed.load(); });
    }
}

} // namespace

bool device_gate_close(std::chrono::steady_clock::time_point deadline) {
    closed.store(true);
    std::unique_lock lk(gate_mu);
    if (gate_cv.wait_until(lk, deadline, [] { return users.load() == 0; })) return true;
    closed.store(false);
    gate_cv.notify_all();
    return false;
}
bool device_gate_closed() { return closed.load(); }
void device_gate_open() {
    {
        std::lock_guard lk(gate_mu);
        closed.store(false);
    }
    gate_cv.notify_all();
}

void device_life_release_all() {
    std::vector<Step>& all = steps();
    for (auto it = all.rbegin(); it != all.rend(); ++it)
        if (it->release) it->release();
}
bool device_life_rebuild_all() {
    for (const Step& s : steps()) {
        if (s.rebuild && !s.rebuild()) {
            logf("vk: device rebuild: %s could not be made again", s.module);
            return false;
        }
    }
    return true;
}

void device_generation_advance() {
    generation.fetch_add(1, std::memory_order_acq_rel);
    device_thread_sync();
}

uint64_t device_generation() {
    return generation.load(std::memory_order_acquire);
}

DeviceLife::DeviceLife(int order, const char* module, void (*release)(), bool (*rebuild)(), void (*thread)()) {
    std::vector<Step>& all = steps();
    all.push_back({order, module, release, rebuild, thread});
    std::stable_sort(all.begin(), all.end(), [](const Step& a, const Step& b) { return a.order < b.order; });
}

void device_thread_sync() {
    const uint64_t now = device_generation();
    if (thread_generation == now) return;
    for (const Step& s : steps())
        if (s.thread) s.thread();
    thread_generation = now;
}

DeviceUse::DeviceUse() {
    if (use_depth++) return;
    enter();
    device_thread_sync();
}

DeviceUse::~DeviceUse() {
    if (--use_depth) return;
    leave();
}

void device_use_yield() {
    if (use_depth != 1 || !closed.load()) return;
    leave();
    enter();
    device_thread_sync();
}

} // namespace mkwvk

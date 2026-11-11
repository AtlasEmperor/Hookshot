// The device lifetime's mechanism (gpu/vk/vk_device_life.cpp) and the rebuild's decision (gpu/vk/device_change.h), with no GPU:
// the steps' order, the latches and thread caches across a generation, and the gate with uses in progress.
#include "device_change.h"
#include "vk_device_life.h"

#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <thread>
#include <vector>

#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); std::exit(1); } } while (0)

namespace mkwvk {
void logf(const char*, ...) {}
}
using namespace mkwvk;
using namespace std::chrono_literals;

namespace {
std::string calls;
bool memory_fails = false;
thread_local int thread_cache = 0;
void release_draws() { calls += "d-"; }
void release_memory() { calls += "m-"; }
bool rebuild_draws() { calls += "d+"; return true; }
bool rebuild_memory() { calls += "m+"; return !memory_fails; }
void thread_draws() { thread_cache = 0; }
// (registered out of order, as files' static objects are)
const DeviceLife draws(kDeviceOrderDraws, "draws", release_draws, rebuild_draws, thread_draws);
const DeviceLife memory(kDeviceOrderMemory, "memory", release_memory, rebuild_memory, nullptr);
} // namespace

int main() {
    // The steps: released from the highest order down, made again from the lowest up; a failed step fails the rebuild there.
    device_life_release_all();
    CHECK(calls == "d-m-");
    calls.clear();
    CHECK(device_life_rebuild_all() && calls == "m+d+");
    memory_fails = true, calls.clear();
    CHECK(!device_life_rebuild_all() && calls == "m+");
    memory_fails = false;

    // A latch works its value out once a device; a thread's cache and a DeviceLocal are emptied at their first use after a rebuild.
    int made = 0;
    DeviceLatch<int> latch;
    const auto make = [&made] { return ++made * 10; };
    CHECK(latch.get(make) == 10 && latch.get(make) == 10 && made == 1);
    static thread_local DeviceLocal<std::vector<int>> local;
    local->push_back(7);
    thread_cache = 5;
    const uint64_t before = device_generation();
    device_generation_advance();
    CHECK(device_generation() == before + 1);
    CHECK(latch.get(make) == 20 && made == 2);
    CHECK(local->empty());
    CHECK(thread_cache == 0);   // (the advancing thread's own caches)
    std::thread([] {
        thread_cache = 3;
        device_thread_sync();   // (a thread that last used the device before: its caches go)
        CHECK(thread_cache == 0);
        thread_cache = 3;
        device_thread_sync();   // (and only once a generation)
        CHECK(thread_cache == 3);
    }).join();

    // The gate: it closes only once no use is in progress, opens again when one stays past the deadline, and a use started while
    // it is closed waits for it to open.
    std::atomic<bool> holding{false}, let_go{false};
    std::thread user([&] {
        DeviceUse use;
        holding = true;
        while (!let_go) std::this_thread::sleep_for(1ms);
    });
    while (!holding) std::this_thread::sleep_for(1ms);
    CHECK(!device_gate_close(std::chrono::steady_clock::now() + 50ms));
    {
        DeviceUse nested_ok;   // (open again: a use goes in at once)
    }
    let_go = true;
    user.join();
    CHECK(device_gate_close(std::chrono::steady_clock::now() + 1s));
    std::atomic<bool> entered{false};
    std::thread late([&] {
        DeviceUse use;
        entered = true;
    });
    std::this_thread::sleep_for(50ms);
    CHECK(!entered && device_gate_closed());   // (held at the door while the device is replaced)
    device_gate_open();
    late.join();
    CHECK(!device_gate_closed());
    CHECK(entered);

    // A long wait inside a use, sliced, lets a rebuild in between two slices, then goes on.
    std::atomic<bool> waiting{false}, done{false};
    std::atomic<int> slices{0};
    std::thread waiter([&] {
        DeviceUse use;
        waiting = true;
        while (!done) {
            std::this_thread::sleep_for(1ms);
            device_use_yield();
            slices++;
        }
    });
    while (!waiting) std::this_thread::sleep_for(1ms);
    CHECK(device_gate_close(std::chrono::steady_clock::now() + 1s));
    const int held_at = slices.load();
    std::this_thread::sleep_for(30ms);
    CHECK(slices.load() <= held_at + 1);   // (parked in its yield while the gate is closed)
    device_gate_open();
    done = true;
    waiter.join();

    // A frame's end: a rebuild waiting for one closes the gate inside the present's use, and the game's next call waits at
    // the door. Without a frame, the gate closes at the time given; without a rebuild waiting, a frame's end changes nothing.
    device_frame_end();
    {
        DeviceUse open_ok;
    }
    std::atomic<bool> held{false};
    std::thread closer([&] {
        device_gate_close_at_frame_end(std::chrono::steady_clock::now() + 5s);
        held = true;
    });
    std::this_thread::sleep_for(30ms);
    CHECK(!held);   // (waiting for the frame to end, the game running)
    const auto frame_at = std::chrono::steady_clock::now();
    std::atomic<bool> frames_stop{false};
    // (the game's frames, each ending inside its present's use: one ended before the rebuild waits for it changes nothing)
    std::thread frames([&] {
        while (!frames_stop) {
            {
                DeviceUse present;
                device_frame_end();
            }
            std::this_thread::sleep_for(5ms);
        }
    });
    closer.join();
    CHECK(held && std::chrono::steady_clock::now() - frame_at < 4s);   // (at a frame's end, well before the 5 s deadline)
    frames_stop = true;   // (its next present waits at the door until the gate opens)
    std::atomic<bool> next_call{false};
    std::thread game([&] {
        DeviceUse use;
        next_call = true;
    });
    std::this_thread::sleep_for(30ms);
    CHECK(!next_call);
    CHECK(device_gate_close(std::chrono::steady_clock::now() + 1s));
    device_gate_open();
    game.join();
    frames.join();
    CHECK(next_call);
    const auto no_frame_at = std::chrono::steady_clock::now();
    device_gate_close_at_frame_end(no_frame_at + 50ms);
    CHECK(std::chrono::steady_clock::now() - no_frame_at >= 50ms);
    CHECK(device_gate_close(std::chrono::steady_clock::now() + 1s));
    device_gate_open();

    // The decision: another GPU, the same GPU with the robustness crossing Off or other mesh shaders, or nothing (no GPU
    // listed: the one in use stays).
    using device_change::Change;
    int a = 0, b = 0;
    CHECK(device_change::needed(&a, true, 0, &b, true, 0) == Change::Gpu);
    CHECK(device_change::needed(&a, true, 0, &b, true, 2) == Change::Gpu);
    CHECK(device_change::needed(&a, true, 0, &a, false, 0) == Change::Robustness);
    CHECK(device_change::needed(&a, false, 0, &a, true, 0) == Change::Robustness);
    CHECK(device_change::needed(&a, true, 0, &a, true, 2) == Change::MeshShaders);
    CHECK(device_change::needed(&a, true, 2, &a, true, 1) == Change::MeshShaders);
    CHECK(device_change::needed(&a, true, 1, &a, true, 1) == Change::None);
    CHECK(device_change::needed(&a, true, 0, nullptr, false, 2) == Change::None);
    std::puts("PASS: steps in order, latches and thread caches per device, the gate with uses in progress and at a frame's end, "
              "the rebuild's decision");
}

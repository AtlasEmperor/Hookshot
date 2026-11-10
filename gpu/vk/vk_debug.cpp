#include "vk_debug.h"

#include <algorithm>
#include <array>
#include <atomic>
#include <charconv>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <unordered_map>

namespace mkwvk {
void logf(const char* format, ...);

namespace {
using Clock = std::chrono::steady_clock;
constexpr auto kRecordingDuration = std::chrono::seconds(kDebugRecordingSeconds);
constexpr size_t kHistoryLineBytes = 1024;
constexpr size_t kHistoryEntryReserveBytes = 64;   // room kept for one more "present:exposure" entry in a dump line

struct ExposureReading { int64_t present; uint32_t word; };

struct DebugRecorder {
    std::mutex mutex;
    DebugState view;
    bool initialized = false;
    int64_t first_present = 0;   // the recording logs from this presentation on
    bool waiting = false;        // armed by the environment, its time limit starting at first_present
    Clock::time_point deadline{};
    uint32_t exposure_remaining = 0;
    bool exposure_every = false;   // RX_VK_EXPOSURE_LOG=2: every reading of the session, outside any recording's bounds
    std::unordered_map<uint64_t, uint64_t> resets;   // samples-passed resets seen per queue during the recording
    std::array<ExposureReading, kDebugExposureHistory> history{};
    uint32_t history_at = 0, history_size = 0;
    std::atomic<int64_t> present{0};
    std::atomic<bool> sample_on{false}, exposure_on{false}, recording_on{false};   // lock-free gates of the hot paths
};

DebugRecorder& debug_recorder() {
    static DebugRecorder recorder;
    return recorder;
}

/// The whole text as a non-negative integer, else -1.
int64_t parse_nonnegative(const char* text) {
    if (!text) return -1;
    int64_t value = -1;
    const char* end = text + std::strlen(text);
    const auto parsed = std::from_chars(text, end, value);
    return parsed.ec == std::errc{} && parsed.ptr == end && value >= 0 ? value : -1;
}

/// The environment variable as a non-negative integer; -1 when unset, or set to anything else (which is logged).
int64_t environment_count(const char* name) {
    const char* text = std::getenv(name);
    const int64_t value = parse_nonnegative(text);
    if (text && value < 0) logf("vk: %s=\"%s\" ignored: not a non-negative integer", name, text);
    return value;
}

void update_flags(DebugRecorder& recorder) {
    const DebugState& view = recorder.view;
    recorder.sample_on.store(view.recording && view.samples && view.remaining, std::memory_order_relaxed);
    recorder.exposure_on.store(view.exposure != 0, std::memory_order_relaxed);
    recorder.recording_on.store(view.recording, std::memory_order_relaxed);
}

void stop_locked(DebugRecorder& recorder, const char* reason) {
    if (!recorder.view.recording) return;
    recorder.view.recording = false;
    update_flags(recorder);
    logf("vk: diagnostic recording %llu stopped (%s)", (unsigned long long)recorder.view.recording_id, reason);
}

bool start_locked(DebugRecorder& recorder, int64_t first, bool wait) {
    DebugState& view = recorder.view;
    if (!view.samples && !view.exposure) return false;
    ++view.recording_id;
    view.recording = true;
    view.remaining = view.samples ? kDebugSampleReportLimit : 0;
    recorder.exposure_remaining = kDebugExposureReadingLimit;
    recorder.first_present = first;
    recorder.waiting = wait;
    recorder.deadline = Clock::now() + kRecordingDuration;
    recorder.resets.clear();
    update_flags(recorder);
    logf("vk: diagnostic recording %llu armed at present %lld (samples %d, exposure %d; %d seconds maximum)",
         (unsigned long long)view.recording_id, (long long)first, view.samples, view.exposure, kDebugRecordingSeconds);
    return true;
}

/// Whether the recording logs at this presentation; stops it when its time limit has passed.
bool active_locked(DebugRecorder& recorder, int64_t present) {
    if (!recorder.view.recording || present < recorder.first_present) return false;
    if (recorder.waiting) {
        recorder.waiting = false;
        recorder.deadline = Clock::now() + kRecordingDuration;
    }
    if (Clock::now() >= recorder.deadline) {
        stop_locked(recorder, "time limit");
        return false;
    }
    return true;
}

void dump_locked(const DebugRecorder& recorder, const char* why) {
    if (!recorder.history_size) return;
    char line[kHistoryLineBytes];
    int used = std::snprintf(line, sizeof line, "vk: %s: exposure by present:", why);
    const uint32_t first = (recorder.history_at + kDebugExposureHistory - recorder.history_size) % kDebugExposureHistory;
    for (uint32_t i = 0; i < recorder.history_size && (size_t)used < sizeof line - kHistoryEntryReserveBytes; ++i) {
        const ExposureReading& reading = recorder.history[(first + i) % kDebugExposureHistory];
        float exposure;
        std::memcpy(&exposure, &reading.word, sizeof exposure);
        used += std::snprintf(line + used, sizeof line - used, " %lld:%.5g", (long long)reading.present, exposure);
    }
    logf("%s", line);
}
} // namespace

void debug_settings_init(int samples, int exposure) {
    DebugRecorder& recorder = debug_recorder();
    std::lock_guard lock(recorder.mutex);
    if (recorder.initialized) return;
    recorder.initialized = true;
    recorder.view.samples = samples != 0;
    recorder.view.exposure = std::clamp(exposure, 0, kDebugExposureEachReading);
    const int64_t first = environment_count("RX_VK_LOG_SAMPLES");
    const int64_t environment_exposure = environment_count("RX_VK_EXPOSURE_LOG");
    if (first >= 0) recorder.view.samples = 1;
    if (environment_exposure >= 0)
        recorder.view.exposure = (int)std::min<int64_t>(environment_exposure, kDebugExposureEachReading);
    recorder.exposure_every = environment_exposure == kDebugExposureEachReading;
    update_flags(recorder);
    if (first >= 0) start_locked(recorder, first, true);   // saved choices alone never arm a recording
}

void debug_settings_set(int samples, int exposure) {
    DebugRecorder& recorder = debug_recorder();
    std::lock_guard lock(recorder.mutex);
    samples = samples != 0;
    exposure = std::clamp(exposure, 0, kDebugExposureEachReading);
    if (recorder.view.samples == samples && recorder.view.exposure == exposure) return;
    stop_locked(recorder, "settings changed");
    recorder.view.samples = samples;
    recorder.view.exposure = exposure;
    if (exposure != kDebugExposureEachReading) recorder.exposure_every = false;
    if (!exposure) recorder.history_size = recorder.history_at = 0;
    update_flags(recorder);
}

void debug_recording_start() {
    DebugRecorder& recorder = debug_recorder();
    std::lock_guard lock(recorder.mutex);
    if (!start_locked(recorder, recorder.present.load(std::memory_order_relaxed), false))
        logf("vk: diagnostic recording not started: no report is selected");
}

void debug_recording_stop() {
    DebugRecorder& recorder = debug_recorder();
    std::lock_guard lock(recorder.mutex);
    if (!recorder.view.recording) logf("vk: diagnostic recording not stopped: none is running");
    stop_locked(recorder, "requested");
}

void debug_mark_flash() {
    DebugRecorder& recorder = debug_recorder();
    std::lock_guard lock(recorder.mutex);
    ++recorder.view.flash_markers;
    logf("vk: flash marker %llu at present %lld (recording %llu)", (unsigned long long)recorder.view.flash_markers,
         (long long)recorder.present.load(std::memory_order_relaxed), (unsigned long long)recorder.view.recording_id);
    dump_locked(recorder, "manual flash marker");
}

DebugState debug_state() {
    DebugRecorder& recorder = debug_recorder();
    std::lock_guard lock(recorder.mutex);
    active_locked(recorder, recorder.present.load(std::memory_order_relaxed));
    return recorder.view;
}

void debug_present(int64_t present) {
    DebugRecorder& recorder = debug_recorder();
    recorder.present.store(present, std::memory_order_relaxed);
    if (!recorder.recording_on.load(std::memory_order_relaxed)) return;
    std::lock_guard lock(recorder.mutex);
    active_locked(recorder, present);
}

void debug_samples_reset(uint64_t queue) {
    DebugRecorder& recorder = debug_recorder();
    if (!recorder.sample_on.load(std::memory_order_relaxed)) return;
    std::lock_guard lock(recorder.mutex);
    if (recorder.view.recording && recorder.view.samples && recorder.view.remaining) ++recorder.resets[queue];
}

void debug_samples_report(int64_t present, uint64_t queue, uint64_t address, uint64_t value, bool written) {
    DebugRecorder& recorder = debug_recorder();
    if (!recorder.sample_on.load(std::memory_order_relaxed)) return;
    std::lock_guard lock(recorder.mutex);
    DebugState& view = recorder.view;
    if (!active_locked(recorder, present) || !view.samples || !view.remaining) return;
    const auto found = recorder.resets.find(queue);
    const uint64_t resets = found == recorder.resets.end() ? 0 : found->second;
    logf("vk: samples present %lld queue %#llx reset %llu addr %#llx value %llu written %u", (long long)present,
         (unsigned long long)queue, (unsigned long long)resets, (unsigned long long)address,
         (unsigned long long)value, (unsigned)written);
    --view.remaining;
    if (!view.remaining) {
        logf("vk: samples trace stopped after %u reports", kDebugSampleReportLimit);
        if (view.exposure != kDebugExposureEachReading || !recorder.exposure_remaining) stop_locked(recorder, "report limit");
        update_flags(recorder);
    }
}

bool debug_exposure_enabled() {
    return debug_recorder().exposure_on.load(std::memory_order_relaxed);
}

void debug_exposure_note(int64_t present, uint32_t word) {
    DebugRecorder& recorder = debug_recorder();
    if (!recorder.exposure_on.load(std::memory_order_relaxed)) return;
    std::lock_guard lock(recorder.mutex);
    if (!recorder.view.exposure) return;
    // The final pass can draw more than once in a presentation: the history and the log keep every reading.
    recorder.history[recorder.history_at] = {present, word};
    recorder.history_at = (recorder.history_at + 1) % kDebugExposureHistory;
    recorder.history_size = std::min(recorder.history_size + 1, kDebugExposureHistory);
    const bool each = recorder.view.exposure == kDebugExposureEachReading;
    const bool recorded = each && !recorder.exposure_every && active_locked(recorder, present) && recorder.exposure_remaining;
    if (!each || !(recorder.exposure_every || recorded)) return;
    float exposure;
    std::memcpy(&exposure, &word, sizeof exposure);
    logf("vk: exposure %lld %g", (long long)present, exposure);
    if (recorded && !--recorder.exposure_remaining) {
        logf("vk: exposure trace stopped after %u readings", kDebugExposureReadingLimit);
        if (!recorder.view.samples || !recorder.view.remaining) stop_locked(recorder, "report limit");
    }
}

void debug_exposure_dump(const char* why) {
    DebugRecorder& recorder = debug_recorder();
    std::lock_guard lock(recorder.mutex);
    dump_locked(recorder, why);
}

} // namespace mkwvk

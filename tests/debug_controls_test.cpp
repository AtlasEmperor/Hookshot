// Exercise the production diagnostic controller without a Vulkan device or a game.
#include <algorithm>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <thread>
#include <vector>

std::vector<std::string> lines;
namespace mkwvk {
void logf(const char* format, ...) {
    char line[1200];
    va_list args;
    va_start(args, format);
    std::vsnprintf(line, sizeof line, format, args);
    va_end(args);
    lines.emplace_back(line);
}
}
#include "vk_debug.cpp"
using namespace mkwvk;
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "failed line %d: %s\n", __LINE__, #x); std::exit(1); } } while (0)

constexpr int64_t kWaitedPresent = 600;   // RX_VK_LOG_SAMPLES=600 in the environment mode
constexpr int kWorkers = 4, kReportsPerWorker = 100;
constexpr int kReadingsPerPresentation = 2;   // the live mode notes two readings per presentation

uint32_t bits(float value) {
    uint32_t word;
    std::memcpy(&word, &value, sizeof word);
    return word;
}
size_t count(const char* prefix) {
    return std::count_if(lines.begin(), lines.end(), [&](const std::string& line) { return line.starts_with(prefix); });
}
bool contains(const std::string& line, const char* text) { return line.find(text) != std::string::npos; }

void environment_mode() {
    debug_settings_init(0, 0);
    CHECK(debug_state().samples == 1 && debug_state().exposure == kDebugExposureEachReading && debug_state().recording);
    lines.clear();
    debug_present(kWaitedPresent - 1);
    debug_samples_report(kWaitedPresent - 1, 1, 0x10, 12, true);
    debug_exposure_note(kWaitedPresent - 1, bits(0.5f));
    CHECK(count("vk: samples present") == 0 && count("vk: exposure ") == 1);   // samples wait for their presentation
    debug_present(kWaitedPresent);
    debug_samples_report(kWaitedPresent, 1, 0x10, 12, true);
    debug_exposure_note(kWaitedPresent, bits(0.5f));
    CHECK(count("vk: samples present") == 1 && count("vk: exposure ") == 2);
    // RX_VK_EXPOSURE_LOG=2 logs every reading of the session: past a recording's reading limit and its time limit.
    const int64_t past_limit = kWaitedPresent + 2 * kDebugExposureReadingLimit;
    for (int64_t present = kWaitedPresent + 1; present < past_limit; ++present) debug_exposure_note(present, bits(1.0f));
    debug_recorder().deadline = Clock::now() - std::chrono::seconds(1);
    debug_present(past_limit);
    debug_exposure_note(past_limit, bits(1.0f));
    CHECK(count("vk: exposure ") == 2 + (size_t)(past_limit - kWaitedPresent) && count("vk: exposure trace stopped") == 0);
    // Several readings in one presentation: each is logged, in order.
    const size_t before = count("vk: exposure ");
    for (const float reading : {1.5f, 2.5f, 3.5f}) debug_exposure_note(past_limit + 1, bits(reading));
    CHECK(count("vk: exposure ") == before + 3);
    CHECK(lines.back() == "vk: exposure " + std::to_string(past_limit + 1) + " 3.5");
    CHECK(lines[lines.size() - 3] == "vk: exposure " + std::to_string(past_limit + 1) + " 1.5");
    std::puts("PASS: explicit environment recording threshold, unbounded exposure log and effective selections");
}

void invalid_environment_mode() {
    debug_settings_init(1, 1);
    CHECK(!debug_state().recording && debug_state().samples == 1 && debug_state().exposure == 1);
    CHECK(count("vk: RX_VK_LOG_SAMPLES=\"bad\" ignored") == 1 && count("vk: RX_VK_EXPOSURE_LOG=\"-2\" ignored") == 1);
    std::puts("PASS: invalid environment values are reported and leave the saved choices");
}

void live_mode() {
    debug_settings_init(1, 1);
    CHECK(!debug_state().recording);   // saved preferences never start a recording
    debug_present(10);
    debug_samples_report(10, 1, 0x10, 12, true);
    CHECK(lines.empty());
    debug_recording_start();
    const uint64_t first_id = debug_state().recording_id;
    CHECK(debug_state().recording && debug_state().remaining == kDebugSampleReportLimit);
    debug_samples_reset(1);
    debug_samples_report(10, 1, 0x10, 12, false);
    CHECK(contains(lines.back(), "reset 1 addr 0x10 value 12 written 0"));
    debug_recording_stop();
    CHECK(!debug_state().recording);
    debug_recording_start();
    CHECK(debug_state().recording_id == first_id + 1 && debug_state().remaining == kDebugSampleReportLimit);
    debug_samples_report(10, 1, 0x10, 12, true);
    CHECK(contains(lines.back(), "reset 0"));

    debug_settings_set(0, kDebugExposureEachReading);
    CHECK(!debug_state().recording && debug_exposure_enabled());
    lines.clear();
    debug_exposure_note(10, bits(0.25f));
    debug_exposure_note(10, bits(0.5f));
    CHECK(lines.empty());   // each-reading logging still requires an explicit recording
    debug_mark_flash();
    CHECK(count("vk: flash marker") == 1 && contains(lines.back(), " 10:0.25 10:0.5"));   // every reading of a presentation, in order

    debug_recording_start();
    lines.clear();
    const int64_t last_present = 10 + kDebugExposureReadingLimit + kDebugExposureHistory;
    for (int64_t present = 11; present <= last_present; ++present) {
        debug_present(present);
        debug_exposure_note(present, bits(1.0f));
        debug_exposure_note(present, bits(2.0f));
    }
    CHECK(count("vk: exposure ") == kDebugExposureReadingLimit + 1);   // the readings plus the limit notice
    CHECK(!debug_state().recording);
    debug_mark_flash();
    // The history holds the last kDebugExposureHistory readings: both readings of each of the last presentations they span.
    const int64_t oldest = last_present - kDebugExposureHistory / kReadingsPerPresentation + 1;
    const std::string kept = " " + std::to_string(oldest) + ":1 " + std::to_string(oldest) + ":2";
    const std::string evicted = " " + std::to_string(oldest - 1) + ":";
    CHECK(contains(lines.back(), kept.c_str()) && contains(lines.back(), (" " + std::to_string(last_present) + ":2").c_str()));
    CHECK(!contains(lines.back(), evicted.c_str()));

    debug_recording_start();
    // Only the controller's deadline moves, so its public expiry path runs without sleeping.
    debug_recorder().deadline = Clock::now() - std::chrono::seconds(1);
    CHECK(!debug_state().recording && contains(lines.back(), "time limit"));
    debug_settings_set(0, 0);
    lines.clear();
    debug_recording_start();
    CHECK(!debug_state().recording && lines.size() == 1 && contains(lines.back(), "not started: no report is selected"));
    debug_mark_flash();
    CHECK(lines.size() == 2);   // a disabled history is cleared, not shown as current evidence
    debug_recording_stop();
    CHECK(lines.size() == 3 && contains(lines.back(), "not stopped: none is running"));

    debug_settings_set(1, kDebugExposureEachReading);
    debug_recording_start();
    lines.clear();
    std::vector<std::thread> workers;
    for (int worker = 0; worker < kWorkers; ++worker) workers.emplace_back([worker] {
        for (int report = 0; report < kReportsPerWorker; ++report) {
            debug_samples_reset((uint64_t)worker);
            debug_samples_report(last_present + report, (uint64_t)worker, 0x1000, (uint64_t)report, true);
            debug_exposure_note(last_present + report, bits((float)report));
            (void)debug_state();
        }
    });
    for (auto& worker : workers) worker.join();
    const uint32_t logged = kWorkers * kReportsPerWorker;
    CHECK(count("vk: samples present") == logged && debug_state().remaining == kDebugSampleReportLimit - logged);
    debug_recording_stop();
    std::puts("PASS: live diagnostic settings, rearming, bounds, history, markers, expiry and concurrent readers");
}

int main(int argc, char** argv) {
    const std::string mode = argc > 1 ? argv[1] : "live";
    if (mode == "environment") environment_mode();
    else if (mode == "invalid") invalid_environment_mode();
    else live_mode();
}

// Live diagnostic controls: bounded recordings of occlusion counter reports and of the final pass's exposure.
// A saved preference never starts a recording; only an explicit command or environment variable does.
#pragma once

#include <cstdint>

namespace mkwvk {

constexpr uint32_t kDebugSampleReportLimit = 4096;    // sample reports logged by one recording
constexpr uint32_t kDebugExposureReadingLimit = 600;  // exposure readings logged by one recording
constexpr int kDebugRecordingSeconds = 30;            // longest a recording runs
constexpr uint32_t kDebugExposureHistory = 32;        // exposure readings kept for a flash marker's dump
constexpr int kDebugExposureEachReading = 2;          // exposure setting: readings logged during a recording

struct DebugState {
    int samples = 0;     // 0 off, 1 sample reports traced
    int exposure = 0;    // 0 off, 1 recent readings kept in memory only, kDebugExposureEachReading
    bool recording = false;
    uint32_t remaining = 0;   // sample reports the recording may still log
    uint64_t recording_id = 0;
    uint64_t flash_markers = 0;
};

/// Applies the saved choices once, then the explicit environment overrides (RX_VK_LOG_SAMPLES, RX_VK_EXPOSURE_LOG);
/// RX_VK_LOG_SAMPLES arms a recording from the presentation it names.
void debug_settings_init(int samples, int exposure);
/// Changes the selections; a running recording stops, and the next explicitly started one uses them.
void debug_settings_set(int samples, int exposure);
/// Starts a recording at the current presentation, bounded by the kDebug*Limit and kDebugRecordingSeconds constants.
void debug_recording_start();
void debug_recording_stop();
/// Logs a flash marker with the exposure history.
void debug_mark_flash();
DebugState debug_state();

/// Called once per presentation with its number.
void debug_present(int64_t present);
/// A samples-passed counter reset on a queue.
void debug_samples_reset(uint64_t queue);
/// A samples-passed counter report; `written` is whether the report's counter word was written.
void debug_samples_report(int64_t present, uint64_t queue, uint64_t address, uint64_t value, bool written);
bool debug_exposure_enabled();
/// The final pass's exposure word of a presentation.
void debug_exposure_note(int64_t present, uint32_t word);
/// Logs the exposure history under `why`.
void debug_exposure_dump(const char* why);

} // namespace mkwvk

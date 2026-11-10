/* The pictures a game that was told its display is HDR10 draws as PQ (ST 2084, Rec. 2020, RGB10A2): the game keeps drawing PQ
   until it asks its display again, whatever the swapchain has become since, so a picture is PQ by what the game was last told
   and by its format. Whether it is converted for an SDR window is decided where the picture is presented, with the swapchain
   as it is then. Plain code, no Vulkan: tests/test_queued_pq.cpp checks it. */
#pragma once

#include <atomic>

namespace mkwvk::queued_pq {

struct Answer {
    std::atomic<bool> hdr10{false};   // (the last answer to the game's question: its display is HDR10)

    /// The game asks its display status: whether it is HDR10, the answer, remembered as what the game draws for next
    bool give(bool display_is_hdr10) {
        hdr10.store(display_is_hdr10, std::memory_order_relaxed);
        return display_is_hdr10;
    }
    /// Whether a picture of the game is PQ: the game was last told HDR10 and draws RGB10A2
    bool picture_is_pq(bool picture_is_rgb10a2) const {
        return picture_is_rgb10a2 && hdr10.load(std::memory_order_relaxed);
    }
};

}   // namespace mkwvk::queued_pq

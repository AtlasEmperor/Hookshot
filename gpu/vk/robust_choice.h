/* Bounds-checked buffer access as the Insert menu's Robust buffers row asks for it (vk_main.cpp's create_device).
   RX_VK_ROBUST, when set, wins over the row. */
#pragma once

#include <cstdlib>

namespace mkwvk::robust_choice {

/// Asked for: Auto (0) and On (2) on, Off (1) off. env: RX_VK_ROBUST, null when unset; 0 off, any other number on.
inline bool requested(int menu, const char* env) { return env ? std::atoi(env) != 0 : menu != 1; }

/// What the device gets: robustBufferAccess with robustBufferAccess2, only where VK_EXT_robustness2 offers both.
/// Without the extension the device gets neither, whatever the row asks for.
inline bool effective(bool asked, bool buffer_access2, bool buffer_access) { return asked && buffer_access2 && buffer_access; }

} // namespace mkwvk::robust_choice

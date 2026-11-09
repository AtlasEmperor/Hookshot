/* What a change of the Insert menu's GPU device or Robust buffers row needs (vk_device_rebuild.cpp): the device made again on
   another GPU, made again on the same GPU with the other robustness, or nothing. Compared on the effective choice, never on
   the rows: Auto and On are both on, RX_VK_DEVICE and RX_VK_ROBUST win over the rows, and robustness without
   VK_EXT_robustness2 is off whatever the row says (robust_choice.h). */
#pragma once

namespace mkwvk::device_change {

enum class Change { None, Gpu, Robustness };

/// gpu_in_use, robust_in_use: the device's; gpu_wanted, robust_wanted: what the rows and the environment give now (gpu_wanted
/// null: no GPU with Vulkan 1.3 is listed, and the device in use stays)
inline Change needed(const void* gpu_in_use, bool robust_in_use, const void* gpu_wanted, bool robust_wanted) {
    if (!gpu_wanted) return Change::None;
    if (gpu_wanted != gpu_in_use) return Change::Gpu;
    return robust_wanted != robust_in_use ? Change::Robustness : Change::None;
}

} // namespace mkwvk::device_change

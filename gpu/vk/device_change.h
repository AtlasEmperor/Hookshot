/* What a change of the Insert menu's GPU device, Robust buffers or Mesh shaders row needs (vk_device_rebuild.cpp): the device
   made again on another GPU, made again on the same GPU with the other robustness or the other mesh shaders, or nothing.
   The GPU and the robustness are compared on the effective choice, never on the rows: Auto and On are both on, RX_VK_DEVICE
   and RX_VK_ROBUST win over the rows, and robustness without VK_EXT_robustness2 is off whatever the row says
   (robust_choice.h). The mesh shaders are compared as asked (mesh_choice.h, RX_VK_FORCE_MESH_FALLBACK over the row): a change
   between Automatic and Native makes the device again on any GPU, though the two differ only on the GPUs whose task + mesh
   draws take the compute path by default. */
#pragma once

namespace mkwvk::device_change {

enum class Change { None, Gpu, Robustness, MeshShaders };

/// gpu_in_use, robust_in_use, mesh_in_use: the device's; gpu_wanted, robust_wanted, mesh_wanted: what the rows and the
/// environment give now (gpu_wanted null: no GPU with Vulkan 1.3 is listed, and the device in use stays)
inline Change needed(const void* gpu_in_use, bool robust_in_use, int mesh_in_use, const void* gpu_wanted, bool robust_wanted,
                     int mesh_wanted) {
    if (!gpu_wanted) return Change::None;
    if (gpu_wanted != gpu_in_use) return Change::Gpu;
    if (robust_wanted != robust_in_use) return Change::Robustness;
    return mesh_wanted != mesh_in_use ? Change::MeshShaders : Change::None;
}

} // namespace mkwvk::device_change

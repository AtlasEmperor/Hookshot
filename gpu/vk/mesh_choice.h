/* Task and mesh programs as the Insert menu's Mesh shaders row asks for them (vk_main.cpp's make_device, #1001).
   RX_VK_FORCE_MESH_FALLBACK, a test, is Compute over the row when set to a number other than 0. */
#pragma once

#include <cstdlib>

namespace mkwvk::mesh_choice {

/// The row's choices: the GPU's own mesh shaders where it has them and the compute path where not (and for the task + mesh
/// draws of the GPUs that time out on them); the GPU's own for every draw; the compute path on every GPU
enum Mode { kAutomatic = 0, kNative = 1, kCompute = 2 };

/// Asked for: the row, Compute when force_fallback (RX_VK_FORCE_MESH_FALLBACK, null when unset) is a number other than 0; a
/// value out of the row's range is Automatic
inline int requested(int menu, const char* force_fallback) {
    if (force_fallback && std::atoi(force_fallback) != 0) return kCompute;
    return menu >= kAutomatic && menu <= kCompute ? menu : kAutomatic;
}

} // namespace mkwvk::mesh_choice

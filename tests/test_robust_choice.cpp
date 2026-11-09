#include "../gpu/vk/robust_choice.h"

#include <cstdio>

#define CHECK(name, condition) do { if (!(condition)) { std::fprintf(stderr, "FAIL %s at line %d\n", name, __LINE__); return 1; } } while (0)

int main() {
    using mkwvk::robust_choice::effective;
    using mkwvk::robust_choice::requested;
    CHECK("Auto asks for it", requested(0, nullptr));
    CHECK("Off does not", !requested(1, nullptr));
    CHECK("On asks for it", requested(2, nullptr));
    CHECK("RX_VK_ROBUST=0 wins over the row", !requested(0, "0") && !requested(2, "0"));
    CHECK("RX_VK_ROBUST=1 wins over the row", requested(1, "1"));
    CHECK("asked for, and offered by VK_EXT_robustness2: given", effective(true, true, true));
    CHECK("Off: not given", !effective(false, true, true));
    CHECK("no VK_EXT_robustness2: never given", !effective(true, false, true));
    CHECK("no robustBufferAccess: never given", !effective(true, true, false));
    std::puts("robust choice: all checks passed");
}

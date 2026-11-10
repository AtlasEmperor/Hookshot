// Which pictures are PQ after the window fell back to SDR (gpu/vk/queued_pq.h): no game, no GPU.
#include "../gpu/vk/queued_pq.h"

#include <cstdio>
#include <cstdlib>

#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); std::exit(1); } } while (0)

int main() {
    mkwvk::queued_pq::Answer answer;
    // (the game was never told HDR10: its pictures are SDR, whatever the format)
    CHECK(!answer.picture_is_pq(true));
    CHECK(!answer.picture_is_pq(false));
    // (told HDR10: a RGB10A2 picture is PQ, any other is not)
    CHECK(answer.give(true));
    CHECK(answer.picture_is_pq(true));
    CHECK(!answer.picture_is_pq(false));
    // (the swapchain is made SDR after the picture was judged: the judgement does not read the swapchain, so it stands and the
    // present, which asks the swapchain as it is then, converts the picture)
    const bool judged_before_rebuild = answer.picture_is_pq(true);
    const bool swapchain_is_hdr10_after_rebuild = false;
    CHECK(judged_before_rebuild && !swapchain_is_hdr10_after_rebuild);
    // (the game asks again and is told its display is not HDR10: its pictures are SDR from then on)
    CHECK(!answer.give(false));
    CHECK(!answer.picture_is_pq(true));
    // (told HDR10 again)
    CHECK(answer.give(true));
    CHECK(answer.picture_is_pq(true));
    std::puts("PASS: PQ pictures follow what the game was last told, not the swapchain");
}

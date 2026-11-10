"""Compile and run the rule that tells a PQ picture on an SDR window (gpu/vk/queued_pq.h; no game or GPU required), and check that
the replay asks it of every picture, converts the PQ ones back to SDR in the present, and keeps what the game was last told."""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def statement(source, start):
    """The statement beginning at start, up to its semicolon"""
    return source[start:source.index(";", start)]


def check_source():
    replay = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    framegen = (ROOT / "gpu/vk/vk_framegen.cpp").read_text(encoding="utf-8")
    nn_vi = (ROOT / "host/nn_vi.c").read_text(encoding="utf-8")
    for needle in ('#include "queued_pq.h"',
                   "hdr10_answer.picture_is_pq(rgb10a2)",
                   "present_game_pq.store(game_pq",
                   "!dev.hdr && src && view && present_game_pq.load(",
                   "framegen_pq_sdr(f.cmd, view, sw, sh, crop, rect.w, rect.h)"):
        if needle not in replay:
            raise SystemExit("vk_replay.cpp no longer has: " + needle)
    # (the judgement of the picture is made before present_image can make the swapchain again: it must not read the swapchain)
    judged = statement(replay, replay.index("const bool game_pq ="))
    if "dev.hdr" in judged or "dev.hdr" in statement(replay, replay.index("present_game_pq.store(")):
        raise SystemExit("do_present judges the PQ picture by the swapchain, which present_image may make again afterwards")
    # (the answer is remembered from the display status question alone; the paper white question gives it without recording)
    if len(re.findall(r"hdr10_answer\.give\(", replay)) != 1 or "id == HOS_OPT_HDR_STATUS) return hdr10_answer.give(" not in replay:
        raise SystemExit("vk_replay.cpp remembers the HDR10 answer other than for HOS_OPT_HDR_STATUS")
    if "id == HOS_OPT_HDR_NATIVE) return dev.hdr && opts.hdr == 2;" not in replay:
        raise SystemExit("vk_replay.cpp no longer answers HOS_OPT_HDR_NATIVE without recording it")
    status = nn_vi[nn_vi.index("QueryDisplayHdrStatus"):nn_vi.index("QueryDisplayHdrPaperWhite")]
    white = nn_vi[nn_vi.index("QueryDisplayHdrPaperWhite"):nn_vi.index("QueryDisplayVrrSupported")]
    if "rx_option(HOS_OPT_HDR_STATUS, 0)" not in status or "HOS_OPT_HDR_STATUS" in white:
        raise SystemExit("nn_vi.c: only QueryDisplayHdrStatus asks HOS_OPT_HDR_STATUS")
    if "PQ_TO_SDR_COMP_SPV" not in framegen or "VkImage framegen_pq_sdr(" not in framegen:
        raise SystemExit("vk_framegen.cpp no longer makes the PQ to SDR picture")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="queued-pq-") as tmp:
        exe = Path(tmp) / "queued-pq"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror",
                        str(ROOT / "tests/test_queued_pq.cpp"), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()

"""The Insert menu's Robust buffers row (gpu/vk/robust_choice.h and its use in vk_main.cpp's make_device), no game or
GPU required.

python -I -B tests/test_robust_choice.py [--cxx g++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    main_src = (ROOT / "gpu" / "vk" / "vk_main.cpp").read_text(encoding="utf-8")
    create = main_src[main_src.index("bool make_device("):]
    create = create[:create.index("\n}\n")]
    if "robust_buffers=" in main_src:
        raise SystemExit("vk_main.cpp reads hookshot_options.ini itself: the menu's options are its one reader")
    for need, why in (('robust_choice::requested(opts.robust, getenv("RX_VK_ROBUST"))', "the row, RX_VK_ROBUST over it"),
                      ("robust_choice::effective(", "the device gets what VK_EXT_robustness2 offers"),
                      ("f.features.robustBufferAccess = robust_ok", "robustBufferAccess follows the effective choice")):
        if need not in create:
            raise SystemExit("make_device: %s is missing (%s)" % (need, why))
    # (VUID-VkDeviceCreateInfo-robustBufferAccess-10247: robustBufferAccess with update-after-bind buffer descriptors needs
    # robustBufferAccessUpdateAfterBind; none are used, so none are enabled)
    created = create.index("vkCreateDevice(")
    for bit in ("UniformBuffer", "StorageBuffer", "UniformTexelBuffer", "StorageTexelBuffer"):
        cleared = create.find("f12.descriptorBinding%sUpdateAfterBind = " % bit)
        if cleared < 0 or cleared > created:
            raise SystemExit("make_device enables descriptorBinding%sUpdateAfterBind" % bit)
    with tempfile.TemporaryDirectory(prefix="robust-choice-") as tmp:
        exe = Path(tmp) / "robust-choice"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror",
                        str(ROOT / "tests" / "test_robust_choice.cpp"), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()

"""The PQ to SDR pass (gpu/vk/shaders/pq_to_sdr.comp): pq_to_sdr_comp_spv.h names the sha256 of the shader it was compiled from, and
with glslangValidator (--glslang) the header's code is the shader compiled now. And the decoding it does, checked in Python with the
constants and the matrix read from the two shaders: hdr_encode.comp's pictures come back as they were, paper white lands on white,
black stays black, and what is brighter than white keeps its hue.

    python -I -B tests/test_pq_to_sdr.py [--glslang glslangValidator]
"""
import argparse, hashlib, re, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHADERS = ROOT / "gpu" / "vk" / "shaders"


def constants(source):
    """The PQ constants m1, m2, c1, c2, c3 of a shader's pq function or its decoding"""
    found = re.search(r"const float m1 = ([\d.]+), m2 = ([\d.]+), c1 = ([\d.]+), c2 = ([\d.]+), c3 = ([\d.]+);", source)
    assert found, "the PQ constants"
    return [float(v) for v in found.groups()]


def matrix(source, name):
    """A mat3 constant as rows: GLSL lists its columns"""
    found = re.search(r"mat3 %s = mat3\(([^)]*)\);" % name, source)
    assert found, name
    values = [float(v) for v in found.group(1).split(",")]
    assert len(values) == 9
    return [[values[column * 3 + row] for column in range(3)] for row in range(3)]


def apply(rows, vector):
    return [sum(rows[row][column] * vector[column] for column in range(3)) for row in range(3)]


encode = (SHADERS / "hdr_encode.comp").read_text()
decode = (SHADERS / "pq_to_sdr.comp").read_text()
assert constants(encode) == constants(decode), "the two shaders' PQ constants differ"
m1, m2, c1, c2, c3 = constants(decode)
to2020, to709 = matrix(encode, "to2020"), matrix(decode, "to709")


def pq(nits):
    level = min(max(nits / 10000.0, 0.0), 1.0) ** m1
    return ((c1 + c2 * level) / (1 + c3 * level)) ** m2


def pq_to_nits(code):
    power = min(max(code, 0.0), 1.0) ** (1 / m2)
    return 10000.0 * (max(power - c1, 0.0) / (c2 - c3 * power)) ** (1 / m1)


def srgb(linear):
    return linear * 12.92 if linear <= 0.0031308 else 1.055 * linear ** (1 / 2.4) - 0.055


def decoded(code, white):
    """pq_to_sdr.comp's main for one texel: the PQ code of a Rec. 2020 colour to the sRGB code shown"""
    linear = [max(v / white, 0.0) for v in apply(to709, [pq_to_nits(c) for c in code])]
    scale = max(1.0, max(linear))
    return [srgb(v / scale) for v in linear]


a = argparse.ArgumentParser()
a.add_argument("--glslang")
args = a.parse_args()
header = (SHADERS / "pq_to_sdr_comp_spv.h").read_text()
if hashlib.sha256((SHADERS / "pq_to_sdr.comp").read_bytes()).hexdigest() not in header.splitlines()[0]:
    sys.exit("FAIL: pq_to_sdr_comp_spv.h was not made from pq_to_sdr.comp as it is (recompile it)")
for nits in (0.5, 10, 100, 203, 1000, 10000):
    assert abs(pq_to_nits(pq(nits)) / nits - 1) < 1e-6, "the decoding is not the encoding's inverse at %s nits" % nits
product = [apply(to709, apply(to2020, [float(i == j) for i in range(3)])) for j in range(3)]
assert all(abs(product[j][i] - float(i == j)) < 2e-3 for i in range(3) for j in range(3)), "to709 is not the inverse of to2020"
white = 200.0
# (paper white, in any hue of the picture's: what hdr_encode.comp made of an sRGB code comes back as that code)
for code in ((1.0, 1.0, 1.0), (0.5, 0.5, 0.5), (0.25, 0.5, 0.1), (0.1, 0.1, 0.4), (0.0, 0.0, 0.0)):
    linear = [((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92 for v in code]
    nits = [v * white for v in apply(to2020, linear)]
    back = decoded([pq(n) for n in nits], white)
    assert all(abs(b - c) < 2e-3 for b, c in zip(back, code)), "%s came back as %s" % (code, back)
# (a highlight past paper white: no channel past white, the hue kept)
back = decoded([pq(n) for n in apply(to2020, [4 * white, 3 * white, 2 * white])], white)
assert max(back) <= 1.0 + 1e-6 and abs(back[0] - 1.0) < 1e-6, back
assert abs(back[1] / back[0] - srgb(0.75) / 1.0) < 1e-3 and back[2] < back[1], back
if args.glslang:
    with tempfile.TemporaryDirectory() as d:
        out = Path(d, "h.h")
        subprocess.run([args.glslang, "-V", "--target-env", "vulkan1.2", "--vn", "PQ_TO_SDR_COMP_SPV", "-o", str(out),
                        str(SHADERS / "pq_to_sdr.comp")], check=True, capture_output=True)
        if out.read_text() != "".join(header.splitlines(True)[1:]):
            sys.exit("FAIL: pq_to_sdr_comp_spv.h differs from the shader compiled now")
print("PASS: the PQ to SDR pass's header is its shader, and it decodes what hdr_encode.comp encodes")

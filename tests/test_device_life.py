"""Every device-bound object of the Vulkan back end is covered by the device rebuild (gpu/vk/vk_device_life.h), no GPU required.

A rebuild on another GPU, or with the other robustness, destroys the VkDevice: an object, a handle cached on a thread or a
fact latched from the device that the rebuild does not reach is used on a device that no longer exists (a crash, or
VUID-vkDestroyDevice-device-05137 at the teardown under RX_VK_VALIDATION=1). This test lists, in every gpu/vk/*.cpp, the
thread_locals, the std::call_once flags, the function-local statics and the namespace-scope variables that hold a Vulkan or
VMA handle, a pointer into a module's device tables or a fact read from the device, and fails on any of them that is
neither
  - a DeviceLatch or a DeviceLocal (worked out again, or emptied, on each device),
  - named in a step its file registers with DeviceLife (release, rebuild or thread),
  - nor in EXEMPT below, with the reason it is not device-bound.
It also checks that the sites the decision's judges named are found and covered, and the order of the teardown, and runs the
mechanism itself (tests/device_life_test.cpp: the steps' order, latches and thread caches per device, the gate, the decision).

python -I -B tests/test_device_life.py [--cxx g++] [--vulkan-include <dir>] [--root <checkout>]
"""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}", "--vulkan-include", "{vulkan_headers}"]

ROOT = Path(__file__).resolve().parents[1]
# (the mechanism itself)
SKIP_FILES = {"vk_device_life.cpp", "vk_device_rebuild.cpp"}
HANDLE = (r"\b(?:Vk(?:Buffer|Image|ImageView|BufferView|Sampler|Pipeline|PipelineLayout|PipelineCache|DescriptorSet|"
          r"DescriptorSetLayout|DescriptorPool|CommandBuffer|CommandPool|Fence|Semaphore|Event|QueryPool|ShaderModule|"
          r"DeviceMemory|Queue|Device|SwapchainKHR|SurfaceKHR|FormatProperties|PhysicalDevice\w*)|Vma\w+)\b")
DEVICE = re.compile(HANDLE + r"|\bdev\.\w+|\bvk[A-Z]\w*\(|\bPipeEntry\b|\bProgram\b|\bTexture\b|\bmemory_guest_pages\b")
HANDLE_RE = re.compile(HANDLE)
WRAPPED = re.compile(r"\bDevice(?:Latch|Local)\s*<")
NAME = re.compile(r"(\w+)\s*(?:\[[^\]]*\]\s*)*(?:=|;|\{|\(|,)")

# (file, name): why it is not device-bound
EXEMPT = {
    ("vk_bank.cpp", "seed_cs_control"): "set and cleared around one seed translation",
    ("vk_bank.cpp", "e"): "a stage's pointer table read from guest memory, by draw-state generation",
    ("vk_bank.cpp", "for_gen"): "the guest state generation of that pointer table",
    ("vk_bank.cpp", "for_state"): "the guest state that pointer table was read for",
    ("vk_bank.cpp", "for_stage"): "the stage that pointer table was read for",
    ("vk_draw.cpp", "list"): "the owner list of this file's TLS_OBJECTs (thread exit)",
    ("vk_draw.cpp", "fault_jmp"): "the Linux driver fault guard's jump buffer, armed around one driver call",
    ("vk_draw.cpp", "fault_armed"): "the Linux driver fault guard's flag, around one driver call",
    ("vk_draw.cpp", "once"): "the Linux driver fault guard's signal handlers, installed once a process",
    ("vk_draw.cpp", "driver_cache_only"): "set and cleared around one predict_run",
    ("vk_draw.cpp", "last_view_format"): "the last view format logged (RX_VK_LOG_IMG), a value",
    ("vk_draw.cpp", "dump_inputs"): "RX_VK_DUMP's text of what a draw samples",
    ("vk_draw.cpp", "dump_mesh_indirect"): "RX_VK_DUMP's program keys and guest addresses",
    ("vk_draw.cpp", "trace_seq"): "a counter of RX_VK_PASS_TRACE's records",
    ("vk_draw.cpp", "tmp"): "scratch bytes of one c1 upload",
    ("vk_draw.cpp", "changed"): "scratch writes of one descriptor push",
    ("vk_draw.cpp", "words"): "scratch words of one descriptor push",
    ("vk_draw.cpp", "hits_value"): "the submission value the resolved targets were last touched at",
    ("vk_draw.cpp", "b"): "scratch bytes of one probe readback",
    ("vk_draw.cpp", "sb"): "scratch bytes of one probe readback",
    ("vk_draw.cpp", "copies"): "scratch copy regions of one vertex upload",
    ("vk_draw.cpp", "last"): "the guest render targets the dry pass last marked, guest state",
    ("vk_draw.cpp", "seen"): "a sampler id's parameters by slot version, guest data",
    ("vk_draw.cpp", "desc_fp"): "scratch slot versions of one descriptor build, guest data",
    ("vk_draw.cpp", "desc_fp_dummy"): "scratch flag of one descriptor build",
    ("vk_draw.cpp", "desc_samp_seen"): "the samplers' registration generation one descriptor build began at",
    ("vk_draw.cpp", "desc_destroy_seen"): "the eviction generation one descriptor build began at",
    ("vk_memory.cpp", "import_cooling"): "set by one import attempt for its caller",
    ("vk_memory.cpp", "import_result"): "set by one import attempt for its caller",
    ("vk_memory.cpp", "list"): "the host's pool list read by memory_sync, guest data",
    ("vk_memory.cpp", "mirrored"): "scratch guest ranges of one capture",
    ("vk_memory.cpp", "ver"): "the capture range version that scratch list was built at",
    ("vk_memory.cpp", "ok"): "scratch page flags of one capture copy",
    ("vk_memory.cpp", "merged"): "scratch guest ranges of one capture",
    ("vk_memory.cpp", "chunks"): "scratch chunks of one write-back diff",
    ("vk_memory.cpp", "chunk_src"): "scratch sources of one write-back diff",
    ("vk_memory.cpp", "fills"): "scratch copy regions of one write-back diff",
    ("vk_memory.cpp", "odd"): "scratch copy regions of one write-back diff",
    ("vk_memory.cpp", "pairs"): "scratch copies of one capture",
    ("vk_memory.cpp", "game"): "scratch page lists of one shadow update, guest data",
    ("vk_memory.cpp", "collected"): "scratch page lists of one shadow update, guest data",
    ("vk_memory.cpp", "replay"): "scratch page lists of one shadow update, guest data",
    ("vk_menu.cpp", "once"): "the upscalers' background questions, started once a process, each a device use",
    ("vk_ngx_msvc_rt.cpp", "_Init_thread_epoch"): "Microsoft's thread-safe statics' epoch, read by compiled code",
    ("vk_replay.cpp", "suspend_ok"): "set and cleared around one serial replay",
    ("vk_replay.cpp", "suspend_at"): "the guest command it stopped at, guest data",
    ("vk_replay.cpp", "ub_gen"): "the uniform-update overlay's generation, guest data",
    ("vk_replay.cpp", "rmode"): "the replay mode of the thread, set per segment",
    ("vk_replay.cpp", "ub_limit"): "a worker's place in the uniform updates, guest data",
    ("vk_replay.cpp", "cond_at"): "a worker's place in the render conditions, guest data",
    ("vk_replay.cpp", "ub_gap_cache"): "uniform-update gaps, guest data",
    ("vk_replay.cpp", "dst"): "scratch uniform-update ranges",
    ("vk_replay.cpp", "end"): "scratch uniform-update ranges",
    ("vk_replay.cpp", "ub_words"): "uniform-update words, guest data",
    ("vk_replay.cpp", "ub_copies"): "uniform-update copies, guest data",
    ("vk_replay.cpp", "watch"): "sync_watch's thread, started once a process",
    ("vk_replay.cpp", "replay_pin_depth"): "the replay thread's CPU affinity nesting around one replay",
    ("vk_replay.cpp", "replay_pin_prev"): "the CPU affinity to put back after one replay",
    ("vk_replay.cpp", "once"): "the lost device's report, once a process: the process ends after it",
    ("vk_replay.cpp", "present_defer_into"): "set and cleared around one present_image call, null between",
    ("vk_shader.cpp", "forced"): "set and cleared around one translation",
    ("vk_shader.cpp", "seed_capture"): "set and cleared around one translation",
    ("vk_shader.cpp", "questions_out"): "set and cleared around one translation",
    ("vk_shader.cpp", "questions_in"): "set and cleared around one translation",
    ("vk_shader.cpp", "questions_at"): "set and cleared around one translation",
    ("vk_shader.cpp", "answers_in"): "set and cleared around one translation",
    ("vk_shader.cpp", "known"): "texture answers by slot version, guest data",
    ("vk_shader.cpp", "fresh"): "scratch storage of one Shader::Info",
    ("vk_shader.cpp", "now"): "scratch handles of one pick",
    ("vk_texture.cpp", "tl_watch_prog"): "RX_VK_WATCH's program key, a value",
    ("vk_texture.cpp", "in_run"): "scratch guest ranges",
    ("vk_texture.cpp", "cpu"): "scratch guest ranges",
    ("vk_texture.cpp", "inner"): "scratch guest ranges",
    ("vk_texture.cpp", "last"): "the memory generation those scratch ranges were built at",
    ("vk_texture.cpp", "dirty"): "scratch guest ranges",
    ("vk_texture.cpp", "first"): "scratch guest ranges",
    ("vk_texture.cpp", "d"): "scratch guest ranges",
    ("vk_texture.cpp", "astc_fail"): "why this thread's last GPU ASTC upload failed, a static message",
    ("vk_texture.cpp", "up_route"): "the route of the upload in progress, a value",
    ("vk_texture.cpp", "upload_defer_ok"): "set and cleared around one draw's uploads",
    ("vk_texture.cpp", "moves"): "scratch moves of one compaction pass, emptied when the pass begins",
    ("vk_texture.cpp", "regions"): "scratch copy regions of one moved texture, emptied at each use",
}

# The sites the judges of the GPU switch decision (and its D2 addendum) named, as they are named now: each must be found by
# this test and covered. (file, name)
JUDGED = [
    ("vk_draw.cpp", "mine"), ("vk_draw.cpp", "table"), ("vk_draw.cpp", "rec_cmd"), ("vk_draw.cpp", "grid_patch_buf"),
    ("vk_draw.cpp", "last_pipeline"), ("vk_draw.cpp", "mesh_conv_buf"), ("vk_draw.cpp", "on"), ("vk_draw.cpp", "amd_latch"),
    ("vk_draw.cpp", "eq_bias_latch"), ("vk_draw.cpp", "serial_latch"), ("vk_draw.cpp", "movie_helper"),
    ("vk_draw.cpp", "typed_helper"), ("vk_draw.cpp", "pcache"), ("vk_draw.cpp", "samplers"), ("vk_draw.cpp", "gpl_libs"),
    ("vk_draw.cpp", "clear_pipes"), ("vk_draw.cpp", "pages_latch"),
    ("vk_texture.cpp", "up_cmd"), ("vk_texture.cpp", "last_barrier_cmd"), ("vk_texture.cpp", "fmt_cache"),
    ("vk_texture.cpp", "astc_pipe"), ("vk_texture.cpp", "bc_pipe"), ("vk_texture.cpp", "unsw_pipe"),
    ("vk_texture.cpp", "sparse_fence"), ("vk_texture.cpp", "texel_views"),
    ("vk_memory.cpp", "tl_pools"), ("vk_memory.cpp", "bind_memo"), ("vk_memory.cpp", "dmabuf_fence"),
    ("vk_memory.cpp", "budget"), ("vk_memory.cpp", "keep_latch"), ("vk_memory.cpp", "guest_pages_buffer"),
    ("vk_shader.cpp", "p"), ("vk_shader.cpp", "picks"), ("vk_shader.cpp", "prog_fast"),
    ("vk_vma.cpp", "image_pool"), ("vk_vma.cpp", "vma"), ("vk_framegen.cpp", "hdr"), ("vk_framegen.cpp", "pq_sdr"),
]
# (and those a type cannot tell: a fact of the device kept as a plain number or flag, each named in its file's release)
JUDGED_PLAIN = [
    ("vk_texture.cpp", "astc_state"), ("vk_texture.cpp", "bc_state"), ("vk_texture.cpp", "unsw_state"),
    ("vk_texture.cpp", "vram_budget"), ("vk_memory.cpp", "host_pointer_type"), ("vk_memory.cpp", "dmabuf_type"),
    ("vk_memory.cpp", "guest_pages_tried"), ("vk_vma.cpp", "image_pool_tried"), ("vk_vma.cpp", "texture_pool_tried"),
]


def strip(text):
    """the source without comments and string literals, line breaks kept"""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("\n" * text.count("\n", i, j))
            i = j
        elif c == '"' or c == "'":
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == "\\" else 1
            out.append(c + c)
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def block_at(text, at):
    """text[at:] up to the end of the first {...} block after at"""
    start = text.index("{", at)
    depth = 0
    for i in range(start, len(text)):
        depth += (text[i] == "{") - (text[i] == "}")
        if depth == 0:
            return text[at:i + 1]
    raise SystemExit("no end for the block at %d" % at)


def device_structs(text):
    """the struct names of this file whose members hold a device handle, directly or through another such struct"""
    bodies = {}
    for m in re.finditer(r"(?m)^\s*struct (\w+)\s*(?::[^{]*)?\{", text):
        bodies[m.group(1)] = block_at(text, m.start())
    bound = {name for name, body in bodies.items() if HANDLE_RE.search(body) or re.search(r"\bPipeEntry\b", body)}
    while True:
        more = {name for name, body in bodies.items() if name not in bound and any(re.search(r"\b%s\b" % b, body) for b in bound)}
        if not more:
            return bound
        bound |= more


def statement(lines, i):
    """the statement starting at line i, up to its ';' or its first '{' (an initializer lambda's body is not needed)"""
    s, j = lines[i], i
    while ";" not in s and j + 1 < len(lines) and j - i < 8:
        j += 1
        s += " " + lines[j].strip()
    return s.split(";")[0]


def initializer_lambda(lines, i):
    """the body of the lambda a declaration at line i runs for its value ('static const bool on = [] { ... }();'), else ''"""
    if not re.search(r"=\s*\[[^\]]*\]\s*(?:\([^)]*\))?\s*(?:->\s*[\w:<>]+\s*)?\{\s*$", lines[i]):
        return ""
    depth, j = 0, i
    while j < len(lines):
        depth += lines[j].count("{") - lines[j].count("}")
        if depth <= 0:
            break
        j += 1
    return "\n".join(lines[i:j + 1])


def declared_names(decl):
    """the names a declaration declares (several for 'int a = 0, b = 0')"""
    head = re.sub(r"\[[^\]]*\]", "", decl)
    head = re.sub(r"<[^<>]*(<[^<>]*>[^<>]*)*>", "", head)   # (template arguments)
    head = re.sub(r"=\s*[^,]*", "", head)
    head = re.sub(r"\{[^}]*\}", "", head)
    head = re.sub(r"\([^()]*\)\s*$", "", head.strip())   # (a constructor's arguments: list(8192))
    names = re.findall(r"(\w+)\s*(?:,|$)", head.strip())
    return [n for n in names if n not in {"const", "static", "thread_local", "volatile", "inline", "constexpr", "struct"}]


def found(path):
    """[(line, name, kind, wrapped)] of the device-bound declarations of a file"""
    text = strip(path.read_text(encoding="utf-8"))
    lines = text.split("\n")
    structs = device_structs(text)
    struct_type = re.compile(r"\b(?:%s)\b" % "|".join(sorted(structs))) if structs else None
    out = []
    depth = 0
    for i, line in enumerate(lines):
        code = re.sub(r"^alignas\s*\([^)]*\)\s*", "", line.strip())
        at_file_scope = depth == 0 or (depth <= 2 and not line.startswith((" ", "\t")))
        if code.startswith("#") or (i and lines[i - 1].rstrip().endswith("\\")):   # (a directive, or a macro's line)
            pass
        elif code.startswith("TLS_OBJECT(") and not line.startswith("#"):
            out.append((i + 1, re.match(r"TLS_OBJECT\((\w+)", code).group(1), "tls", False))
        elif re.match(r"(static\s+)?thread_local\b", code) and not code.startswith("extern"):
            for name in declared_names(statement(lines, i).replace("thread_local", "").replace("static", "")):
                out.append((i + 1, name, "tls", bool(WRAPPED.search(code))))
        elif re.search(r"\bstd::once_flag\s+(\w+)", code):
            out.append((i + 1, re.search(r"\bstd::once_flag\s+(\w+)", code).group(1), "once", False))
        elif re.match(r"static\s", code) and line.startswith((" ", "\t")) and not code.startswith("static_assert"):
            st = statement(lines, i)
            if re.match(r"static\s+[\w:<>,\s*&]+\s+\w+\s*\(.*\)\s*(const\s*)?$", st.strip()):   # (a function's declaration)
                pass
            elif (DEVICE.search(st) or DEVICE.search(initializer_lambda(lines, i)) or WRAPPED.search(st) or
                  (struct_type and struct_type.search(st.split("=")[0]))):
                for name in declared_names(st.split("=")[0].replace("static", "")) or []:
                    out.append((i + 1, name, "static", bool(WRAPPED.search(st))))
        elif at_file_scope and not line.startswith((" ", "\t")) and code and not code.startswith(
                ("return", "using", "typedef", "extern", "template", "namespace", "struct", "class", "enum", "#", "}", "//")):
            st = statement(lines, i)
            head = st.split("=")[0]
            is_function = re.search(r"\w\s*\([^)]*\)\s*(const\s*)?(\{|$)", head) and "{" not in head.split("(")[0]
            if not is_function and "(" not in head and (HANDLE_RE.search(head) or (struct_type and struct_type.search(head))):
                for name in declared_names(head):
                    out.append((i + 1, name, "file", bool(WRAPPED.search(st))))
        depth += line.count("{") - line.count("}")
    # (a struct with handles, defined and declared at once: 'struct { ... } name;', 'struct Pass { ... } a, b;')
    for m in re.finditer(r"(?m)^struct\s*(?:\w+\s*)?\{", text):
        body = block_at(text, m.start())
        tail = re.match(r"\s*(\w+(?:\s*\[[^\]]*\])?(?:\s*,\s*\w+(?:\s*\[[^\]]*\])?)*)\s*;", text[m.start() + len(body):])
        if tail and (HANDLE_RE.search(body) or (struct_type and struct_type.search(body))):
            for name in re.findall(r"(\w+)\s*(?:\[[^\]]*\])?\s*(?:,|$)", tail.group(1)):
                out.append((text.count("\n", 0, m.start()) + 1, name, "file", False))
    return out, text


KEYWORDS = {"if", "for", "while", "switch", "return", "sizeof", "catch", "decltype", "alignof", "static_cast", "const_cast",
            "reinterpret_cast", "defined"}


def bodies_of(text, fn):
    """the bodies of this file's definitions of function fn"""
    if fn in KEYWORDS:
        return []
    return [block_at(text, d.start()) for d in re.finditer(r"(?m)^\s*(?:\[\[\w+\]\]\s*)?[\w:<>&*]+\s+%s\s*\([^;{]*\)\s*\{" % fn, text)
            if not re.match(r"\s*else\b", text[d.start():])]


def covered_names(text):
    """every word in the bodies of the steps this file registers with DeviceLife: its release step's and the functions of this
    file that release calls (two levels: release_prep and collect from dlss_shutdown), with the statics of those it calls (an
    accessor's module state: al()'s a), its rebuild and thread steps' own"""
    words = set()
    for m in re.finditer(r"DeviceLife\s+\w+\s*\(([^;]*)\);", text):
        args = [a.strip() for a in m.group(1).split(",")]
        steps = [a if re.fullmatch(r"\w+", a) and a != "nullptr" else None for a in args[2:5]]
        release, rebuild, thread = (steps + [None, None, None])[:3]
        level, done = [release] if release else [], set()
        for _ in range(3):
            called = []
            for fn in level:
                if fn in done:
                    continue
                done.add(fn)
                for body in bodies_of(text, fn):
                    words |= body_words(body)
                    if fn != release:   # (the state an accessor the release calls hands it: static State s; return s;)
                        words |= set(re.findall(r"\bstatic\s+[\w:<>&*\s]+?\b(\w+)\s*(?:;|\{|=)", body))
                    called += [w for w in re.findall(r"\b(\w+)\s*\(", body) if w not in KEYWORDS]
            level = called
        for fn in (rebuild, thread):
            if fn:
                for body in bodies_of(text, fn):
                    words |= body_words(body)
    return words


def body_words(body):
    """the names a function body uses, but those it declares itself (its locals cover nothing of the file's)"""
    locals_ = set(re.findall(r"(?:\b(?:auto|const|[\w:]+(?:<[^;(){}]*>)?)[&*\s]+)(\w+)\s*(?:=[^=]|\{|:[^:]|;|\))", body))
    for group in re.findall(r"auto\s*&?\s*\[([^\]]*)\]", body):
        locals_ |= {w.strip() for w in group.split(",")}
    return set(re.findall(r"(?<![\w.])(?<!->)(?<!::)(\w+)", body)) - locals_   # (a member's name, x.d or p->d, is not d)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--cxx", default="g++")
    parser.add_argument("--vulkan-include", type=Path)
    args = parser.parse_args()
    vk = args.root / "gpu" / "vk"
    bad, seen, exempt_used, n = [], {}, set(), 0
    covered_by_file = {}
    for path in sorted(vk.glob("vk_*.cpp")):
        if path.name in SKIP_FILES:
            continue
        decls, text = found(path)
        covered = covered_names(text)
        covered_by_file[path.name] = covered
        for line, name, kind, wrapped in decls:
            n += 1
            seen.setdefault((path.name, name), []).append(line)
            if wrapped or name in covered or (kind == "tls" and name + "_tls" in covered):
                continue
            if (path.name, name) in EXEMPT:
                exempt_used.add((path.name, name))
                continue
            bad.append("%s:%d %s (%s)" % (path.name, line, name, kind))
    if bad:
        raise SystemExit("device-bound state the device rebuild does not cover (a DeviceLatch, a DeviceLocal, a DeviceLife step "
                         "of its file, or EXEMPT with why it is not device-bound):\n  " + "\n  ".join(bad))
    stale = sorted(set(EXEMPT) - exempt_used)
    if stale:
        raise SystemExit("EXEMPT names what this test no longer finds (remove them): %s" % stale)
    missing = [site for site in JUDGED if site not in seen]
    if missing:
        raise SystemExit("the judged sites are not found by this test: %s" % missing)
    plain = [site for site in JUDGED_PLAIN if site[1] not in covered_by_file.get(site[0], set())]
    if plain:
        raise SystemExit("device facts kept as plain values that their file's release does not reset: %s" % plain)
    # (Eden's process-wide software-multiply flag: set again by each device's test, from false)
    coop = (vk / "vk_coopmat.cpp").read_text(encoding="utf-8")
    init = block_at(coop, coop.index("void coopmat_init() {"))
    if "Shader::Backend::SPIRV::mma_software = false;" not in init.split("\n")[1]:
        raise SystemExit("coopmat_init does not start from mma_software false: a GPU after one without cooperative matrices "
                         "keeps the software multiplies")
    # (the old device's objects are destroyed through its own commands: the teardown before the new device's are loaded)
    rebuild = (vk / "vk_device_rebuild.cpp").read_text(encoding="utf-8")
    once = block_at(rebuild, rebuild.index("bool rebuild_once("))
    if not once.index("make_device(want, made)") < once.index("tear_down(") < once.index("bring_up(made)"):
        raise SystemExit("vk_device_rebuild.cpp: the new device is not made and checked before the old one is torn down, "
                         "or the old one not torn down before the new one is adopted")
    # (the programs a rebuild lets go are read back from the program cache, this session's too: the release lists every record
    # the file holds again, and each record written joins that full list)
    shader = strip((vk / "vk_shader.cpp").read_text(encoding="utf-8"))
    life_at = shader.index("const DeviceLife life(kDeviceOrderPrograms")
    release = block_at(shader, shader.rindex("void release() {", 0, life_at))
    save = block_at(shader, shader.index("void program_cache_save("))
    if "disk_records = disk_known;" not in release or "disk_known[p.key].push_back(" not in save:
        raise SystemExit("vk_shader.cpp: after a device rebuild the programs already in the program cache are not all listed "
                         "again (they would be translated again)")
    # (a record listed again is no longer one taken out for the prediction: each is offered to it once)
    reopen = block_at(shader, shader.index("void disk_reopen() {"))
    if "disk_taken.clear();" not in release or "disk_taken.clear()" not in reopen:
        raise SystemExit("vk_shader.cpp: a device rebuild leaves records taken out for the prediction beside the same records "
                         "listed again (offered twice), or beside a program cache opened again for another device")
    # (the profiles of the stages pinned to 32 lanes are copies of the device's profile: worked out again with it)
    for head in ("const Shader::Profile& profile_pinned()", "const Shader::Profile& profile_graphics("):
        if "DeviceLatch<Shader::Profile>" not in block_at(shader, shader.index(head)):
            raise SystemExit("vk_shader.cpp: %s keeps the first device's profile" % head.split("& ")[1].split("(")[0])
    main_src = strip((vk / "vk_main.cpp").read_text(encoding="utf-8"))
    adopt = block_at(main_src, main_src.index("void adopt_device("))
    if adopt.index("static_cast<DeviceFacts&>(dev) = d;") > adopt.index("load_device(dev.device);"):
        raise SystemExit("adopt_device loads the device's commands before it takes the device")
    # (the start-up screen's painter presents outside the game's calls: each present is a use of its own)
    painter = main_src[main_src.index("std::thread painter("):main_src.index("SetEvent(painted);")]
    presents = [m.start() for m in re.finditer(r"present_image\(", painter)]
    if not presents or any("DeviceUse use;" not in painter[max(0, at - 160):at] for at in presents):
        raise SystemExit("the start-up screen's painter presents outside a DeviceUse: a device rebuild would not wait for it")
    # (the start-up screen's questions to the upscalers run on a thread of their own: each one is a use of its own)
    menu_src = strip((vk / "vk_menu.cpp").read_text(encoding="utf-8"))
    probe = block_at(menu_src, menu_src.index("void probe_upscalers_soon() {"))
    loop = re.search(r"for \(void \(\*(\w+)\)\(\) : \{(.*?)\}\) \{\s*DeviceUse use;\s*\1\(\);", probe, re.S)
    asked = re.findall(r"\b(?:dlss_probe|fsr4_probe|fsr3::supported)\b", probe)
    if not loop or any(q not in loop.group(2) for q in ("dlss_probe", "fsr4_probe", "fsr3::supported()")) or len(asked) != 3:
        raise SystemExit("the start-up screen asks the upscalers outside a DeviceUse: a device rebuild would not wait for it")
    make = block_at(main_src, main_src.index("bool make_device("))
    if re.search(r"\bdev\.(?!instance\b)", make):
        raise SystemExit("make_device reads the device in use (dev.): a candidate is made from the GPU given alone")
    # (and the modules' hooks it calls change no answer the device in use is read by: DLSS's is published at adoption)
    dlss = strip((vk / "vk_dlss.cpp").read_text(encoding="utf-8"))
    hook = block_at(dlss, dlss.index("void dlss_device_extensions(std::vector<const char*>& want"))
    if re.search(r"\bg_why\s*=", hook) or "dlss_device_created();" not in adopt:
        raise SystemExit("a device made and refused changes DLSS's answer for the device in use (g_why, dlss_device_created)")
    print("PASS: %d device-bound declarations, each covered or exempt (%d exempt); the judged sites found and covered; the "
          "teardown before the new device is adopted" % (n, len(exempt_used)))
    flags = [args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-pthread", "-DVK_NO_PROTOTYPES", "-I" + str(vk)]
    if os.name != "nt":   # (the Win32 types on POSIX; Windows' own windows.h otherwise)
        flags.append("-I" + str(args.root / "host" / "posix"))
    if args.vulkan_include:
        flags.append("-I" + str(args.vulkan_include))
    with tempfile.TemporaryDirectory(prefix="device-life-") as tmp:
        exe = Path(tmp) / "device_life_test"
        subprocess.run(flags + [str(args.root / "tests" / "device_life_test.cpp"), str(vk / "vk_device_life.cpp"), "-o", str(exe)],
                       check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()

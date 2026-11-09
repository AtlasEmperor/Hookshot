// Game-free regression: a predicate chooses an address, but is not its base pointer.
#include <cstdio>
#include <cstdlib>

#include "shader_recompiler/frontend/ir/ir_emitter.h"
#include "shader_recompiler/host_translate_info.h"
#include "shader_recompiler/ir_opt/passes.h"
#include "shader_recompiler/object_pool.h"

namespace Shader::Optimization {
// Normally supplied by CollectShaderInfoPass and the renderer's translation scope.
thread_local u32 g_nvn2_compute_ssbo_base{};
thread_local u32 g_nvn2_compute_ssbo_count{};
thread_local bool g_all_global_this{};
thread_local bool g_gm_port_this{};
} // namespace Shader::Optimization

using namespace Shader;

// The current pass needs an Environment for native pointer metadata. Test
// programs use the non-native route, so this fixture supplies neutral values.
struct SyntheticEnvironment final : Environment {
    u64 ReadInstruction(u32) override { return 0; }
    u32 ReadCbufValue(u32, u32) override { return 0; }
    TextureType ReadTextureType(u32) override { return {}; }
    TexturePixelFormat ReadTexturePixelFormat(u32) override { return {}; }
    bool IsTexturePixelFormatInteger(u32) override { return false; }
    u32 ReadViewportTransformState() override { return 0; }
    u32 TextureBoundBuffer() const override { return 0; }
    u32 LocalMemorySize() const override { return 0; }
    u32 SharedMemorySize() const override { return 0; }
    std::array<u32, 3> WorkgroupSize() const override { return {1, 1, 1}; }
    bool HasHLEMacroState() const override { return false; }
    std::optional<ReplaceConstant> GetReplaceConstBuffer(u32, u32) override { return std::nullopt; }
    void Dump(u64, u64) override {}
};

static void check(bool value, const char* message) {
    if (!value) {
        std::fprintf(stderr, "FAIL: %s\n", message);
        std::exit(1);
    }
}

struct Fixture {
    ObjectPool<IR::Inst> pool;
    IR::Block block{pool};
    IR::Program program;
    IR::IREmitter ir{block};

    explicit Fixture(Stage stage) {
        program.stage = stage;
        program.blocks = {&block};
        program.post_order_blocks = {&block};
    }

    IR::U32 word(u32 bank, u32 offset) {
        return ir.GetCbuf(ir.Imm32(bank), ir.Imm32(offset));
    }

    IR::U64 address(const IR::U32& low, const IR::U32& high) {
        return ir.PackUint2x32(ir.CompositeConstruct(low, high));
    }

    IR::Value loaded_pointer(u32 offset) {
        return ir.LoadGlobal64(address(word(0, offset), word(0, offset + 4)));
    }

    void run() {
        HostTranslateInfo host{};
        host.min_ssbo_alignment = 16;
        host.support_int64 = true;
        SyntheticEnvironment env{};
        Optimization::GlobalMemoryToStorageBufferPass(env, program, host);
    }

    unsigned count(IR::Opcode opcode) const {
        unsigned n{};
        for (const IR::Inst& inst : block.Instructions()) n += inst.GetOpcode() == opcode;
        return n;
    }
};

static void loaded_selection(Stage stage, bool table_condition) {
    Fixture f{stage};
    const IR::Value a{f.loaded_pointer(0x100)}, b{f.loaded_pointer(0x110)};
    IR::U32 condition_word;
    if (table_condition) {
        const IR::U32 index{f.ir.ShiftLeftLogical(f.ir.LocalInvocationIdX(), f.ir.Imm32(4))};
        condition_word = f.ir.GetCbuf(f.ir.Imm32(5), f.ir.IAdd(index, f.ir.Imm32(0x40)));
    } else {
        condition_word = f.word(5, 0x60);
    }
    const IR::U1 condition{f.ir.ILessThan(condition_word, f.ir.Imm32(1), false)};
    const IR::U32 low{f.ir.Select(condition, f.ir.CompositeExtract(a, 0), f.ir.CompositeExtract(b, 0))};
    const IR::U32 high{f.ir.Select(condition, f.ir.CompositeExtract(a, 1), f.ir.CompositeExtract(b, 1))};
    (void)f.ir.LoadGlobal128(f.address(low, high));
    f.run();

    for (const auto& d : f.program.info.storage_buffers_descriptors)
        check(d.cbuf_index != 5, "a select predicate became a storage-buffer descriptor");
    check(f.program.info.num_global_tables == 0, "a select predicate became a pointer-table descriptor");
    check(f.count(IR::Opcode::LoadGlobal128) == 1, "selected loaded pointers must keep their runtime address");
    check(f.count(IR::Opcode::LoadStorage128) == 0, "record load was rebased on unrelated condition data");
    check(f.count(IR::Opcode::LoadStorage64) == 2, "the two real pointer loads must still bind normally");
}

static void direct_pointer() {
    Fixture f{Stage::Mesh};
    const IR::U32 low{f.ir.IAdd(f.word(0, 0x100), f.ir.ShiftLeftLogical(f.ir.LocalInvocationIdX(), f.ir.Imm32(4)))};
    (void)f.ir.LoadGlobal128(f.address(low, f.word(0, 0x104)));
    f.run();
    check(f.program.info.storage_buffers_descriptors.size() == 1, "direct pointer lost its binding");
    const auto& d = f.program.info.storage_buffers_descriptors[0];
    check(d.cbuf_index == 0 && d.cbuf_offset == 0x100, "direct pointer bound the wrong slot");
    check(f.count(IR::Opcode::LoadStorage128) == 1, "direct pointer should remain a storage load");
}

static void genuine_pointer_table() {
    Fixture f{Stage::Mesh};
    const IR::U32 index{f.ir.ShiftLeftLogical(f.ir.LocalInvocationIdX(), f.ir.Imm32(4))};
    const IR::U32 offset{f.ir.IAdd(index, f.ir.Imm32(0x40))};
    const IR::U32 low{f.ir.GetCbuf(f.ir.Imm32(4), offset)};
    const IR::U32 high{f.ir.GetCbuf(f.ir.Imm32(4), f.ir.IAdd(offset, f.ir.Imm32(4)))};
    (void)f.ir.LoadGlobal128(f.address(low, high));
    f.run();
    check(f.program.info.num_global_tables == 1, "genuine pointer table was not retained");
    const auto& t = f.program.info.global_tables[0];
    check(t.first == 4 && t.second == 0x40, "genuine pointer table changed");
    check(f.count(IR::Opcode::LoadGlobal128) == 1, "table access should keep runtime buffer selection");
}

int main() {
    direct_pointer();
    genuine_pointer_table();
    for (const Stage stage : {Stage::Task, Stage::Mesh, Stage::Compute}) {
        loaded_selection(stage, false);
        loaded_selection(stage, true);
    }
    std::puts("PASS: predicate-only cbufs stay out of storage bindings and pointer tables; real pointers preserved");
    return 0;
}

#include "datasys.h"

#include <windows.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace datasys {
namespace {

// ---------------------------------------------------------------- 游戏侧结构
// CPdxArray<T>：{ T* data; int capacity; int size; IAllocator* allocator }
struct PdxArray {
    void* data;
    int capacity;
    int size;
    void* allocator;
};
static_assert(sizeof(PdxArray) == 0x18, "CPdxArray 布局");

// 字符串视图：{ const char* ptr; int len; bool null_terminated }
struct StrView {
    const char* ptr;
    int len;
    bool nul;
};

struct GameString {
    union { char buf[16]; char* ptr; };
    size_t size;
    size_t cap;
    const char* c_str() const { return cap > 15 ? ptr : buf; }
};

using ArrayInitFn = void* (*)(PdxArray*);
using EmptyTypeFn = void* (*)();
using StmtCtorFn = void* (*)(void* stmt);
using CreateStmtFn = bool (*)(void* factory, const StrView* text, void* stmt, bool flag, void* extra);
using EvalFn = bool (*)(void* stmt, PdxArray* ctx, void* scratch, void* any_out);
using BuildLocFn = bool (*)(const StrView* text, PdxArray* out, void*, void*, void*);
using FetchLocFn = void* (*)(void* result, const PdxArray* loc, PdxArray* ctx, void* scratch);
// Evaluate 内部的两步：先按上下文解析提升（写进 scratch、得到调用对象），再调用末端函数
using ResolveFn = bool (*)(void* stmt, PdxArray* ctx, void* scratch, void* target_out, int* id);
using CallVoidFn = bool (*)(void* call, void* target, void* arg_any, void* scratch);
using DefaultIdFn = int* (*)();

uint8_t* g_base = nullptr;
ArrayInitFn g_array_init = nullptr;
EmptyTypeFn g_empty_type = nullptr;
StmtCtorFn g_stmt_ctor = nullptr;
CreateStmtFn g_create = nullptr;
EvalFn g_eval = nullptr;
BuildLocFn g_build_loc = nullptr;
FetchLocFn g_fetch_loc = nullptr;
ResolveFn g_resolve = nullptr;
CallVoidFn g_call_void = nullptr;
DefaultIdFn g_default_id = nullptr;
void** g_factory = nullptr;  // 全局数据工厂指针所在的地址

// Evaluate 的第三个参数：语句里的提升（promote）中间结果按 40 字节一项写进 *scratch
struct Scratch {
    void* data;
    int capacity;
    int size;
    void* allocator;
};
alignas(16) uint8_t g_scratch_buf[40 * 4096];

// ---------------------------------------------------------------- SEH 包装（不能有带析构的局部变量）
DWORD g_last_exception = 0;

bool seh_create(void* factory, const StrView* v, void* stmt, bool flag) {
    __try {
        return g_create(factory, v, stmt, flag, nullptr);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        g_last_exception = GetExceptionCode();
        return false;
    }
}

int seh_eval(void* stmt, PdxArray* ctx, void* scratch, void* any) {
    __try {
        return g_eval(stmt, ctx, scratch, any) ? 1 : 0;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        g_last_exception = GetExceptionCode();
        return -1;
    }
}

int seh_exec(void* stmt, PdxArray* ctx, void* scratch, void* arg_any) {
    __try {
        struct { void* ptr; bool flag; char pad[7]; } target = {};
        int id = *g_default_id();
        if (!g_resolve(stmt, ctx, scratch, &target, &id)) return 0;
        return g_call_void(static_cast<uint8_t*>(stmt) + 0x18, &target, arg_any, scratch) ? 1 : 0;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        g_last_exception = GetExceptionCode();
        return -1;
    }
}

int seh_build_loc(const StrView* v, PdxArray* loc) {
    __try {
        return g_build_loc(v, loc, nullptr, nullptr, nullptr) ? 1 : 0;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        g_last_exception = GetExceptionCode();
        return -1;
    }
}

bool seh_fetch(void* result, const PdxArray* loc, PdxArray* ctx, void* scratch) {
    __try {
        g_fetch_loc(result, loc, ctx, scratch);
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        g_last_exception = GetExceptionCode();
        return false;
    }
}

std::string exc_text(const char* what) {
    char b[96];
    snprintf(b, sizeof b, "%s 时异常 0x%08lX", what, g_last_exception);
    return b;
}

Scratch make_scratch() {
    memset(g_scratch_buf, 0, sizeof g_scratch_buf);
    return Scratch{g_scratch_buf, 4096, 0, nullptr};
}

}  // namespace

bool locate(uint8_t* base, std::string* error) {
    // TODO：换成特征码定位（当前为 1.13.11 实测地址，验证调用约定用）
    g_base = base;
    g_array_init = reinterpret_cast<ArrayInitFn>(base + 0x0061c180);
    g_empty_type = reinterpret_cast<EmptyTypeFn>(base + 0x0063af30);
    g_stmt_ctor = reinterpret_cast<StmtCtorFn>(base + 0x02d11f40);
    g_create = reinterpret_cast<CreateStmtFn>(base + 0x03a7b010);
    g_eval = reinterpret_cast<EvalFn>(base + 0x03a79ce0);
    g_build_loc = reinterpret_cast<BuildLocFn>(base + 0x03a85270);
    g_fetch_loc = reinterpret_cast<FetchLocFn>(base + 0x03a85df0);
    g_factory = reinterpret_cast<void**>(base + 0x0592ebb8);
    g_resolve = reinterpret_cast<ResolveFn>(base + 0x03a79b80);
    g_call_void = reinterpret_cast<CallVoidFn>(base + 0x03a797b0);
    g_default_id = reinterpret_cast<DefaultIdFn>(base + 0x00626b80);
    (void)error;
    return true;
}

bool ready() { return g_eval != nullptr; }

std::string describe() { return "{}"; }

bool read(const std::string& text, std::string* out, std::string* error) {
    PdxArray loc;
    g_array_init(&loc);
    StrView v{text.c_str(), static_cast<int>(text.size()), true};
    int built = seh_build_loc(&v, &loc);
    if (built < 0) { *error = exc_text("解析"); return false; }
    if (built == 0) { *error = "解析失败（表达式不合法，看 error.log）"; return false; }
    PdxArray ctx;
    g_array_init(&ctx);
    Scratch scr = make_scratch();
    alignas(16) uint8_t result[0x40] = {};
    if (!seh_fetch(result, &loc, &ctx, &scr)) { *error = exc_text("求值"); return false; }
    auto* s = reinterpret_cast<GameString*>(result);
    out->assign(s->c_str(), s->size);
    if (result[0x20]) { *error = "求值失败（看 error.log）"; return false; }
    // 解析出的条目与结果字符串都由游戏分配，这里不释放（泄漏很小）
    return true;
}

bool exec(const std::string& statement, bool flag, std::string* error) {
    alignas(16) uint8_t stmt[0x200] = {};
    g_stmt_ctor(stmt);
    StrView v{statement.c_str(), static_cast<int>(statement.size()), true};
    if (!seh_create(*g_factory, &v, stmt, flag)) {
        *error = g_last_exception ? exc_text("构建语句") : "构建语句失败（看 error.log）";
        g_last_exception = 0;
        return false;
    }
    PdxArray ctx;
    g_array_init(&ctx);
    Scratch scr = make_scratch();
    alignas(16) uint8_t any[0x80] = {};
    *reinterpret_cast<void**>(any) = g_empty_type();
    int r = seh_exec(stmt, &ctx, &scr, any);
    if (r < 0) { *error = exc_text("执行"); return false; }
    if (r == 0) { *error = "执行失败（看 error.log）"; return false; }
    return true;
}

}  // namespace datasys

#include "datasys.h"

#include <windows.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "scan.h"

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

// 求值上下文的一项：{ 对象指针; 类型 id; 是否 const }。语句建立时记下自己需要哪些上下文类型
// （SPdxDataStatement+0xb8 的 int 数组），求值时按同样的顺序给出对象。
struct CtxEntry {
    void* ptr;
    int type_id;
    bool is_const;
    char pad[3];
};
static_assert(sizeof(CtxEntry) == 0x10, "上下文项布局");

// 数据模型（列表）里第 i 项的 datacontext：+0 对象，+0x28 转换函数，+0x30 种类，+0x38 类型 id
struct DataContext {
    uint8_t raw[0x40];
};

constexpr size_t kStmtSize = 0x200;        // SPdxDataStatement 实际 0x138，留余量
constexpr size_t kStmtReqTypes = 0xb8;     // 需要的上下文类型（每项 8 字节）
constexpr size_t kStmtReqCount = 0xc4;     // int  个数
constexpr size_t kStmtCall = 0x18;         // 末端调用（CallVoid 的第一个参数）
constexpr size_t kLocEntrySize = 0x178;    // BuildLocData 产出的每一段
constexpr size_t kLocEntryStmt = 0x20;     // 段内的语句

using ArrayInitFn = void* (*)(PdxArray*);
using EmptyTypeFn = void* (*)();
using StmtCtorFn = void* (*)(void* stmt);
using StmtDtorFn = void (*)(void* stmt);
using CreateStmtFn = bool (*)(void* factory, const StrView* text, void* stmt, bool flag, void* extra);
using EvalFn = bool (*)(void* stmt, PdxArray* ctx, void* scratch, void* any_out);
using BuildLocFn = bool (*)(const StrView* text, PdxArray* out, void*, void*, void*);
using FetchLocFn = void* (*)(void* result, const PdxArray* loc, PdxArray* ctx, void* scratch);
// Evaluate 内部的两步：先按上下文解析提升（写进 scratch、得到调用对象），再调用末端函数
using ResolveFn = bool (*)(void* stmt, PdxArray* ctx, void* scratch, void* target_out, int* id);
using CallVoidFn = bool (*)(void* call, void* target, void* arg_any, void* scratch);
using DefaultIdFn = int* (*)();
// 数据模型实现的虚表：[0] 个数 (impl, storage)，[3] 第 i 项的 datacontext (impl, out, storage, i)
using ModelSizeFn = int (*)(void* impl, void* storage);
using ModelItemFn = void* (*)(void* impl, DataContext* out, void* storage, int index);
using DcConvertFn = void (*)(DataContext* dc, CtxEntry* out);

// 游戏状态访问作用域（引擎自己的 RAII，界面更新时就处在 Interface 访问下）：
// ctor(scope, access, hidden_access, reason)，dtor(scope)。部分数据函数断言必须在这个作用域里调用。
using AccessCtorFn = void* (*)(void* scope, int access, int hidden, const char* reason);
using AccessDtorFn = void (*)(void* scope);
constexpr int kAccessInterface = 1;

uint8_t* g_base = nullptr;
AccessCtorFn g_access_ctor = nullptr;
AccessDtorFn g_access_dtor = nullptr;
ArrayInitFn g_array_init = nullptr;
EmptyTypeFn g_empty_type = nullptr;
StmtCtorFn g_stmt_ctor = nullptr;
StmtDtorFn g_stmt_dtor = nullptr;
CreateStmtFn g_create = nullptr;
EvalFn g_eval = nullptr;
BuildLocFn g_build_loc = nullptr;
FetchLocFn g_fetch_loc = nullptr;
ResolveFn g_resolve = nullptr;
CallVoidFn g_call_void = nullptr;
DefaultIdFn g_default_id = nullptr;
void** g_factory = nullptr;  // 全局数据工厂指针所在的地址

// Evaluate 的第三个参数：语句里各个调用的实参 / 提升中间结果，40 字节一项，按下标写进 scratch->data。
// 回调会按 size 新建同样大小的临时数组再按下标取实参 —— size 必须不小于语句里的槽位数，
// 界面上是按语句精确 resize 的，这里给一个足够大的固定值。
struct Scratch {
    void* data;
    int capacity;
    int size;
    void* allocator;
};
constexpr int kScratchSlots = 256;
alignas(16) uint8_t g_scratch_buf[40 * kScratchSlots];

Scratch make_scratch() {
    memset(g_scratch_buf, 0, sizeof g_scratch_buf);
    return Scratch{g_scratch_buf, kScratchSlots, kScratchSlots, nullptr};
}

// ---------------------------------------------------------------- SEH 包装（不能有带析构的局部变量）
DWORD g_last_exception = 0;
uint64_t g_last_fault = 0;  // 异常地址（相对模块基址），排查用
uint64_t g_fault_stack[10] = {};

int filter(EXCEPTION_POINTERS* ep) {
    g_last_exception = ep->ExceptionRecord->ExceptionCode;
    g_last_fault = reinterpret_cast<uint64_t>(ep->ExceptionRecord->ExceptionAddress) - reinterpret_cast<uint64_t>(g_base);
    CONTEXT c = *ep->ContextRecord;  // 往上展开几帧，便于定位是哪一层传错了参数
    for (int i = 0; i < 10; ++i) {
        g_fault_stack[i] = c.Rip - reinterpret_cast<uint64_t>(g_base);
        DWORD64 image = 0;
        auto* fn = RtlLookupFunctionEntry(c.Rip, &image, nullptr);
        if (!fn) break;
        void* hd = nullptr;
        DWORD64 frame = 0;
        RtlVirtualUnwind(UNW_FLAG_NHANDLER, image, c.Rip, fn, &c, &hd, &frame, nullptr);
    }
    return EXCEPTION_EXECUTE_HANDLER;
}

bool seh_create(const StrView* v, void* stmt, bool flag) {
    __try {
        return g_create(*g_factory, v, stmt, flag, nullptr);
    } __except (filter(GetExceptionInformation())) {
        return false;
    }
}

void seh_destroy(void* stmt) {
    __try {
        if (g_stmt_dtor) g_stmt_dtor(stmt);
    } __except (filter(GetExceptionInformation())) {
    }
}

int seh_eval(void* stmt, PdxArray* ctx, void* scratch, void* any) {
    __try {
        return g_eval(stmt, ctx, scratch, any) ? 1 : 0;
    } __except (filter(GetExceptionInformation())) {
        return -1;
    }
}

int seh_exec(void* stmt, PdxArray* ctx, void* scratch, void* arg_any) {
    __try {
        struct { void* ptr; bool flag; char pad[7]; } target = {};
        int id = *g_default_id();
        if (!g_resolve(stmt, ctx, scratch, &target, &id)) return 0;
        return g_call_void(static_cast<uint8_t*>(stmt) + kStmtCall, &target, arg_any, scratch) ? 1 : 0;
    } __except (filter(GetExceptionInformation())) {
        return -1;
    }
}

int seh_build_loc(const StrView* v, PdxArray* loc) {
    __try {
        return g_build_loc(v, loc, nullptr, nullptr, nullptr) ? 1 : 0;
    } __except (filter(GetExceptionInformation())) {
        return -1;
    }
}

bool seh_fetch(void* result, const PdxArray* loc, PdxArray* ctx, void* scratch) {
    __try {
        g_fetch_loc(result, loc, ctx, scratch);
        return true;
    } __except (filter(GetExceptionInformation())) {
        return false;
    }
}

int seh_model_size(void* impl, void* storage) {
    __try {
        return reinterpret_cast<ModelSizeFn>((*reinterpret_cast<void***>(impl))[0])(impl, storage);
    } __except (filter(GetExceptionInformation())) {
        return -1;
    }
}

bool seh_model_item(void* impl, DataContext* out, void* storage, int i) {
    __try {
        reinterpret_cast<ModelItemFn>((*reinterpret_cast<void***>(impl))[3])(impl, out, storage, i);
        return true;
    } __except (filter(GetExceptionInformation())) {
        return false;
    }
}

bool seh_dc_convert(DataContext* dc, CtxEntry* e) {
    __try {
        auto fn = *reinterpret_cast<DcConvertFn*>(dc->raw + 0x28);
        if (fn) fn(dc, e);
        return true;
    } __except (filter(GetExceptionInformation())) {
        return false;
    }
}

std::string exc_text(const char* what) {
    char b[128];
    snprintf(b, sizeof b, "%s 时异常 0x%08lX @ 0x%llx", what, g_last_exception,
             static_cast<unsigned long long>(g_last_fault));
    std::string o = b;
    for (uint64_t f : g_fault_stack) {
        snprintf(b, sizeof b, " %llx", static_cast<unsigned long long>(f));
        o += b;
    }
    g_last_exception = 0;
    return o;
}

// ---------------------------------------------------------------- 上下文
// datacontext → 上下文项（游戏 035ee7c0 的等价实现）：种类 0/1 直接给指针（const / 非 const），
// 其余种类由 datacontext 自带的转换函数填指针
bool to_ctx_entry(DataContext* dc, CtxEntry* e) {
    e->type_id = *reinterpret_cast<int*>(dc->raw + 0x38);
    int8_t kind = static_cast<int8_t>(dc->raw[0x30]);
    switch (kind) {
        case -1: return false;
        case 0: e->ptr = *reinterpret_cast<void**>(dc->raw); e->is_const = true; return true;
        case 1: e->ptr = *reinterpret_cast<void**>(dc->raw); e->is_const = false; return true;
        case 2: e->is_const = true; return seh_dc_convert(dc, e);
        default: e->is_const = false; return seh_dc_convert(dc, e);
    }
}

// 按语句的需求排好上下文数组。items 里类型对得上的就填进去，其余留空（全局表达式用不到）。
// 返回的数组指向 storage，调用方保证 storage 活得比求值久。
std::string g_ctx_note;  // 最近一次没配上的上下文需求，失败时附在错误信息后面

// 类型 id 取这个值的上下文项可以顶替任何没配上的需求：用于自己构造、拿不到类型 id 的界面对象
constexpr int kAnyType = INT32_MIN;

PdxArray make_ctx(void* stmt, const CtxEntry* items, int n_items, CtxEntry* storage, int cap) {
    PdxArray ctx;
    g_array_init(&ctx);
    g_ctx_note.clear();
    int n = stmt ? *reinterpret_cast<int*>(static_cast<uint8_t*>(stmt) + kStmtReqCount) : 0;
    if (n <= 0 || n > cap) return ctx;
    // 需求表每项 8 字节，类型 id 在低 4 字节（游戏里按 [base + k*8] 读）
    const uint8_t* req_base = *reinterpret_cast<uint8_t**>(static_cast<uint8_t*>(stmt) + kStmtReqTypes);
    int req[16];
    for (int k = 0; k < n; ++k) req[k] = *reinterpret_cast<const int*>(req_base + k * 8);
    for (int k = 0; k < n; ++k) {
        storage[k] = CtxEntry{nullptr, *g_default_id(), true, {}};
        bool matched = false;
        for (int j = 0; j < n_items; ++j) {
            if (items[j].type_id == req[k]) {
                storage[k] = items[j];
                matched = true;
            }
        }
        for (int j = 0; j < n_items && !matched; ++j) {
            if (items[j].type_id == kAnyType) {
                storage[k] = items[j];
                storage[k].type_id = req[k];
                matched = true;
            }
        }
        if (!matched) {
            g_ctx_note += "（需要上下文类型 " + std::to_string(req[k]) + "，路径提供了";
            for (int j = 0; j < n_items; ++j) g_ctx_note += " " + std::to_string(items[j].type_id);
            g_ctx_note += "）";
        }
    }
    ctx.data = storage;
    ctx.capacity = n;
    ctx.size = n;
    ctx.allocator = nullptr;  // 求值只读不改，用不到分配器
    return ctx;
}

// ---------------------------------------------------------------- 基本操作（带上下文）
bool read_in(const std::string& text, const CtxEntry* items, int n_items, std::string* out, std::string* error) {
    PdxArray loc;
    g_array_init(&loc);
    StrView v{text.c_str(), static_cast<int>(text.size()), true};
    int built = seh_build_loc(&v, &loc);
    if (built < 0) { *error = exc_text("解析"); return false; }
    if (built == 0) { *error = "解析失败（表达式不合法，看 error.log）"; return false; }
    // 一段文本可以含多个 [..]，但它们共用一个上下文数组：带上下文时只允许一个表达式
    void* stmt = nullptr;
    int with_req = 0;
    for (int i = 0; i < loc.size; ++i) {
        void* s = static_cast<uint8_t*>(loc.data) + i * kLocEntrySize + kLocEntryStmt;
        if (*reinterpret_cast<int*>(static_cast<uint8_t*>(s) + kStmtReqCount) > 0) {
            stmt = s;
            ++with_req;
        }
    }
    if (with_req > 1) { *error = "带上下文的文本只能有一个需要上下文的 [..]"; return false; }
    CtxEntry storage[16];
    PdxArray ctx = make_ctx(stmt, items, n_items, storage, 16);
    Scratch scr = make_scratch();
    alignas(16) uint8_t result[0x40] = {};
    if (!seh_fetch(result, &loc, &ctx, &scr)) { *error = exc_text("求值"); return false; }
    auto* s = reinterpret_cast<GameString*>(result);
    out->assign(s->c_str(), s->size);
    if (result[0x20]) { *error = "求值失败（看 error.log）" + g_ctx_note; return false; }
    // 解析出的段与结果字符串由游戏分配，这里不释放（每次几百字节）
    return true;
}

bool exec_in(const std::string& statement, const CtxEntry* items, int n_items, std::string* error) {
    alignas(16) uint8_t stmt[kStmtSize] = {};
    g_stmt_ctor(stmt);
    StrView v{statement.c_str(), static_cast<int>(statement.size()), true};
    if (!seh_create(&v, stmt, true)) {
        *error = g_last_exception ? exc_text("构建语句") : "构建语句失败（看 error.log）";
        seh_destroy(stmt);
        return false;
    }
    CtxEntry storage[16];
    PdxArray ctx = make_ctx(stmt, items, n_items, storage, 16);
    Scratch scr = make_scratch();
    alignas(16) uint8_t any[0x80] = {};
    *reinterpret_cast<void**>(any) = g_empty_type();
    int r = seh_exec(stmt, &ctx, &scr, any);
    seh_destroy(stmt);
    if (r < 0) { *error = exc_text("执行"); return false; }
    if (r == 0) { *error = "执行失败（看 error.log）" + g_ctx_note; return false; }
    return true;
}

bool eval_in(const std::string& statement, bool flag, const CtxEntry* items, int n_items, uint8_t* any_out,
             std::string* error) {
    alignas(16) uint8_t stmt[kStmtSize] = {};
    g_stmt_ctor(stmt);
    StrView v{statement.c_str(), static_cast<int>(statement.size()), true};
    if (!seh_create(&v, stmt, flag)) {
        *error = g_last_exception ? exc_text("构建语句") : "构建语句失败（看 error.log）";
        seh_destroy(stmt);
        return false;
    }
    CtxEntry storage[16];
    PdxArray ctx = make_ctx(stmt, items, n_items, storage, 16);
    Scratch scr = make_scratch();
    *reinterpret_cast<void**>(any_out) = g_empty_type();
    int r = seh_eval(stmt, &ctx, &scr, any_out);
    seh_destroy(stmt);
    if (r < 0) { *error = exc_text("求值"); return false; }
    if (r == 0) { *error = "求值失败（看 error.log）" + g_ctx_note; return false; }
    return true;
}

// 列表求值得到的 CPdxAny 里是数据模型：类型指针低位为 1 时存储在堆上（+8 是指针），否则内联在 +8。
// 模型本身 = { impl*; storage... }
struct Model {
    void* impl;
    void* storage;
};

struct AnyBuf {
    alignas(16) uint8_t b[0x80];
};

bool open_model(const std::string& list, const std::vector<CtxEntry>& items, AnyBuf* any, Model* m, int* size,
                std::string* error) {
    if (!eval_in(list, true, items.data(), static_cast<int>(items.size()), any->b, error)) return false;
    uint64_t type = *reinterpret_cast<uint64_t*>(any->b);
    uint8_t* model = (type & 1) ? *reinterpret_cast<uint8_t**>(any->b + 8) : any->b + 8;
    m->impl = *reinterpret_cast<void**>(model);
    m->storage = model + 8;
    if (!m->impl) { *error = "不是数据模型（列表）：" + list; return false; }
    *size = seh_model_size(m->impl, m->storage);
    if (*size < 0) { *error = exc_text("取列表长度"); return false; }
    return true;
}

bool item_ctx(const Model& m, int i, CtxEntry* e, std::string* error) {
    DataContext dc{};
    if (!seh_model_item(m.impl, &dc, m.storage, i)) { *error = exc_text("取列表项"); return false; }
    if (!to_ctx_entry(&dc, e)) { *error = "列表项没有可用的上下文"; return false; }
    return true;
}

// 沿路径逐层取列表项，累积成上下文：[(Country.AccessStates, 3), (State.GetPotentialUrbanBuildings, 0)]
// 之后的表达式就能同时用 State 与 Building。anys 保存各层列表的求值结果，调用方用完前不能释放。
bool walk(const std::vector<PathStep>& path, std::vector<CtxEntry>* items, std::vector<AnyBuf>* anys,
          std::string* error) {
    anys->reserve(path.size() + 1);
    for (const PathStep& step : path) {
        anys->emplace_back();
        Model m{};
        int size = 0;
        if (!open_model(step.list, *items, &anys->back(), &m, &size, error)) return false;
        if (step.index < 0 || step.index >= size) {
            *error = step.list + " 下标 " + std::to_string(step.index) + " 越界（共 " + std::to_string(size) + " 项）";
            return false;
        }
        CtxEntry e{};
        if (!item_ctx(m, step.index, &e, error)) return false;
        items->push_back(e);
    }
    return true;
}

// ---------------------------------------------------------------- 定位
uint8_t* call_target_after(uint8_t* site, size_t offset) { return scan::rel32_target(site + offset, 1); }

bool function_bounds(uint8_t* addr, uint8_t** begin, size_t* size) {
    DWORD64 image = 0;
    auto* fn = RtlLookupFunctionEntry(reinterpret_cast<DWORD64>(addr), &image, nullptr);
    if (!fn) return false;
    *begin = reinterpret_cast<uint8_t*>(image + fn->BeginAddress);
    *size = fn->EndAddress - fn->BeginAddress;
    return true;
}

std::string g_describe;

// 在 Interface 访问作用域里执行：与界面更新时同样的前提
struct Access {
    alignas(16) uint8_t scope[0x80] = {};
    bool on = false;
    Access() {
        if (g_access_ctor) {
            g_access_ctor(scope, kAccessInterface, 0, "V3Bridge");
            on = true;
        }
    }
    ~Access() {
        if (on) g_access_dtor(scope);
    }
};

}  // namespace

bool locate(uint8_t* base, std::string* error) {
    g_base = base;
    scan::Module mod = scan::main_module();
    uint8_t* refs[4];
    auto fail = [&](const char* what) {
        *error = what;
        g_eval = nullptr;
        return false;
    };

    // FetchLocalized：唯一引用 "FetchData failed for '{}'" 的函数（本地化文本里 [..] 的求值）
    uint8_t* s = scan::find_cstring(mod.rdata, "FetchData failed for '{}'");
    if (!s || scan::find_lea_refs(mod.text, s, refs, 4) != 1) return fail("找不到 FetchData failed 的唯一引用");
    uint8_t* fetch = scan::function_start(refs[0]);
    uint8_t* fb = nullptr;
    size_t fs = 0;
    if (!function_bounds(fetch, &fb, &fs)) return fail("FetchLocalized 没有展开信息");
    // 其中：lea rcx,[rbx+20h]; lea r9,[rsp+48h]; mov r8,[rbp+..]; mov rdx,[rbp+..]; call Evaluate
    uint8_t* site = scan::find_pattern(fb, fs, "48 8D 4B 20 4C 8D 4C 24 48 4C 8B 85 ?? ?? ?? ?? 48 8B 95 ?? ?? ?? ?? E8");
    if (!site) return fail("FetchLocalized 里找不到 Evaluate 调用");
    uint8_t* eval = call_target_after(site, 23);
    // 开头：mov dword [rsp+30h],1; call EmptyAnyType
    site = scan::find_pattern(fb, fs, "C7 44 24 30 01 00 00 00 E8");
    if (!site) return fail("FetchLocalized 里找不到空 CPdxAny 类型");
    uint8_t* empty = call_target_after(site, 8);

    // Evaluate 里：call DefaultId; lea r9,[rsp+30h]; ... call Resolve
    uint8_t* eb = nullptr;
    size_t es = 0;
    if (!function_bounds(eval, &eb, &es)) return fail("Evaluate 没有展开信息");
    site = scan::find_pattern(eb, es,
                              "E8 ?? ?? ?? ?? 4C 8D 4C 24 30 4C 8B C5 49 8B D6 8B 08 48 8D 44 24 60 89 4C 24 60 "
                              "48 8B CF 48 89 44 24 20 E8");
    if (!site) return fail("Evaluate 里找不到 Resolve 调用");
    uint8_t* default_id = call_target_after(site, 0);
    uint8_t* resolve = call_target_after(site, 35);

    // CallVoid / CallValue 都引用 "No function for call '{}'"；Evaluate 用的是 CallValue，另一个就是 CallVoid
    s = scan::find_cstring(mod.rdata, "No function for call '{}'");
    size_t n = s ? scan::find_lea_refs(mod.text, s, refs, 4) : 0;
    if (n != 2) return fail("No function for call 的引用数不是 2");
    uint8_t* f0 = scan::function_start(refs[0]);
    uint8_t* f1 = scan::function_start(refs[1]);
    uint8_t* call_value = nullptr;
    for (uint8_t* p = eb; p + 5 <= eb + es; ++p) {
        if (*p == 0xE8 && (scan::rel32_target(p, 1) == f0 || scan::rel32_target(p, 1) == f1)) {
            call_value = scan::rel32_target(p, 1);
        }
    }
    if (!call_value) return fail("Evaluate 里找不到 CallValue");
    uint8_t* call_void = call_value == f0 ? f1 : f0;

    // BuildLocData：mov r9b,1; lea r8,[rbp-20h]; lea rdx,[rbp+140h]; mov rcx,[rip+工厂]; call CreateStatement
    site = scan::find_pattern(mod.text.begin, mod.text.size,
                              "41 B1 01 4C 8D 45 E0 48 8D 95 40 01 00 00 48 8B 0D ?? ?? ?? ?? E8");
    if (!site) return fail("找不到 BuildLocData 里的 CreateStatement 调用");
    uint8_t* create = call_target_after(site, 21);
    void** factory = reinterpret_cast<void**>(site + 21 + *reinterpret_cast<int32_t*>(site + 17));
    uint8_t* build = scan::function_start(site);
    uint8_t* bb = nullptr;
    size_t bs = 0;
    if (!function_bounds(build, &bb, &bs)) return fail("BuildLocData 没有展开信息");
    // 语句的构造 / 析构：lea rcx,[rbp-20h]; call ...，第一个是构造，另一个是析构
    uint8_t* ctor = nullptr;
    uint8_t* dtor = nullptr;
    for (uint8_t* p = bb; p + 9 <= bb + bs; ++p) {
        if (p[0] == 0x48 && p[1] == 0x8D && p[2] == 0x4D && p[3] == 0xE0 && p[4] == 0xE8) {
            uint8_t* t = scan::rel32_target(p + 4, 1);
            if (!ctor) ctor = t;
            else if (t != ctor && !dtor) dtor = t;
        }
    }
    if (!ctor || !dtor) return fail("BuildLocData 里找不到语句的构造 / 析构");
    // 构造函数开头：mov rbx,rcx; call CPdxArray::Init
    uint8_t* cb = nullptr;
    size_t cs = 0;
    if (!function_bounds(ctor, &cb, &cs)) return fail("语句构造函数没有展开信息");
    site = scan::find_pattern(cb, cs, "48 8B D9 E8");
    if (!site) return fail("找不到 CPdxArray::Init");
    uint8_t* array_init = call_target_after(site, 3);

    // 访问作用域：SetAccessToDestroyed 所在函数之后紧挨着的两个函数就是作用域的构造与析构；
    // 用「构造函数第一个 lea 指向的全局」与 SetAccessToDestroyed 写的全局是否一致来核对
    s = scan::find_cstring(mod.rdata, "NGameState::SetAccessToDestroyed");
    if (!s || scan::find_lea_refs(mod.text, s, refs, 4) == 0) return fail("找不到 SetAccessToDestroyed");
    uint8_t* destroyed = scan::function_start(refs[0]);
    uint8_t* access_global = nullptr;
    {
        uint8_t* db = nullptr;
        size_t ds = 0;
        if (!function_bounds(destroyed, &db, &ds)) return fail("SetAccessToDestroyed 没有展开信息");
        uint8_t* w = scan::find_pattern(db, ds, "89 05");  // mov dword [rip+disp], eax
        if (w) access_global = w + 6 + *reinterpret_cast<int32_t*>(w + 2);
    }
    uint8_t* actor = nullptr;
    uint8_t* adtor = nullptr;
    {
        uint8_t* db = nullptr;
        size_t ds = 0;
        function_bounds(destroyed, &db, &ds);
        uint8_t* p = db + ds;
        while (*p == 0xCC) ++p;  // 跳过函数间的填充
        actor = p;
        uint8_t* ab = nullptr;
        size_t as = 0;
        if (!function_bounds(actor, &ab, &as) || ab != actor) return fail("访问作用域构造函数边界不对");
        uint8_t* l = scan::find_pattern(ab, as, "48 8D 05");
        if (!l || l + 7 + *reinterpret_cast<int32_t*>(l + 3) != access_global) return fail("访问作用域构造函数核对失败");
        p = ab + as;
        while (*p == 0xCC) ++p;
        adtor = p;
    }
    g_access_ctor = reinterpret_cast<AccessCtorFn>(actor);
    g_access_dtor = reinterpret_cast<AccessDtorFn>(adtor);

    g_array_init = reinterpret_cast<ArrayInitFn>(array_init);
    g_empty_type = reinterpret_cast<EmptyTypeFn>(empty);
    g_stmt_ctor = reinterpret_cast<StmtCtorFn>(ctor);
    g_stmt_dtor = reinterpret_cast<StmtDtorFn>(dtor);
    g_create = reinterpret_cast<CreateStmtFn>(create);
    g_build_loc = reinterpret_cast<BuildLocFn>(build);
    g_fetch_loc = reinterpret_cast<FetchLocFn>(fetch);
    g_resolve = reinterpret_cast<ResolveFn>(resolve);
    g_call_void = reinterpret_cast<CallVoidFn>(call_void);
    g_default_id = reinterpret_cast<DefaultIdFn>(default_id);
    g_factory = factory;
    g_eval = reinterpret_cast<EvalFn>(eval);

    auto h = [&](const void* p) { return scan::hex(p, base); };
    g_describe = "{\"fetch\":\"" + h(fetch) + "\",\"eval\":\"" + h(eval) + "\",\"resolve\":\"" + h(resolve) +
                 "\",\"call_void\":\"" + h(call_void) + "\",\"create\":\"" + h(create) + "\",\"build_loc\":\"" +
                 h(build) + "\",\"stmt_ctor\":\"" + h(ctor) + "\",\"stmt_dtor\":\"" + h(dtor) +
                 "\",\"array_init\":\"" + h(array_init) + "\",\"factory\":\"" + h(factory) +
                 "\",\"access_ctor\":\"" + h(actor) + "\",\"access_dtor\":\"" + h(adtor) + "\"}";
    return true;
}

bool ready() { return g_eval != nullptr; }

std::string describe() { return g_describe.empty() ? "null" : g_describe; }

bool read(const std::vector<PathStep>& path, const std::string& text, std::string* out, std::string* error) {
    Access access;
    std::vector<CtxEntry> items;
    std::vector<AnyBuf> anys;
    if (!walk(path, &items, &anys, error)) return false;
    return read_in(text, items.data(), static_cast<int>(items.size()), out, error);
}

bool exec(const std::vector<PathStep>& path, const std::string& statement, std::string* error) {
    Access access;
    std::vector<CtxEntry> items;
    std::vector<AnyBuf> anys;
    if (!walk(path, &items, &anys, error)) return false;
    return exec_in(statement, items.data(), static_cast<int>(items.size()), error);
}

bool eval_raw(const std::string& statement, bool flag, uint8_t* any_out, std::string* error) {
    Access access;
    return eval_in(statement, flag, nullptr, 0, any_out, error);
}

bool list_read(const std::vector<PathStep>& path, const std::string& list, const std::vector<std::string>& fields,
               int limit, std::vector<std::vector<std::string>>* rows, std::string* error) {
    Access access;
    std::vector<CtxEntry> items;
    std::vector<AnyBuf> anys;
    if (!walk(path, &items, &anys, error)) return false;
    anys.emplace_back();
    Model m{};
    int size = 0;
    if (!open_model(list, items, &anys.back(), &m, &size, error)) return false;
    if (limit > 0 && size > limit) size = limit;
    items.emplace_back();
    for (int i = 0; i < size; ++i) {
        std::vector<std::string> row;
        if (!item_ctx(m, i, &items.back(), error)) return false;
        for (const std::string& f : fields) {
            std::string v, err;
            // 单个字段失败不中断整张表，以  开头标出
            if (!read_in(f, items.data(), static_cast<int>(items.size()), &v, &err)) v = "" + err;
            row.push_back(v);
        }
        rows->push_back(std::move(row));
    }
    return true;
}

// ---------------------------------------------------------------- 改组政府
// 界面上「改组政府」的数据对象 CReformGovernment 挂在政治面板（PoliticsPanel）上，从玩家国家走不到。
// ReformGovernment.Confirm（1.13.11 的 0228a140 → 02286390）只读这个对象里的拟议名单：
//   +0x18 名单数组 data（元素是利益集团对象指针），+0x24 个数；
//   利益集团对象：+0x08 侵入式引用计数（lock inc / dec），+0x10 利益集团 id；
// 玩家国家取自全局，然后组装 CReformGovernmentCommand（make_shared）交回给 Execute 发出。
// 所以这里自己构造一个只填了名单的对象（元素就是列表里取到的利益集团对象），
// 再照常 Execute(ReformGovernment.Confirm)，与玩家点「确认」同一条路。
namespace {

constexpr int kMaxGovernment = 16;
void* g_members[kMaxGovernment];
alignas(16) uint8_t g_reform[0x400];  // 伪造的 CReformGovernment，只用到名单字段

bool seh_read_int(const void* p, int* out) {
    __try {
        *out = *static_cast<const int*>(p);
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

}  // namespace

bool reform_government(const std::string& ig_list, const std::vector<int>& members, std::string* out,
                       std::string* error) {
    if (members.empty() || members.size() > kMaxGovernment) { *error = "政府成员个数不对"; return false; }
    Access access;
    std::vector<CtxEntry> items;
    AnyBuf any;
    Model m{};
    int size = 0;
    if (!open_model(ig_list, items, &any, &m, &size, error)) return false;
    *out = "[";
    for (size_t k = 0; k < members.size(); ++k) {
        int i = members[k];
        if (i < 0 || i >= size) { *error = "利益集团下标 " + std::to_string(i) + " 越界"; return false; }
        CtxEntry e{};
        if (!item_ctx(m, i, &e, error)) return false;
        int id = -1;
        if (!e.ptr || !seh_read_int(static_cast<uint8_t*>(e.ptr) + 0x10, &id)) { *error = "读不到利益集团 id"; return false; }
        g_members[k] = e.ptr;
        *out += (k ? "," : "") + std::to_string(id);
    }
    *out += "]";
    memset(g_reform, 0, sizeof g_reform);
    *reinterpret_cast<void***>(g_reform + 0x18) = g_members;
    *reinterpret_cast<int*>(g_reform + 0x20) = kMaxGovernment;
    *reinterpret_cast<int*>(g_reform + 0x24) = static_cast<int>(members.size());
    CtxEntry reform{g_reform, kAnyType, false, {}};
    return exec_in("Execute(ReformGovernment.Confirm)", &reform, 1, error);
}

}  // namespace datasys

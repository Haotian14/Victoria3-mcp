#include "trace.h"

#include <windows.h>
#include <tlhelp32.h>

#include <atomic>
#include <cstring>
#include <cstdio>
#include <mutex>
#include <vector>

namespace trace {
namespace {

struct Hit {
    DWORD tid;
    uint64_t regs[4];  // rcx rdx r8 r9
    uint64_t rsp;
    uint64_t stackq[8];  // 命中时栈顶 8 个 qword（第 5 个起的参数在 rsp+0x28 之后）
    std::vector<uint64_t> frames;
};

std::mutex g_mu;
std::vector<Hit> g_hits;
std::atomic<uint64_t> g_target{0};
std::atomic<int> g_remaining{0};
uint8_t* g_base = nullptr;

void unwind(CONTEXT ctx, std::vector<uint64_t>& out) {
    for (int i = 0; i < 24 && ctx.Rip; ++i) {
        out.push_back(ctx.Rip);
        DWORD64 image = 0;
        auto* fn = RtlLookupFunctionEntry(ctx.Rip, &image, nullptr);
        if (!fn) {  // 叶函数：返回地址就在栈顶
            ctx.Rip = *reinterpret_cast<DWORD64*>(ctx.Rsp);
            ctx.Rsp += 8;
            continue;
        }
        void* handler_data = nullptr;
        DWORD64 frame = 0;
        RtlVirtualUnwind(UNW_FLAG_NHANDLER, image, ctx.Rip, fn, &ctx, &handler_data, &frame, nullptr);
    }
}

LONG CALLBACK on_exception(EXCEPTION_POINTERS* ep) {
    if (ep->ExceptionRecord->ExceptionCode != EXCEPTION_SINGLE_STEP) return EXCEPTION_CONTINUE_SEARCH;
    CONTEXT* c = ep->ContextRecord;
    if (c->Rip != g_target.load() || g_target.load() == 0) return EXCEPTION_CONTINUE_SEARCH;
    if (g_remaining.fetch_sub(1) > 0) {
        Hit h{GetCurrentThreadId(), {c->Rcx, c->Rdx, c->R8, c->R9}, c->Rsp, {}, {}};
        memcpy(h.stackq, reinterpret_cast<void*>(c->Rsp), sizeof h.stackq);
        unwind(*c, h.frames);
        std::lock_guard<std::mutex> lock(g_mu);
        g_hits.push_back(std::move(h));
    } else {
        c->Dr7 &= ~1ull;  // 次数用完：本线程自己撤掉断点
    }
    c->EFlags |= 0x10000;  // RF：恢复执行时不再立刻触发同一个断点
    return EXCEPTION_CONTINUE_EXECUTION;
}

void set_all_threads(uint64_t addr) {
    DWORD self = GetCurrentThreadId();
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
    THREADENTRY32 te{sizeof te};
    for (BOOL ok = Thread32First(snap, &te); ok; ok = Thread32Next(snap, &te)) {
        if (te.th32OwnerProcessID != GetCurrentProcessId() || te.th32ThreadID == self) continue;
        HANDLE t = OpenThread(THREAD_GET_CONTEXT | THREAD_SET_CONTEXT | THREAD_SUSPEND_RESUME, FALSE, te.th32ThreadID);
        if (!t) continue;
        SuspendThread(t);
        CONTEXT c{};
        c.ContextFlags = CONTEXT_DEBUG_REGISTERS;
        if (GetThreadContext(t, &c)) {
            c.Dr0 = addr;
            c.Dr7 = addr ? ((c.Dr7 & ~0xF0003ull) | 1ull) : (c.Dr7 & ~1ull);  // L0，执行断点（RW0=00, LEN0=00）
            SetThreadContext(t, &c);
        }
        ResumeThread(t);
        CloseHandle(t);
    }
    CloseHandle(snap);
}

std::string hex64(uint64_t v) {
    char b[24];
    snprintf(b, sizeof b, "\"0x%llx\"", static_cast<unsigned long long>(v));
    return b;
}

std::string rel(uint64_t v) {
    auto m = reinterpret_cast<uint64_t>(g_base);
    if (v >= m && v < m + 0x10000000) return hex64(v - m);
    return "\"abs:" + hex64(v).substr(1);
}

}  // namespace

std::string run(uint8_t* module_base, uint64_t rva, int hits, unsigned timeout_ms) {
    static PVOID veh = AddVectoredExceptionHandler(1, on_exception);
    (void)veh;
    g_base = module_base;
    {
        std::lock_guard<std::mutex> lock(g_mu);
        g_hits.clear();
    }
    uint64_t addr = reinterpret_cast<uint64_t>(module_base) + rva;
    g_remaining = hits;
    g_target = addr;
    set_all_threads(addr);
    DWORD t0 = GetTickCount();
    while (GetTickCount() - t0 < timeout_ms) {
        {
            std::lock_guard<std::mutex> lock(g_mu);
            if (static_cast<int>(g_hits.size()) >= hits) break;
        }
        Sleep(20);
    }
    set_all_threads(0);
    g_target = 0;

    std::lock_guard<std::mutex> lock(g_mu);
    std::string o = "{\"ok\":true,\"hits\":[";
    for (size_t i = 0; i < g_hits.size(); ++i) {
        const Hit& h = g_hits[i];
        if (i) o += ",";
        o += "{\"tid\":" + std::to_string(h.tid) + ",\"rcx\":" + hex64(h.regs[0]) + ",\"rdx\":" + hex64(h.regs[1]) +
             ",\"r8\":" + hex64(h.regs[2]) + ",\"r9\":" + hex64(h.regs[3]) + ",\"rsp\":" + hex64(h.rsp) + ",\"stackq\":[";
        for (int k = 0; k < 8; ++k) o += (k ? "," : "") + hex64(h.stackq[k]);
        o += "],\"stack\":[";
        for (size_t k = 0; k < h.frames.size(); ++k) o += (k ? "," : "") + rel(h.frames[k]);
        o += "]}";
    }
    o += "]}";
    return o;
}

std::string read_memory(uint64_t addr, size_t len) {
    if (len > 65536) len = 65536;
    std::vector<uint8_t> buf(len);
    SIZE_T got = 0;
    if (!ReadProcessMemory(GetCurrentProcess(), reinterpret_cast<void*>(addr), buf.data(), len, &got) || got == 0)
        return "{\"ok\":false,\"error\":\"地址不可读\"}";
    std::string o = "{\"ok\":true,\"hex\":\"";
    char b[4];
    for (SIZE_T i = 0; i < got; ++i) {
        snprintf(b, sizeof b, "%02x", buf[i]);
        o += b;
    }
    return o + "\"}";
}

}  // namespace trace

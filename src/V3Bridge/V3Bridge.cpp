// V3Bridge：注入 victoria3.exe 的桥接层。
//
// 在 127.0.0.1:8766 提供 HTTP 接口，把控制台命令放到游戏主线程执行：
//   GET  /health            存活状态、定位到的函数、主线程 id
//   POST /console?cmd=...   执行一条控制台命令，返回 {ok, output, ms}
//
// 控制台的执行路径（1.13.11 逆向，见 docs/bridge.md）：
//   控制台输入框 → Console::Execute(this, const std::string&)
//     写 console_history.txt，打日志 "Running console command: {}"，按空格切分参数，然后
//     CommandManager::Get()->Execute(&result, &tokens)   ← 本文件直接调用这一层
// 两个函数都按字符串交叉引用 + 调用序列特征码定位，不写死地址。
//
// 主线程：子类化游戏主窗口的 WndProc，HTTP 线程用 SendMessageTimeout 把任务投递过去，
// 窗口过程在创建窗口的线程（即游戏主线程 / UI 线程）里执行，和玩家在控制台里敲命令同一个线程。

#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>

#include <atomic>
#include <chrono>
#include <cstdarg>
#include <cstddef>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "datasys.h"
#include "scan.h"
#include "trace.h"

#pragma comment(lib, "ws2_32.lib")

namespace {

// ---------------------------------------------------------------- 游戏侧数据结构
// MSVC std::string：{ union { char buf[16]; char* ptr; }; size_t size; size_t cap; }，与游戏同一编译器
struct GameString {
    union { char buf[16]; char* ptr; };
    size_t size;
    size_t cap;
    const char* c_str() const { return cap > 15 ? ptr : buf; }
};
static_assert(sizeof(GameString) == 0x20, "std::string 布局与游戏不符");
static_assert(sizeof(std::string) == 0x20, "本 DLL 的 std::string 必须与游戏一致（Release、无迭代器调试）");

// Execute 的入参：Paradox 自家的动态数组 { T* data; int capacity; int size; Allocator* }
struct GameTokens {
    std::string* data;
    int capacity;
    int size;
    void* allocator;  // 只读路径不用，留空
};

// Execute 的出参：{ bool ok; std::string text; }
struct GameResult {
    bool ok;
    char pad[7];
    GameString text;
};
static_assert(offsetof(GameResult, text) == 8, "Result 布局与游戏不符");

using GetManagerFn = void* (*)();
using ExecuteFn = void (*)(void* mgr, GameResult* out, const GameTokens* args);

GetManagerFn g_get_manager = nullptr;
ExecuteFn g_execute = nullptr;
scan::Module g_mod;

HWND g_hwnd = nullptr;
WNDPROC g_orig_proc = nullptr;
DWORD g_main_tid = 0;
std::atomic<bool> g_ready{false};
std::string g_locate_error;

constexpr UINT WM_BRIDGE_JOB = WM_APP + 0x2A3;

// ---------------------------------------------------------------- 日志
std::string g_log_path;

void log(const char* fmt, ...) {
    char line[2048];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    SYSTEMTIME t;
    GetLocalTime(&t);
    if (FILE* f = fopen(g_log_path.c_str(), "a")) {
        fprintf(f, "%02d:%02d:%02d.%03d %s\n", t.wHour, t.wMinute, t.wSecond, t.wMilliseconds, line);
        fclose(f);
    }
}

std::string env(const char* name, const char* fallback) {
    char buf[1024];
    DWORD n = GetEnvironmentVariableA(name, buf, sizeof buf);
    return (n > 0 && n < sizeof buf) ? std::string(buf, n) : std::string(fallback);
}

// ---------------------------------------------------------------- 定位
bool locate() {
    g_mod = scan::main_module();
    if (!g_mod.text.begin || !g_mod.rdata.begin) {
        g_locate_error = "找不到 .text / .rdata 节";
        return false;
    }
    uint8_t* refs[8];

    // CommandManager::Execute：唯一引用 "Unknown command" 的函数
    uint8_t* s_unknown = scan::find_cstring(g_mod.rdata, "Unknown command");
    size_t n = s_unknown ? scan::find_lea_refs(g_mod.text, s_unknown, refs, 8) : 0;
    if (n != 1) {
        g_locate_error = "\"Unknown command\" 的引用数不是 1：" + std::to_string(n);
        return false;
    }
    uint8_t* execute = scan::function_start(refs[0]);

    // Console::Execute 里打完 "Running console command: {}" 之后紧跟：
    //   call CommandManager::Get
    //   lea r8, [rbp+tokens] ; lea rdx, [rbp+result] ; mov rcx, rax
    //   call CommandManager::Execute
    uint8_t* s_running = scan::find_cstring(g_mod.rdata, "Running console command: {}");
    n = s_running ? scan::find_lea_refs(g_mod.text, s_running, refs, 8) : 0;
    if (n != 1) {
        g_locate_error = "\"Running console command\" 的引用数不是 1：" + std::to_string(n);
        return false;
    }
    uint8_t* site = scan::find_pattern(refs[0], 0x200, "E8 ?? ?? ?? ?? 4C 8D 45 ?? 48 8D 55 ?? 48 8B C8 E8");
    if (!site) {
        g_locate_error = "Console::Execute 里找不到 Get → Execute 调用序列";
        return false;
    }
    uint8_t* get = scan::rel32_target(site, 1);
    uint8_t* exec2 = scan::rel32_target(site + 16, 1);
    if (exec2 != execute) {
        g_locate_error = "两条线索定位到的 Execute 不一致：" + scan::hex(exec2, g_mod.base) + " vs " +
                         scan::hex(execute, g_mod.base);
        return false;
    }
    g_get_manager = reinterpret_cast<GetManagerFn>(get);
    g_execute = reinterpret_cast<ExecuteFn>(execute);
    log("定位成功：CommandManager::Get=%s Execute=%s", scan::hex(get, g_mod.base).c_str(),
        scan::hex(execute, g_mod.base).c_str());
    std::string err;
    if (!datasys::locate(g_mod.base, &err)) log("数据系统定位失败：%s", err.c_str());
    return true;
}

// ---------------------------------------------------------------- 主线程执行
enum class JobKind { Console, Read, Exec, Call, Eval, List, Reform };

struct Job {
    JobKind kind = JobKind::Console;
    bool flag = false;      // /data/eval：CreateStatement 的第四个参数
    uint64_t call[5] = {};  // 开发用 /call：函数 rva 与四个参数
    std::string cmd;        // 命令 / 文本 / 语句
    std::vector<datasys::PathStep> path;  // 数据系统的上下文路径（p0/i0, p1/i1 ...）
    std::string list;                     // /data/list：要逐项求值的列表
    std::vector<std::string> fields;
    int limit = 0;
    std::vector<int> members;  // /gov/reform：改组后在朝的利益集团（list 里的下标）
    bool json = false;     // output 已经是 JSON（不再当字符串转义）
    bool ok = false;
    bool crashed = false;
    DWORD exception = 0;
    std::string output;
};

// 不能有需要析构的局部对象，才能用 __try
bool call_execute(void* mgr, GameResult* res, const GameTokens* tok, DWORD* code) {
    __try {
        g_execute(mgr, res, tok);
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        *code = GetExceptionCode();
        return false;
    }
}

void* call_get_manager(DWORD* code) {
    __try {
        return g_get_manager();
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        *code = GetExceptionCode();
        return nullptr;
    }
}

using Call4 = uint64_t (*)(uint64_t, uint64_t, uint64_t, uint64_t);

bool seh_call(uint64_t fn, const uint64_t* a, uint64_t* ret, DWORD* code) {
    __try {
        *ret = reinterpret_cast<Call4>(fn)(a[0], a[1], a[2], a[3]);
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        *code = GetExceptionCode();
        return false;
    }
}

std::string json_escape(const std::string& s);

void run_job(Job* job) {
    if (job->kind == JobKind::List) {
        std::vector<std::vector<std::string>> rows;
        std::string err;
        job->ok = datasys::list_read(job->path, job->list, job->fields, job->limit, &rows, &err);
        if (!job->ok) { job->output = err; return; }
        std::string o = "[";
        for (size_t r = 0; r < rows.size(); ++r) {
            o += r ? ",[" : "[";
            for (size_t c = 0; c < rows[r].size(); ++c) o += (c ? ",\"" : "\"") + json_escape(rows[r][c]) + "\"";
            o += "]";
        }
        job->output = o + "]";
        job->json = true;
        return;
    }
    if (job->kind == JobKind::Reform) {
        std::string ids, err;
        job->ok = datasys::reform_government(job->list, job->members, &ids, &err);
        job->output = job->ok ? ids : err;
        return;
    }
    if (job->kind == JobKind::Call) {
        uint64_t ret = 0;
        job->ok = seh_call(reinterpret_cast<uint64_t>(g_mod.base) + job->call[0], job->call + 1, &ret, &job->exception);
        char b[64];
        snprintf(b, sizeof b, job->ok ? "0x%llx" : "异常 0x%llx", job->ok ? ret : static_cast<unsigned long long>(job->exception));
        job->output = b;
        return;
    }
    if (job->kind == JobKind::Read) {
        std::string err;
        job->ok = datasys::read(job->path, job->cmd, &job->output, &err);
        if (!job->ok) job->output = err + (job->output.empty() ? "" : "：" + job->output);
        return;
    }
    if (job->kind == JobKind::Eval) {
        alignas(16) uint8_t any[0x40] = {};
        std::string err;
        job->ok = datasys::eval_raw(job->cmd, job->flag, any, &err);
        if (!job->ok) { job->output = err; return; }
        char b[4];
        for (uint8_t x : any) { snprintf(b, sizeof b, "%02x", x); job->output += b; }
        return;
    }
    if (job->kind == JobKind::Exec) {
        std::string err;
        job->ok = datasys::exec(job->path, job->cmd, &err);
        job->output = err;
        return;
    }
    // 与游戏控制台一致：按空格切分，第一个是命令名
    std::vector<std::string> tokens;
    size_t i = 0;
    const std::string& s = job->cmd;
    while (i < s.size()) {
        while (i < s.size() && s[i] == ' ') ++i;
        size_t j = i;
        while (j < s.size() && s[j] != ' ') ++j;
        if (j > i) tokens.emplace_back(s.substr(i, j - i));
        i = j;
    }
    if (tokens.empty()) {
        job->output = "空命令";
        return;
    }
    void* mgr = call_get_manager(&job->exception);
    if (!mgr) {
        job->crashed = true;
        job->output = "CommandManager::Get 失败";
        return;
    }
    GameTokens tok{tokens.data(), static_cast<int>(tokens.size()), static_cast<int>(tokens.size()), nullptr};
    // 出参由游戏写入；text 用游戏的分配器分配，这里不释放（每条命令泄漏几十字节，可接受）
    GameResult res{};
    if (!call_execute(mgr, &res, &tok, &job->exception)) {
        job->crashed = true;
        char buf[64];
        snprintf(buf, sizeof buf, "执行时异常 0x%08lX", job->exception);
        job->output = buf;
        return;
    }
    job->ok = res.ok;
    if (res.text.size < (1u << 24)) job->output.assign(res.text.c_str(), res.text.size);
}

LRESULT CALLBACK bridge_proc(HWND h, UINT msg, WPARAM wp, LPARAM lp) {
    if (msg == WM_BRIDGE_JOB) {
        run_job(reinterpret_cast<Job*>(lp));
        return 1;
    }
    return CallWindowProcW(g_orig_proc, h, msg, wp, lp);
}

BOOL CALLBACK pick_window(HWND h, LPARAM lp) {
    DWORD pid = 0;
    DWORD tid = GetWindowThreadProcessId(h, &pid);
    if (pid != GetCurrentProcessId() || !IsWindowVisible(h) || GetWindow(h, GW_OWNER)) return TRUE;
    RECT r;
    GetWindowRect(h, &r);
    long area = (r.right - r.left) * (r.bottom - r.top);
    auto* best = reinterpret_cast<std::pair<HWND, long>*>(lp);
    if (area > best->second) {
        *best = {h, area};
        g_main_tid = tid;
    }
    return TRUE;
}

bool hook_window() {
    // 游戏先弹启动画面再建主窗口：等到有足够大的可见顶层窗口
    for (int i = 0; i < 1200; ++i) {
        std::pair<HWND, long> best{nullptr, 0};
        EnumWindows(pick_window, reinterpret_cast<LPARAM>(&best));
        if (best.first && best.second >= 640 * 480) {
            g_hwnd = best.first;
            break;
        }
        Sleep(500);
    }
    if (!g_hwnd) return false;
    g_orig_proc = reinterpret_cast<WNDPROC>(
        SetWindowLongPtrW(g_hwnd, GWLP_WNDPROC, reinterpret_cast<LONG_PTR>(bridge_proc)));
    log("子类化主窗口 %p（线程 %lu）：%s", g_hwnd, g_main_tid, g_orig_proc ? "成功" : "失败");
    return g_orig_proc != nullptr;
}

bool post_job(Job* job, DWORD timeout_ms) {
    // 超时后消息不会被撤回，主线程稍后仍可能执行它 —— 所以 Job 必须在堆上，超时就不释放
    DWORD_PTR r = 0;
    return SendMessageTimeoutW(g_hwnd, WM_BRIDGE_JOB, 0, reinterpret_cast<LPARAM>(job),
                               SMTO_NORMAL, timeout_ms, &r) != 0 && r == 1;
}

// ---------------------------------------------------------------- HTTP
std::string json_escape(const std::string& s) {
    std::string o;
    o.reserve(s.size() + 8);
    for (size_t i = 0; i < s.size(); ++i) {
        unsigned char c = static_cast<unsigned char>(s[i]);
        switch (c) {
            case '"': o += "\\\""; continue;
            case '\\': o += "\\\\"; continue;
            case '\n': o += "\\n"; continue;
            case '\r': o += "\\r"; continue;
            case '\t': o += "\\t"; continue;
        }
        if (c < 0x20) {
            char b[8];
            snprintf(b, sizeof b, "\\u%04x", c);
            o += b;
            continue;
        }
        if (c < 0x80) { o += static_cast<char>(c); continue; }
        // 只放行合法 UTF-8；坏字节转成 \u00XX，免得客户端整条 JSON 解不开
        int len = (c >> 5) == 0x6 ? 2 : (c >> 4) == 0xE ? 3 : (c >> 3) == 0x1E ? 4 : 0;
        bool good = len > 0 && i + len <= s.size();
        for (int k = 1; good && k < len; ++k) good = (static_cast<unsigned char>(s[i + k]) >> 6) == 0x2;
        if (good) {
            o.append(s, i, len);
            i += len - 1;
        } else {
            char b[8];
            snprintf(b, sizeof b, "\\u%04x", c);
            o += b;
        }
    }
    return o;
}

std::string url_decode(const std::string& s) {
    std::string o;
    for (size_t i = 0; i < s.size(); ++i) {
        if (s[i] == '+') o += ' ';
        else if (s[i] == '%' && i + 2 < s.size()) {
            o += static_cast<char>(strtol(s.substr(i + 1, 2).c_str(), nullptr, 16));
            i += 2;
        } else o += s[i];
    }
    return o;
}

std::string query_param(const std::string& query, const char* key) {
    std::string k = std::string(key) + "=";
    size_t pos = 0;
    while (pos <= query.size()) {
        size_t amp = query.find('&', pos);
        std::string part = query.substr(pos, amp == std::string::npos ? std::string::npos : amp - pos);
        if (part.compare(0, k.size(), k) == 0) return url_decode(part.substr(k.size()));
        if (amp == std::string::npos) break;
        pos = amp + 1;
    }
    return {};
}

void send_json(SOCKET c, int status, const std::string& body) {
    std::string head = "HTTP/1.1 " + std::to_string(status) + (status == 200 ? " OK" : " Error") +
                       "\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: " +
                       std::to_string(body.size()) + "\r\nConnection: close\r\n\r\n";
    std::string all = head + body;
    send(c, all.data(), static_cast<int>(all.size()), 0);
}

std::string health_json() {
    char buf[512];
    snprintf(buf, sizeof buf,
             "{\"ok\":%s,\"pid\":%lu,\"main_thread\":%lu,\"hwnd\":\"%p\",\"base\":\"%p\",\"get_manager\":\"%s\","
             "\"execute\":\"%s\",\"error\":\"%s\"}",
             g_ready ? "true" : "false", GetCurrentProcessId(), g_main_tid, g_hwnd, g_mod.base,
             g_get_manager ? scan::hex(reinterpret_cast<void*>(g_get_manager), g_mod.base).c_str() : "",
             g_execute ? scan::hex(reinterpret_cast<void*>(g_execute), g_mod.base).c_str() : "",
             json_escape(g_locate_error).c_str());
    std::string h = buf;
    h.pop_back();
    return h + ",\"datasys\":" + datasys::describe() + "}";
}

void handle(SOCKET c) {
    std::string req;
    char buf[8192];
    size_t header_end = std::string::npos;
    while (header_end == std::string::npos) {
        int n = recv(c, buf, sizeof buf, 0);
        if (n <= 0) return;
        req.append(buf, n);
        header_end = req.find("\r\n\r\n");
        if (req.size() > (1 << 20)) return;
    }
    // 读完 body（cmd 也可以放在 body 里，免得命令太长超出 URL 限制）
    size_t content_length = 0;
    for (const char* name : {"Content-Length:", "content-length:"}) {
        size_t cl = req.find(name);
        if (cl != std::string::npos && cl < header_end) content_length = strtoul(req.c_str() + cl + 15, nullptr, 10);
    }
    while (req.size() < header_end + 4 + content_length) {
        int n = recv(c, buf, sizeof buf, 0);
        if (n <= 0) break;
        req.append(buf, n);
    }
    std::string body = req.substr(header_end + 4);

    size_t sp1 = req.find(' ');
    size_t sp2 = req.find(' ', sp1 + 1);
    std::string target = req.substr(sp1 + 1, sp2 - sp1 - 1);
    size_t q = target.find('?');
    std::string path = target.substr(0, q);
    std::string query = q == std::string::npos ? "" : target.substr(q + 1);

    if (path == "/health") {
        send_json(c, 200, health_json());
        return;
    }
    // 开发用：硬件断点抓调用栈、读内存（逆向游戏内部函数时用，正常游玩不需要）
    if (path == "/trace") {
        uint64_t rva = strtoull(query_param(query, "rva").c_str(), nullptr, 16);
        int hits = atoi(query_param(query, "hits").c_str());
        unsigned ms = strtoul(query_param(query, "ms").c_str(), nullptr, 10);
        send_json(c, 200, trace::run(g_mod.base, rva, hits > 0 ? hits : 1, ms > 0 ? ms : 5000));
        return;
    }
    if (path == "/mem") {
        std::string a = query_param(query, "addr");
        uint64_t addr = a.rfind("rva:", 0) == 0
                            ? reinterpret_cast<uint64_t>(g_mod.base) + strtoull(a.c_str() + 4, nullptr, 16)
                            : strtoull(a.c_str(), nullptr, 16);
        size_t len = strtoul(query_param(query, "len").c_str(), nullptr, 10);
        send_json(c, 200, trace::read_memory(addr, len ? len : 64));
        return;
    }
    // /console?cmd=  控制台命令；/data/read?text=  按本地化文本求值；/data/exec?stmt=  执行语句
    if (path == "/console" || path == "/data/read" || path == "/data/exec" || path == "/call" ||
        path == "/data/eval" || path == "/data/list" || path == "/gov/reform") {
        if (!g_ready) {
            send_json(c, 503, "{\"ok\":false,\"error\":\"桥接层未就绪\",\"health\":" + health_json() + "}");
            return;
        }
        auto* job = new Job;
        const char* key = path == "/console" ? "cmd" : path == "/data/read" ? "text" : "stmt";
        if (path == "/data/eval") job->kind = JobKind::Eval;
        if (path == "/data/list") {
            // list=列表语句；fields=以  分隔的若干段文本
            job->kind = JobKind::List;
            job->list = query_param(query, "list");
            if (job->list.empty()) job->list = query_param(body, "list");
            std::string f = query_param(query, "fields");
            if (f.empty()) f = query_param(body, "fields");
            for (size_t a = 0, b; a <= f.size(); a = b + 1) {
                b = f.find('', a);
                if (b == std::string::npos) b = f.size();
                if (b > a) job->fields.push_back(f.substr(a, b - a));
            }
            job->limit = atoi(query_param(query, "limit").c_str());
        }
        if (path == "/gov/reform") {
            // list=利益集团列表语句；igs=逗号分隔的下标（改组后的全部在朝集团）
            job->kind = JobKind::Reform;
            job->list = query_param(query, "list");
            std::string igs = query_param(query, "igs");
            for (size_t a = 0, b; a < igs.size(); a = b + 1) {
                b = igs.find(',', a);
                if (b == std::string::npos) b = igs.size();
                if (b > a) job->members.push_back(atoi(igs.substr(a, b - a).c_str()));
            }
            job->cmd = "reform " + igs;
        }
        // 上下文路径：p0=列表&i0=下标&p1=...，按顺序逐层取项（/gov/reform 不用）
        for (int k = 0; k < 8; ++k) {
            std::string pk = "p" + std::to_string(k), ik = "i" + std::to_string(k);
            std::string lp = query_param(query, pk.c_str());
            if (lp.empty()) lp = query_param(body, pk.c_str());
            if (lp.empty()) break;
            std::string ip = query_param(query, ik.c_str());
            if (ip.empty()) ip = query_param(body, ik.c_str());
            job->path.push_back({lp, atoi(ip.c_str())});
        }
        if (job->kind == JobKind::Console || job->kind == JobKind::Read || job->kind == JobKind::Exec ||
            job->kind == JobKind::Call)
            job->kind = path == "/console" ? JobKind::Console : path == "/data/read" ? JobKind::Read
                      : path == "/data/exec" ? JobKind::Exec : JobKind::Call;
        if (job->kind == JobKind::Call) {  // 开发用：在主线程调用 base+rva(a1..a4)
            job->call[0] = strtoull(query_param(query, "rva").c_str(), nullptr, 16);
            const char* names[] = {"a1", "a2", "a3", "a4"};
            for (int i = 0; i < 4; ++i) job->call[i + 1] = strtoull(query_param(query, names[i]).c_str(), nullptr, 0);
            key = "rva";
        }
        job->cmd = query_param(query, key);
        job->flag = query_param(query, "flag") == "1";
        if (job->cmd.empty()) job->cmd = query_param(body, key);
        if (job->cmd.empty() && job->kind != JobKind::List && body.find('=') == std::string::npos) job->cmd = body;
        DWORD timeout = 60000;
        std::string t = query_param(query, "timeout");
        if (!t.empty()) timeout = strtoul(t.c_str(), nullptr, 10);
        auto t0 = std::chrono::steady_clock::now();
        bool delivered = post_job(job, timeout);
        long long ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                           std::chrono::steady_clock::now() - t0).count();
        log("console %s → delivered=%d ok=%d %lldms", job->cmd.c_str(), delivered, job->ok, ms);
        if (!delivered) {
            send_json(c, 200, "{\"ok\":false,\"error\":\"主线程 " + std::to_string(timeout) +
                                  " 毫秒内没有处理（游戏在加载或卡住），命令稍后仍可能执行\",\"cmd\":\"" +
                                  json_escape(job->cmd) + "\"}");
            return;  // 故意不 delete：主线程稍后可能还会写它
        }
        std::string out = "{\"ok\":" + std::string(job->ok ? "true" : "false") +
                          ",\"crashed\":" + (job->crashed ? "true" : "false") +
                          ",\"cmd\":\"" + json_escape(job->cmd) + "\",\"output\":" +
                          (job->json ? job->output : "\"" + json_escape(job->output) + "\"") +
                          ",\"ms\":" + std::to_string(ms) + "}";
        delete job;
        send_json(c, 200, out);
        return;
    }
    send_json(c, 404, "{\"ok\":false,\"error\":\"未知路径\",\"path\":\"" + json_escape(path) + "\"}");
}

DWORD WINAPI serve_connection(LPVOID p) {
    SOCKET c = reinterpret_cast<SOCKET>(p);
    handle(c);
    shutdown(c, SD_SEND);
    closesocket(c);
    return 0;
}

DWORD WINAPI wait_window(LPVOID) {
    if (g_execute && hook_window()) g_ready = true;
    else if (g_locate_error.empty()) g_locate_error = "等不到游戏主窗口";
    return 0;
}

DWORD WINAPI server_main(LPVOID) {
    g_log_path = env("V3MCP_BRIDGE_LOG", "");
    if (g_log_path.empty()) {
        char tmp[MAX_PATH];
        GetTempPathA(MAX_PATH, tmp);
        g_log_path = std::string(tmp) + "V3Bridge.log";
    }
    log("V3Bridge 加载，pid %lu", GetCurrentProcessId());

    if (!locate()) log("定位失败：%s", g_locate_error.c_str());

    WSADATA wsa;
    WSAStartup(MAKEWORD(2, 2), &wsa);
    SOCKET ls = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(static_cast<u_short>(atoi(env("V3MCP_PORT", "8766").c_str())));
    inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);
    BOOL yes = TRUE;
    setsockopt(ls, SOL_SOCKET, SO_EXCLUSIVEADDRUSE, reinterpret_cast<const char*>(&yes), sizeof yes);
    if (bind(ls, reinterpret_cast<sockaddr*>(&addr), sizeof addr) != 0 || listen(ls, 8) != 0) {
        log("监听失败：%d", WSAGetLastError());
        return 1;
    }
    log("监听 127.0.0.1:%d", ntohs(addr.sin_port));

    // 窗口在 HTTP 起来之后再等：加载期间 /health 也能回应，便于启动脚本判断进度
    CreateThread(nullptr, 0, wait_window, nullptr, 0, nullptr);

    // 每个连接一个线程：/trace 会阻塞等待命中，期间仍要能接受别的请求。
    // 游戏侧的任务都经 SendMessage 投递到主线程，天然串行，不需要另加锁。
    for (;;) {
        SOCKET c = accept(ls, nullptr, nullptr);
        if (c == INVALID_SOCKET) continue;
        DWORD tv = 120000;
        setsockopt(c, SOL_SOCKET, SO_RCVTIMEO, reinterpret_cast<const char*>(&tv), sizeof tv);
        HANDLE t = CreateThread(nullptr, 0, serve_connection, reinterpret_cast<LPVOID>(c), 0, nullptr);
        if (t) CloseHandle(t);
        else serve_connection(reinterpret_cast<LPVOID>(c));
    }
}

}  // namespace

BOOL APIENTRY DllMain(HMODULE mod, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(mod);
        // 不能在 DllMain 里做重活（加载器锁），另起线程
        CreateThread(nullptr, 0, server_main, nullptr, 0, nullptr);
    }
    return TRUE;
}

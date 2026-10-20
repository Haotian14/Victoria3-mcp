#include "scan.h"

#include <windows.h>

#include <cstdio>
#include <cstring>
#include <vector>

namespace scan {

Module main_module() {
    Module m;
    m.base = reinterpret_cast<uint8_t*>(GetModuleHandleW(nullptr));
    auto* dos = reinterpret_cast<IMAGE_DOS_HEADER*>(m.base);
    auto* nt = reinterpret_cast<IMAGE_NT_HEADERS64*>(m.base + dos->e_lfanew);
    auto* sec = IMAGE_FIRST_SECTION(nt);
    for (WORD i = 0; i < nt->FileHeader.NumberOfSections; ++i, ++sec) {
        char name[9] = {};
        memcpy(name, sec->Name, 8);
        Section s{m.base + sec->VirtualAddress, sec->Misc.VirtualSize};
        if (strcmp(name, ".text") == 0) m.text = s;
        else if (strcmp(name, ".rdata") == 0) m.rdata = s;
        else if (strcmp(name, ".data") == 0) m.data = s;
    }
    return m;
}

uint8_t* find_cstring(const Section& sec, const char* s) {
    size_t n = strlen(s) + 1;  // 连同结尾的 \0 一起比
    uint8_t* end = sec.begin + sec.size - n;
    for (uint8_t* p = sec.begin + 1; p < end; ++p) {
        if (*p == static_cast<uint8_t>(s[0]) && p[-1] == 0 && memcmp(p, s, n) == 0) return p;
    }
    return nullptr;
}

size_t find_lea_refs(const Section& text, const uint8_t* target, uint8_t** out, size_t max_out) {
    size_t found = 0;
    uint8_t* end = text.begin + text.size - 7;
    for (uint8_t* p = text.begin; p < end; ++p) {
        // REX.W(48 / 4C) 8D modrm，mod=00 rm=101 即 rip 相对寻址
        if ((p[0] != 0x48 && p[0] != 0x4C) || p[1] != 0x8D || (p[2] & 0xC7) != 0x05) continue;
        int32_t disp = *reinterpret_cast<int32_t*>(p + 3);
        if (p + 7 + disp == target) {
            if (found < max_out) out[found] = p;
            ++found;
        }
    }
    return found;
}

uint8_t* find_pattern(uint8_t* begin, size_t size, const char* pattern) {
    std::vector<int> bytes;  // -1 = 通配
    for (const char* c = pattern; *c;) {
        if (*c == ' ') { ++c; continue; }
        if (c[0] == '?') {
            bytes.push_back(-1);
            c += (c[1] == '?') ? 2 : 1;
            continue;
        }
        bytes.push_back(static_cast<int>(strtoul(std::string(c, 2).c_str(), nullptr, 16)));
        c += 2;
    }
    if (bytes.empty() || size < bytes.size()) return nullptr;
    for (size_t i = 0; i + bytes.size() <= size; ++i) {
        size_t j = 0;
        for (; j < bytes.size(); ++j) {
            if (bytes[j] >= 0 && begin[i + j] != static_cast<uint8_t>(bytes[j])) break;
        }
        if (j == bytes.size()) return begin + i;
    }
    return nullptr;
}

uint8_t* find_vtable(const Module& m, const char* mangled, uint32_t offset) {
    uint8_t* name = find_cstring(m.data, mangled);
    if (!name) return nullptr;
    uint32_t td = static_cast<uint32_t>(name - 0x10 - m.base);
    // 完整对象定位器：{ 签名 1, 偏移, 构造偏移, 类型描述符 rva, 层次 rva, 自身 rva }
    for (uint8_t* p = m.rdata.begin; p + 24 <= m.rdata.begin + m.rdata.size; p += 4) {
        auto* col = reinterpret_cast<uint32_t*>(p);
        if (col[3] != td || col[0] != 1 || col[1] != offset || col[5] != static_cast<uint32_t>(p - m.base)) continue;
        uint64_t va = reinterpret_cast<uint64_t>(p);
        for (uint8_t* q = m.rdata.begin; q + 16 <= m.rdata.begin + m.rdata.size; q += 8) {
            if (*reinterpret_cast<uint64_t*>(q) == va) return q + 8;
        }
    }
    return nullptr;
}

uint8_t* function_start(uint8_t* addr) {
    DWORD64 image = 0;
    auto* fn = RtlLookupFunctionEntry(reinterpret_cast<DWORD64>(addr), &image, nullptr);
    // 函数被编译器拆成多段时，后面的段带 UNW_FLAG_CHAININFO，指回上一段，一直跟到头
    for (int guard = 0; fn && guard < 16; ++guard) {
        auto* info = reinterpret_cast<uint8_t*>(image + fn->UnwindInfoAddress);
        uint8_t flags = info[0] >> 3;
        if (!(flags & UNW_FLAG_CHAININFO)) break;
        uint8_t count = info[2];
        fn = reinterpret_cast<RUNTIME_FUNCTION*>(info + 4 + ((count + 1) & ~1) * 2);
    }
    return fn ? reinterpret_cast<uint8_t*>(image + fn->BeginAddress) : nullptr;
}

std::string hex(const void* p, const void* base) {
    char buf[32];
    snprintf(buf, sizeof buf, "0x%llx",
             static_cast<unsigned long long>(reinterpret_cast<const uint8_t*>(p) -
                                             reinterpret_cast<const uint8_t*>(base)));
    return buf;
}

}  // namespace scan

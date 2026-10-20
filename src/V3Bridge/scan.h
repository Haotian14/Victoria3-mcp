// 在游戏主模块里按「字符串 → 交叉引用 → 特征码」定位函数，不写死任何地址。
// 游戏小版本更新后地址会变，但字符串与调用序列通常不变。
#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

namespace scan {

struct Section {
    uint8_t* begin = nullptr;
    size_t size = 0;
};

struct Module {
    uint8_t* base = nullptr;
    Section text;    // 代码
    Section rdata;   // 只读数据（字符串常量）
};

Module main_module();

// 找以 \0 结尾的完整字符串（前一个字节也必须是 \0，避免命中更长字符串的尾部）
uint8_t* find_cstring(const Section& sec, const char* s);

// .text 里所有 `lea r64, [rip+disp32]` 指向 target 的指令地址
size_t find_lea_refs(const Section& text, const uint8_t* target, uint8_t** out, size_t max_out);

// 带通配符的字节特征码，如 "E8 ?? ?? ?? ?? 4C 8D 45 ??"
uint8_t* find_pattern(uint8_t* begin, size_t size, const char* pattern);

// rel32 跳转 / 调用的目标
inline uint8_t* rel32_target(uint8_t* ins, size_t opcode_len) {
    int32_t rel = *reinterpret_cast<int32_t*>(ins + opcode_len);
    return ins + opcode_len + 4 + rel;
}

// 用 .pdata（异常展开表）找所在函数的入口，跟随链式展开信息回到真正的起点
uint8_t* function_start(uint8_t* addr);

std::string hex(const void* p, const void* base);

}  // namespace scan

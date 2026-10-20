// 开发用的逆向工具：硬件断点抓调用栈、读进程内存。不参与正常游玩。
#pragma once

#include <cstdint>
#include <string>

namespace trace {

// 在 base+rva 设执行断点（所有线程的 DR0），命中 hits 次或超时后撤掉。
// 返回 JSON：每次命中的线程、rcx/rdx/r8/r9 与调用栈（相对模块基址）。
std::string run(uint8_t* module_base, uint64_t rva, int hits, unsigned timeout_ms);

// 读内存，返回 JSON：十六进制字节；地址不可读时 ok=false
std::string read_memory(uint64_t addr, size_t len);

}  // namespace trace

// 游戏数据系统（Jomini PdxData）：界面上 "[GetPlayer.GetName]"、onclick = "[Execute(...)]"
// 用的同一套表达式。读状态与下发玩家动作都走这里，等同于玩家在界面上看与点。
// 必须在游戏主线程调用。
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace datasys {

// 按特征码定位所需的游戏函数；失败时返回原因
bool locate(uint8_t* base, std::string* error);
bool ready();
std::string describe();  // 定位结果（JSON）

// 按本地化文本求值："[GetMetaPlayer.GetPlayedOrObservedCountry.GetGDP|2]" → "108499851.86"。
// 可混排普通文字与多个 [..]
bool read(const std::string& text, std::string* out, std::string* error);

// 执行一条语句（不带方括号），与界面 onclick 同一条路径，如 "TimeKeeper.TogglePause"
bool exec(const std::string& statement, std::string* error);

// 开发用：按值求值一条语句，原样返回 CPdxAny（0x40 字节）。flag 同 CreateStatement 的第四个参数
bool eval_raw(const std::string& statement, bool flag, uint8_t* any_out, std::string* error);

// 列表：list 是返回数据模型的语句（界面 datamodel 用的那种），每一项作为上下文，
// 依次求出 fields 里每段文本（每段只能有一个需要上下文的 [..]，如 "[Technology.GetName]"）
bool list_read(const std::string& list, const std::vector<std::string>& fields, int limit,
               std::vector<std::vector<std::string>>* rows, std::string* error);

// 在列表第 index 项的上下文里执行 statement；check 非空时先核对该项的 check 文本等于 expect
bool list_exec(const std::string& list, int index, const std::string& check, const std::string& expect,
               const std::string& statement, std::string* error);

}  // namespace datasys

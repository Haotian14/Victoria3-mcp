// 游戏数据系统（Jomini PdxData）：界面上 "[GetPlayer.GetName]"、onclick = "[Execute(...)]"
// 用的同一套表达式。读状态与下发玩家动作都走这里，等同于玩家在界面上看与点。
// 必须在游戏主线程调用。
#pragma once

#include <cstdint>
#include <string>

namespace datasys {

// 定位所需的游戏函数；失败时返回原因
bool locate(uint8_t* base, std::string* error);
bool ready();
std::string describe();  // 定位结果（JSON 片段）

// 按本地化文本求值："[GetPlayer.GetName]" → "大清"。可混排普通文字与多个 [..]
bool read(const std::string& text, std::string* out, std::string* error);

// 执行一条语句（不带方括号），如 "Execute(GetPlayer.SetTaxLevelHigh)"
bool exec(const std::string& statement, bool flag, std::string* error);

}  // namespace datasys

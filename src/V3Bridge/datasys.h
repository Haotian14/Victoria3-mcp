// 游戏数据系统（Jomini PdxData）：界面上 "[GetPlayer.GetName]"、onclick = "[Execute(...)]"
// 用的同一套表达式。读状态与下发玩家动作都走这里，等同于玩家在界面上看与点。
// 必须在游戏主线程调用。
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace datasys {

// 上下文路径的一步：对 list 求值（界面 datamodel 用的那种列表），取第 index 项作为上下文。
// 例：{AccessMetaPlayer.AccessPlayedOrObservedCountry.AccessStates, 3}, {State.GetPotentialUrbanBuildings, 0}
// 之后的表达式里就能用 State 与 Building。
struct PathStep {
    std::string list;
    int index;
};

// 按特征码定位所需的游戏函数；失败时返回原因
bool locate(uint8_t* base, std::string* error);
bool ready();
std::string describe();  // 定位结果（JSON）

// 按本地化文本求值："[GetMetaPlayer.GetPlayedOrObservedCountry.GetGDP|2]" → "108499851.86"。
// 可混排普通文字与多个 [..]；带路径时只能有一个需要上下文的 [..]
bool read(const std::vector<PathStep>& path, const std::string& text, std::string* out, std::string* error);

// 执行一条语句（不带方括号），与界面 onclick 同一条路径，如 "Execute(Building.QueueConstruction)"
bool exec(const std::vector<PathStep>& path, const std::string& statement, std::string* error);

// 开发用：按值求值一条语句，原样返回 CPdxAny（0x40 字节）。flag 同 CreateStatement 的第四个参数
bool eval_raw(const std::string& statement, bool flag, uint8_t* any_out, std::string* error);

// 列表逐项求值：沿 path 取好上下文后对 list 求值，每一项再求 fields 里每段文本
bool list_read(const std::vector<PathStep>& path, const std::string& list, const std::vector<std::string>& fields,
               int limit, std::vector<std::vector<std::string>>* rows, std::string* error);

// 改组政府：members 是 ig_list（玩家国家的利益集团列表）里的下标，即改组后的全部在朝集团。
// 走 Execute(ReformGovernment.Confirm)，与玩家在政治面板点「确认」同一条命令。out 返回各集团 id
bool reform_government(const std::string& ig_list, const std::vector<int>& members, std::string* out,
                       std::string* error);

// 伪造界面对象：界面窗口里的对象（事件窗口、草稿……）从玩家国家走不到，就照游戏回调读的字段
// 自己填几块缓冲区，0 号缓冲区作为通配上下文（顶替任何没配上的需求），接在 path 的各项之后。
// spec 以 ; 分隔，每项「缓冲区:偏移(十六进制):类型=值」，类型 b/i/q（1/4/8 字节）或 a（空 CPdxArray，值忽略），值取
//   十进制整数 | bN（N 号缓冲区地址）| cK（路径第 K 项对象指针）| cK@偏移（该对象偏移处的 int32）。
// 例（事件选项）："0:0:q=b1;0:8:i=2;1:88:q=b2;2:10:i=12345"。
// mode：'x' 执行语句 text（out 返回各 cK / cK@偏移 的实际取值）；'r' 求文本 text；'l' 列表 text 逐项求 fields
bool fake_call(const std::vector<PathStep>& path, const std::string& spec, char mode, const std::string& text,
               const std::vector<std::string>& fields, std::string* out, std::vector<std::vector<std::string>>* rows,
               std::string* error);

// 全部进行中的事件（含没有分类、只以弹窗 / 地图标记出现的）：数据系统没有这样的列表，
// 直接遍历游戏的事件对象库，每个事件作为上下文求 fields。每行第一格是事件 id（选项命令要用）
bool list_events(const std::vector<std::string>& fields, std::vector<std::vector<std::string>>* rows,
                 std::string* error);

}  // namespace datasys

# smart_home

自己搭的智能家居：灯光控制，以及卧室的"模拟日出"唤醒（灯 + 电动卷帘）。控制器用 Python，设备之间通过 MQTT 通信；现在由仿真器代替硬件，以后换成 ESP32 节点。

## 架构

```
控制器 (Python)  <──MQTT──>  Mosquitto  <──MQTT──>  节点（现在是仿真器，以后是 ESP32）
```

- 节点只负责上报传感器、执行命令，不含逻辑；所有逻辑都在控制器里。
- 仿真节点和真实节点使用同一套主题约定（见 [src/smarthome/protocol.py](src/smarthome/protocol.py)），换硬件时控制器不用改。
- 房间逻辑是纯状态机（[room.py](src/smarthome/controller/room.py)、[bedroom.py](src/smarthome/controller/bedroom.py)），不依赖 MQTT，可以直接做单元测试。

| 主题 | 方向 | 内容 |
|---|---|---|
| `home/<room>/motion` | 节点 → 控制器 | `{"occupied": bool}` |
| `home/<room>/lux` | 节点 → 控制器 | `{"lux": float}` |
| `home/outdoor/lux` | 节点 → 控制器 | `{"lux": float}`，装在卷帘外侧 |
| `home/<room>/light/set` | 控制器 → 节点 | `{"on": bool, "brightness": 0-255, "kelvin": int}` |
| `home/<room>/light/state` | 节点 → 控制器 | 同上（retained） |
| `home/<room>/shutter/set` | 控制器 → 节点 | `{"position": 0-100}`，0 = 关 |
| `home/<room>/shutter/state` | 节点 → 控制器 | `{"position": 0-100, "moving": bool}`（retained） |
| `home/<room>/button` | 用户 → 控制器 | `{"action": "goodnight"}`：床头按钮或手机快捷指令 |
| `home/<room>/alarm/config` | 用户 → 控制器 | `{"time": "07:00", "enabled": bool, ...}`（retained） |
| `home/<room>/alarm/event` | 用户 → 控制器 | `{"type": "stopped"}`：手机闹钟被关掉 |
| `sim/time` | 仿真器 → 全部 | `{"t": unix 秒}`，仅在仿真时间下使用 |
| `sim/occupant` | 仿真器 → 渲染页 | `{"room": ..., "asleep": bool}`，真值，控制器不能读 |
| `sim/ambient` | 仿真器 → 渲染页 | `{"outdoor": lx, "rooms": {...}}`，真值，控制器不能读 |

## 卧室：睡眠模式与模拟日出

- **晚安**（按钮）→ 关灯、关卷帘，夜里的动静不再触发卧室灯。
- **唤醒**：闹钟前 30 分钟开始，床头照度从 0 按指数曲线升到 250 lx，色温从 2000K 升到 4500K。
- **灯和卷帘的分工**：根据室外照度和在线学习的增益，估算"卷帘全开时床头能有多少自然光"，卷帘开到刚好够用，灯补足剩下的部分（用床头照度做反馈）。外面太暗就不开卷帘。日出过程中卷帘**只开不关、每次至少一档（10%）**，避免电机来回抖动；云层造成的波动交给灯来补偿。
- **结束**：闹钟被关掉（或闹钟后 30 分钟）→ 卷帘全开，回到普通模式。

## 安装

```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
```

## 运行

**离线仿真**（单进程，不需要 MQTT，一天约 5–10 秒）：

```powershell
.venv\Scripts\python -m smarthome.offline --hours 24 --seed 0 -v
.venv\Scripts\python -m smarthome.offline --start "2026-03-20 06:00" --hours 2 --status-every 120 -v   # 春分的早上
.venv\Scripts\python -m smarthome.offline --start "2026-12-21 00:00" --hours 9 --no-wake               # 只有闹钟，对比用
```

**通过 MQTT 运行**（和以后接真实硬件时的结构一样）：

```powershell
docker compose up -d                                          # 启动 Mosquitto
.venv\Scripts\python -m smarthome.controller --sim-clock      # 终端 1
.venv\Scripts\python -m smarthome.sim --speed 30 --start "2026-03-20 06:00" --hours 2   # 终端 2
```

`--speed 30` 表示 1 秒现实时间对应 30 秒仿真时间。

**3D 渲染**：用浏览器直接打开 [web/index.html](web/index.html)（双击即可），它通过 WebSocket（`ws://localhost:9001`）连接 Mosquitto，显示户型、灯光（含色温）、卧室卷帘、自然光和住户。页面只订阅、不发命令，所以不影响控制逻辑。

**测试**：

```powershell
.venv\Scripts\python -m pytest
```

## 指标

仿真结束时输出：

- 每个房间：`lights on` 开灯次数，`wasted min` 灯亮着但没人的时间，`dark min` 有人（不在床上）、偏暗、但灯没开的时间
- 睡眠：夜间醒来次数、睡着时卧室灯亮着的时间、卷帘电机启动次数
- 每天早上：几点醒、比闹钟早几分钟、被什么唤醒（光 / 自然醒 / 闹钟）、醒来前处于哪个睡眠阶段、床头照度

## 仿真模型

- **住户**：按工作日作息随机生成路线，所有房间经由走廊连通。睡前按"晚安"，闹钟后几分钟起床。
- **太阳**：按日期和经纬度（默认慕尼黑）计算太阳高度，含晨昏蒙影，乘以随时间漂移的云量。冬至 7:00 外面几乎全黑，夏至 5 点多就已经很亮。
- **采光**：室内照度 = 室外照度 × 窗户系数；卧室再乘以卷帘透光率（关闭时仍有 2% 从缝隙透进来）。
- **卷帘**：Rollladen，全程 20 秒匀速。真实的 ESP32 节点需要靠运行时间推算位置，在端点处重新校零。
- **睡眠**：约 90 分钟一个周期，前半夜深睡多、后半夜 REM 多。醒来是一个泊松过程，速率 = 阶段敏感度 ×（基础速率 + 增益 × 床头照度）。参数是粗略设定的，以后应当用真实的手表数据拟合。
- **传感器**：照度读数 = 自然光 + 灯光（满亮度约 300 lx），变化超过 1 lx / 5% 或满 1 分钟时上报。人体传感器目前是理想的。

## 已知局限

- 睡眠模型里清晨大多是浅睡，所以"在哪个阶段被叫醒"这项指标在开和不开模拟日出时差别不大；要用真实数据校准后才有说服力。
- 手机闹钟事件和"晚安"按钮目前由仿真器代发；真实使用需要一个 HTTP → MQTT 的小网关，配合 iPhone 快捷指令。
- 控制器的状态（模式、学习到的增益）没有发布出来，渲染页看不到。

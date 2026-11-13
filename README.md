# smart_home

自己搭的智能家居，目前只做灯光控制。控制器用 Python，设备之间通过 MQTT 通信；现在由仿真器代替硬件，以后换成 ESP32 节点。

## 架构

```
控制器 (Python)  <──MQTT──>  Mosquitto  <──MQTT──>  节点（现在是仿真器，以后是 ESP32）
```

- 节点只负责上报传感器、执行命令，不含逻辑；所有逻辑都在控制器里。
- 仿真节点和真实节点使用同一套主题约定（见 [src/smarthome/protocol.py](src/smarthome/protocol.py)），换硬件时控制器不用改。
- 房间逻辑是纯状态机（[src/smarthome/controller/room.py](src/smarthome/controller/room.py)），不依赖 MQTT，可以直接做单元测试。

| 主题 | 方向 | 内容 |
|---|---|---|
| `home/<room>/motion` | 节点 → 控制器 | `{"occupied": bool}` |
| `home/<room>/lux` | 节点 → 控制器 | `{"lux": float}` |
| `home/<room>/light/set` | 控制器 → 节点 | `{"on": bool, "brightness": 0-255}` |
| `home/<room>/light/state` | 节点 → 控制器 | `{"on": bool, "brightness": 0-255}`（retained） |
| `sim/time` | 仿真器 → 全部 | `{"t": unix 秒}`，仅在仿真时间下使用 |

## 安装

```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
```

## 运行

**离线仿真**（单进程，不需要 MQTT，一天约 5 秒）：

```powershell
.venv\Scripts\python -m smarthome.offline --hours 24 --seed 0 -v
.venv\Scripts\python -m smarthome.offline --off-delay 60 --dark-lux 80   # 调参对比
```

**通过 MQTT 运行**（和以后接真实硬件时的结构一样）：

```powershell
docker compose up -d                                          # 启动 Mosquitto
.venv\Scripts\python -m smarthome.controller --sim-clock      # 终端 1
.venv\Scripts\python -m smarthome.sim --speed 60 --start "2026-11-13 17:00" --hours 6   # 终端 2
```

`--speed 60` 表示 1 秒现实时间对应 1 分钟仿真时间。

**测试**：

```powershell
.venv\Scripts\python -m pytest
```

## 指标

仿真结束时按房间输出：

- `lights on`：开灯次数
- `wasted min`：灯亮着但没人的时间
- `dark min`：有人、环境偏暗、但灯没开的时间

## 仿真模型

- 一个住户，按工作日作息随机生成路线：起床、出门、晚上回家、偶尔夜里起床。所有房间经由走廊连通。
- 日照：日出到日落的正弦曲线乘以随机云量；客厅采光 100%，卧室 50%，走廊几乎没有。
- 光照传感器读数 = 自然光 + 灯光（满亮度约 300 lx）。灯光会污染照度读数，这一点是故意保留的。
- 人体传感器目前是理想的（人在就是 true）。

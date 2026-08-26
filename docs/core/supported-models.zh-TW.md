# 支援型號

## Product LIVE 支援邊界

一般 Product LIVE 執行使用下方的精確 Product matrix。Powers Tool 會識別連線的
model，並要求 model、command、transport、backend 與必要 feature 完全相符。
缺少、不支援或非 Product-open 的 scope 都會 fail closed。Product-open 的
system VISA scope 不會自動延伸到 pyvisa-py、pyvisa-bt 或 custom backend。
目前沒有任何 Product-open exact scope 使用 pyvisa-bt。E3646A 與 PSM-2010
僅限 ASRL / RS-232 + system VISA。

## Product LIVE Exact-Scope Matrix

目前 Product-open 的 command inventories 如下：

| Model | 精確 Product connections | Product-open model-aware commands |
| --- | --- | --- |
| `keysight-e36312a` (Keysight E36312A) | USB + system VISA; TCPIP + system VISA | `measure`, `output-state`, `read-status`, `readback`, `validate-readonly`, `capabilities`, `set`, `output-on`, `output-off`, `safe-off`, `cycle-output`, `apply`, `ramp`, `smoke-output`, `ramp-list`, `sequence`, `protection-status`, `protection-set`, `clear-protection`, `snapshot`, `restore-from-snapshot`, `measure-all`, `log`, `doctor`, `trigger-status`, `trigger-step`, `trigger-list`, `trigger-abort`, `trigger-fire`, `trigger-pulse` |
| `keysight-edu36311a` (Keysight EDU36311A) | USB + system VISA; TCPIP + system VISA | `measure`, `output-state`, `read-status`, `readback`, `validate-readonly`, `capabilities`, `set`, `output-on`, `output-off`, `safe-off`, `cycle-output`, `apply`, `ramp`, `smoke-output`, `ramp-list`, `sequence`, `protection-status`, `protection-set`, `clear-protection`, `log`, `doctor` |
| `keysight-e3646a` (Keysight E3646A) | ASRL / RS-232 + system VISA | `measure`, `output-state`, `read-status`, `readback`, `capabilities`, `set`, `output-on`, `output-off`, `safe-off`, `cycle-output`, `apply`, `ramp`, `smoke-output`, `ramp-list`, `sequence`, `log`, `doctor` |
| `gw-instek-psm-2010` (GW Instek PSM-2010) | ASRL / RS-232 + system VISA | `measure`, `output-state`, `read-status`, `readback`, `validate-readonly`, `capabilities`, `set`, `output-on`, `output-off`, `safe-off`, `cycle-output`, `apply`, `ramp`, `smoke-output`, `ramp-list`, `sequence`, `protection-status`, `protection-set`, `clear-protection`, `snapshot`, `restore-from-snapshot`, `log`, `doctor` |

`list-resources`、`verify`、`identify`、`error` 與 `clear` 是明確的診斷豁免項目。
它們的成功只證明該項診斷操作；不代表開啟了其他 model、feature family、
transport/backend scope 或其他 command。

上方的 Product-open command rows 是精確 scope，不是 transport/backend 繼承。
未列出的 command 或 feature 不會由另一個 model、connection、backend 或
command family 開啟。

## Feature-Aware 精確支援範圍

上方的 Product-open command rows 不是其他 command sub-features 的萬用字元。
Powers Tool 會逐一檢查 Sequence step actions 與 Trigger Step/List sources。
Sequence `wait` 與 `log` 仍是 host-only actions。目前 live trigger sources
為 `bus` 與 `immediate`（`imm` 會正規化為 `immediate`）；PIN/EXT inputs
會被拒絕。

在 Product-open connection 上，支援的 actions 與 sources 可供 Product 使用。
pending 的 connection 或 feature 目前不受支援；缺少某個 action 或 source 的
支援不代表該功能可用。

## 目前無法用於 Product 的型號

以下 catalog-known model IDs 目前不是有效的 Product planning 或 live
expected-model identities：`keysight-e36313a`、`keysight-e36233a`、
`keysight-e36441a` 與 `keysight-e36155a`。

`keysight-e36103b` 與 `keysight-e36232a` 已 de-scoped。它們在 no-hardware
planning identities、live expected-model guards、WebUI model selections 與
live model-aware operations 中都會被拒絕，且不會退回使用 `generic-scpi`。

其他 Keysight E36xxx / E36000-series models 目前沒有 Product support。
`generic-scpi` 仍是保守的 no-hardware planning profile，不是 physical live
model。

## 依連線範圍區分的 Product 支援

Product support 以 model、connection、backend、command 與 feature 為 scope。

目前的精確 Product connections 為 E36312A USB 與 LAN、EDU36311A USB 與 LAN，
以及 E3646A 與 PSM-2010 的 ASRL / RS-232。每個 connection 僅限於 Product
matrix 中列出的 commands 與 feature entries。E3646A 與 PSM-2010 的 USB 與
LAN 不在目前 scope 內。

E36312A 與 EDU36311A 的 TCPIP + pyvisa-py connections 目前無法用於 Product
use。System VISA 支援不會延伸到 pyvisa-py、pyvisa-bt 或 custom backend。

| Model | USB | LAN | ASRL / RS-232 |
| --- | --- | --- | --- |
| E36312A | 僅接受列出的精確 commands | 僅接受列出的精確 commands | N/A |
| EDU36311A | 僅接受列出的精確 commands | 僅接受列出的精確 commands | N/A |
| E3646A | 不在目前 scope | 不在目前 scope | 僅接受列出的精確 commands |
| PSM-2010 | 不在目前 scope | 不在目前 scope | 僅接受列出的精確 commands |

EDU36311A 的 trigger/native LIST 與 snapshot/restore 在 live、simulate 與
dry-run 模式中仍停用。E3646A 的 protection、trigger/native LIST、
snapshot/restore 與 completion-pulse 仍停用。E3646A 的 `ramp-list` 與
`sequence` 仍僅為 software workflows，不是 native LIST。

EDU36311A 的 USB read-only、output/write 與 protection commands 可在上方的
精確 Product scopes 內進行 real execution。EDU36311A 的 `protection-set` 與
`clear-protection` 需要 `--confirm` 才能進行 real execution，且支援 Product use。

Trigger workflows 僅限 E36312A。EDU36311A、E3646A、PSM-2010 與
`generic-scpi` 在 live、simulate 與 dry-run 模式都不提供 trigger workflows。
PSM-2010 不支援 Powers trigger workflows。

## No-Hardware Planning Identity 對照表

Dry-run 與 simulate planning 不會開啟真實 VISA hardware。Model-specific
no-hardware commands 需要明確的 planning identity 或已知的 deterministic
SIM resource。Fake 或看似真機的 resource strings 是 placeholder，不得暗示
model identity。

| Planning identity | Deterministic SIM resource | No-hardware channels | Output control scope | Trigger / LIST / protection notes |
| --- | --- | --- | --- | --- |
| `keysight-e36312a` | `USB0::SIM::E36312A::INSTR` | CH1, CH2, CH3 | 每通道獨立輸出控制；`all` 展開為 CH1–CH3 | Trigger workflows 與 native LIST 僅限 E36312A，且在支援的 live E36312A paths 上為 Product-open。Protection read/write paths 支援。 |
| `keysight-edu36311a` | `USB0::SIM::EDU36311A::INSTR` | CH1, CH2, CH3 | 每通道獨立輸出控制；`all` 展開為 CH1–CH3 | Protection read/write paths 支援。Trigger workflows 與 native LIST 在 dry-run、simulate 與 real mode 中都不提供。 |
| `keysight-e3646a` | `ASRL1::SIM::E3646A::INSTR` | CH1, CH2 | 全域 output enable/disable；channel selection 用於 setpoints 與 readback | RS-232 / ASRL output workflows 在精確 scope 內為 Product-open。Protection writes、trigger workflows、snapshot restore、completion pulses 與 native LIST 停用。 |
| `gw-instek-psm-2010` | `ASRL1::SIM::PSM2010::INSTR` | CH1 | 全域輸出控制 | Product LIVE 包含 matrix 中列出的精確 read-only、output、protection、snapshot/restore、ramp 與 software-sequence commands。LOW 與 HIGH ranges 保持不同。此 model profile 不支援 Powers trigger workflows。 |
| `generic-scpi` planning profile | 無；dry-run 中請明確使用 `--profile generic-scpi` | CH1 | 未知 | 僅供保守的 no-hardware planning。Trigger workflows、native LIST 與 protection writes 都不提供。 |

Live hardware 使用 manufacturer-plus-model IDN resolution。在 live mode 中，
`--model` 作為 expected-model guard：偵測到的 canonical identity 必須相符才
會執行 command-specific SCPI；不符時 fail closed。此 guard 不會覆寫 IDN 所選
的 driver。`generic-scpi` 是保守的非實體 dry-run profile，不是 live expected
model。

對 model-aware live execution，Powers Tool 依偵測到的 `*IDN?` model 加上精確
command、transport 與 VISA backend 做出最終 Product decision。缺少或非
Product-open 的 scope 在正常 Product use 中會被拒絕；identity diagnostics
不代表 model 或 feature support。

## 輸出設定值 Programming Ranges

對 output workflows 而言，`voltage` 表示 output voltage setpoint，`current`
表示 output current limit/current setting。下列數值是來自 model manuals 的
programming range metadata；與現有 DC output rating safety limits 不同。
Powers Tool 目前的強制小數位規則尚未實作，也不會在使用者送出 SCPI 前
四捨五入或截斷 setpoint。

| Model | Channel / output | Range | Voltage programming range | Current-limit programming range | Current MIN keyword value |
| --- | --- | --- | --- | --- | --- |
| E36312A | CH1 / P6V | fixed | 0 to 6.18 V | 0 to 5.15 A | 0.001 A |
| E36312A | CH2 / P25V | fixed | 0 to 25.75 V | 0 to 1.03 A | 0.001 A |
| E36312A | CH3 / N25V | fixed | 0 to 25.75 V | 0 to 1.03 A | 0.001 A |
| EDU36311A | CH1 / P6V | fixed | 0 to 6.18 V | 0 to 5.15 A | 0.002 A |
| EDU36311A | CH2 / P30V | fixed | 0 to 30.9 V | 0 to 1.03 A | 0.001 A |
| EDU36311A | CH3 / N30V | fixed | 0 to 30.9 V | 0 to 1.03 A | 0.001 A |
| E3646A | OUT1 / CH1 | LOW / P8V | 0 to 8.24 V | 0 to 3.09 A | 0 A |
| E3646A | OUT1 / CH1 | HIGH / P20V | 0 to 20.60 V | 0 to 1.545 A | 0 A |
| E3646A | OUT2 / CH2 | LOW / P8V | 0 to 8.24 V | 0 to 3.09 A | 0 A |
| E3646A | OUT2 / CH2 | HIGH / P20V | 0 to 20.60 V | 0 to 1.545 A | 0 A |
| PSM-2010 | OUT1 / CH1 | LOW / P8V | 0 to 8.24 V | 0 to 20.6 A | N/A |
| PSM-2010 | OUT1 / CH1 | HIGH / P20V | 0 to 20.6 V | 0 to 10.3 A | N/A |

Sources: E36300 Series Programmable DC Power Supplies Programming Guide,
manual part number E36311-90008, printed page 16; EDU36311A Programming Guide,
manual part number EDU36311-90013, printed pages 15 and 39; Agilent E364xA
Dual Output DC Power Supplies User's and Service Guide, manual part number
E3646-90001, printed pages 82, 83, 84, and 91; GW Instek PSM-Series
Programming Manual, manual part number 82SM-60030IA, printed page 28.
E3646A 與 PSM-2010 的 ranges 取決於所選 range，不可壓平為單一 voltage/current
最大值。在 *RST 後，E3646A 會選擇低電壓 range。PSM-2010 manual 記載儀器全域
*RST current value 為 20 A；這不代表在 HIGH range 下允許 20 A。HIGH 仍受限
於 10 A rating 與 10.3 A programming maximum。

## Command 支援注意事項

上方 matrix 對應以下 command-level facts：

- 不支援的 model、command 與 mode combinations 會刻意 fail。這些 feature-lock
  failures 表示該 workflow 在該 model 上不受支援，而不是 `--model` 或 WebUI
  selector 可以解鎖它。
- CLI `--model` 與 WebUI model selection 在 dry-run/simulate mode 中選擇
  canonical physical planning models。Live requests 使用 IDN-driven detection；
  driver selection 一律依循連線儀器的 identity。`generic-scpi` 仍是保守的
  no-hardware planning profile，永遠不是 live expected model。
- E36312A 的 native trigger/LIST support 透過 `trigger-status`、
  `trigger-step`、`trigger-list` 與 `trigger-abort` 提供。Trigger dry-run 與
  simulator paths 也僅限 E36312A。Native LIST execution 上限 100 steps，
  dwell values 為 0.01 至 3600 秒，count values 為 1 至 256。目前 real native
  trigger sources 僅限 BUS 與 immediate；後方面板 pin 與外部 input sources
  不屬於 Product-open。
- Ramp 一律使用 software setpoint steps。Native LIST execution 僅限
  `trigger-list`。
- EDU36311A 的 USB 與 LAN product execution 僅限於上方 matrix 中的精確
  commands。Feature-family 與 sequence-step support 不會擴大該 command inventory。
- E36312A 與 EDU36311A 的 OVP/OCP trip status 以 channel 為單位查詢。Aggregate
  `protection-status` flags 是所選 channel results 的 OR 結果。
- EDU36311A 的 trigger commands 在所有模式中保持停用。
- EDU36311A 的 snapshot 與 restore-from-snapshot 不屬於 Product-open。
- EDU36311A 的 `sequence` 不得繞過已停用的 trigger/native LIST、snapshot 或
  restore workflows；不支援的 sequence step types 在 live、simulate 與 dry-run
  paths 中持續被拒絕。
- E3646A 的 product execution 僅限 ASRL / RS-232 + system VISA 以及上方
  matrix 中的精確 commands。`output-on` 只在該 ASRL + system-VISA scope 中
  屬於 Product-open。在任何被接受的 live E3646A output command 之前，請確認
  實體 setup 已檢查且要求的 voltage/current limits 對連接負載安全。
  `verify` 是 model-independent connection diagnostic，會開啟選定的 resource
  並查詢 `*IDN?`；它不屬於 model capability matrix。E3646A 使用 `INST:NSEL`
  進行 channels 1 與 2 的 channel preselection，不用 channel-list SCPI 做
  output writes。E3646A 的 `OUTP ON/OFF` 是全域 output enable/disable；
  channel selection 仍用於 setpoint writes 與 readbacks，但 output
  enable/disable 影響的是整台儀器的 output state。Protection changes、
  trigger workflows、snapshot、restore、completion pulses 與 native LIST
  保持停用。E3646A 的 `ramp-list` 是 software setpoint stepping，而其
  `sequence` 是僅限支援 output/read-only steps 的 software workflow。兩者都
  不是 native instrument LIST support。E3646A sequence 會拒絕不支援的 step
  types，例如 protection、trigger、snapshot、restore、native LIST 與
  completion-pulse steps。
- E3646A serial settings 僅限明確設定。若未提供 serial options，程式不會覆寫
  VISA backend、Keysight IO Libraries Suite 或 Connection Expert 的 serial
  settings。Factory example 為 9600 baud、8 data bits、none parity、
  2 stop bits 與 DTR/DSR handshake，但實際 front-panel settings 可能不同且
  不會自動套用。
- E3646A 的 `SYST:REM` 與 `SYST:LOC` 是會改變狀態的 remote/local commands。
  只有在針對 ASRL resource 明確要求 `--serial-remote` 或
  `--serial-local-on-close` 時才會送出。
- PSM-2010 的 Product execution 僅限 ASRL / RS-232 + system VISA 以及上方
  matrix 中的精確 commands。它使用 CH1、全域 output control，以及不同的
  LOW/HIGH operating ranges。其 Product-open 的 `sequence` actions 為
  `apply`、`cycle-output`、`measure`、`output-off`、`output-on`、
  `output-state`、`readback`、`safe-off` 與 `set`；`wait` 與 `log` 仍是
  host-only。Protection command family 支援 OVP configuration、OCP
  enable/status/trip behavior 與 protection clear。OCP delay configuration、
  readback 與 trigger 不受支援。Powers trigger commands、其他 transports 與
  其他 VISA backends 保持關閉。
- No-hardware output-family、Ramp List、Sequence、`protection-set`、
  `clear-protection` 與 trigger plans 使用 strict planning identity。
  `--dry-run` 與 `--simulate` 需要明確的 physical `--model` 或已知的
  deterministic SIM resource。Trigger no-hardware plans 只接受
  `--model keysight-e36312a` 或已知 deterministic E36312A SIM resource，
  例如 `USB0::SIM::E36312A::INSTR`；EDU36311A SIM resource 會被解析後因
  trigger workflows 拒絕。E3646A no-hardware `--channel all` plans 會展開為
  CH1 與 CH2；CH3 會被拒絕。
- Live trigger behavior 依 IDN 判定。`--model` 是 live expected-model guard，
  不會覆寫連接的硬體。
- `snapshot-diff`、`snapshot-diff --summary` 與 `hardware-report` 是
  offline/no-hardware tools，永不開啟 VISA。`sequence --lint` 同樣在不開啟
  VISA 的情況下驗證，並保持 syntax/document validation，除非搭配
  `--dry-run` 或 `--simulate`。

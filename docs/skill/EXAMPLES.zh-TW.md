# Powers Tool CLI 調度範例

以下 prompt 假設已安裝 `powers-tool-cli-orchestration`。Live workflow prompt
中的角括號 placeholder 必須先替換。

## 無硬體 simulator read-only workflow

```text
使用 $powers-tool-cli-orchestration 搭配 <POWERS_TOOL_EXECUTABLE> 執行內附的 deterministic E36312A simulator helper。只能使用 USB0::SIM::E36312A::INSTR、simulate mode、planning_model_id keysight-e36312a 與 read-status。將 artifacts 寫到 .tmp_tests/power_skill_smoke，並只依 schema 2 machine evidence、request/result artifacts、correlation、final summary 與 Worker exit code 判定成功。不得執行 VISA discovery 或任何 output-affecting command。
```

預期行為：Agent 使用固定 helper workflow，不開啟真實硬體，並回報任何
correlation、parse、terminal result、summary 或 exit code 檢查失敗。

## Contract-aware repository diff review

```text
使用 $powers-tool-cli-orchestration 審查目前 repository diff。依 contract lookup order 讀取上游 Common 與 Power Worker／CLI／orchestrator contracts、Core command-parameter contract 與 supported-models.md。檢查 schema_version 2、POST /command top-level context、identity semantics、Core-owned admission、run/job/artifact correlation、Product LIVE exact scope 與 owned-process cleanup。只回報 findings；不要修改檔案或執行 live hardware。
```

預期行為：Repository 原始文件優先於 installed references。審查不會將
no-hardware capability、pending evidence 或其他 backend 視為 Product-open。

## 準備但不執行 live read-only workflow

```text
使用 $powers-tool-cli-orchestration 準備但不要執行 live read-only Power Worker read-status workflow。使用者明確選定的 exact VISA resource 是 <EXACT_USER_PROVIDED_VISA_RESOURCE>。我明確授權未來 workflow 對該 exact resource 進行 live read-only access，但本次 request 只授權規劃。不得掃描、猜測、輪替或替換 resource。expected_model_id keysight-e36312a 只能作為 live mismatch guard；請從 supported-models.md 驗證 exact model + read-status + transport + backend + required-feature Product scope，並提供 Worker config、schema 2 POST /command request、readiness、terminal result、stop、summary 與 exit-code checks。
```

預期行為：Agent 只產生計畫，不啟動 Worker，也不開啟 VISA。Placeholder
尚未換成使用者提供的 exact resource 時，Agent 會拒絕完成可執行計畫；model
guard 不會用來選 driver 或解鎖 support。

## 準備但不執行 live output-affecting workflow

```text
使用 $powers-tool-cli-orchestration 準備但不要執行 live output-affecting Power Worker apply workflow。使用者明確選定的 exact VISA resource 是 <EXACT_USER_PROVIDED_VISA_RESOURCE>。我明確授權未來 workflow 只對該 exact resource 執行 live output，但本次 request 只授權規劃。不得掃描、猜測、輪替或替換 resource。expected_model_id keysight-e36312a 只能作為 mismatch guard。先驗證 exact Product scope。必須同時要求 Worker settings.allow_output_writes: true 與 request arguments.confirm_output: true。規劃 CH1 使用保守的 0.05 A current limit 與 0.5 V setpoint，保留 current-before-voltage 行為、驗證 output state，並在失敗時也執行 safe-off 與完整 owned-process cleanup。包含 schema 2 request/result 與 run_id/job_id/worker_job_id checks。
```

預期行為：Agent 準備 config 與 request，但不執行 live I/O。兩個
output-write gates 都保持明確；cleanup 包含 safe-off、terminal artifact
驗證、cooperative stop、final summary 與 Worker exit code。Placeholder 必須
替換後，計畫才可實際使用。

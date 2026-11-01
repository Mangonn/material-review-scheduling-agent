# 03 评估结果与限制

2026-11-01 在 Python 3.14.3 执行 `python3 -m unittest discover -s tests -v`：**12 项通过**，原始记录见 [test-results.txt](../examples/test-results.txt)。示例由真实 CLI 调用生成，命令为 `python3 examples/run_examples.py`；输出和独立 Trace 均保存在 `examples/`。所有示例模式均为 `mock_policy`。

| 验收点 | 输入 | 实际输出 | Trace | 实际结果 |
| --- | --- | --- | --- | --- |
| 正常排期 | [normal](../examples/inputs/normal.json) | [normal](../examples/outputs/normal.json) | [normal](../examples/traces/normal.json) | 审核通过，保存草稿，未发布 |
| 信息缺失 | [missing](../examples/inputs/missing.json) | [missing](../examples/outputs/missing.json) | [missing](../examples/traces/missing.json) | 缺 `license`，未保存 |
| 规则风险 | [risk](../examples/inputs/risk.json) | [risk](../examples/outputs/risk.json) | [risk](../examples/traces/risk.json) | 命中禁用声明，阻断 |
| 时段冲突 | [conflict](../examples/inputs/conflict.json) | [conflict](../examples/outputs/conflict.json) | [conflict](../examples/traces/conflict.json) | 18:00 占用，补查 19:00，保存待确认草稿 |
| 重复提交 | 同 [conflict](../examples/inputs/conflict.json) | [duplicate](../examples/outputs/duplicate.json) | [duplicate](../examples/traces/duplicate.json) | 返回原草稿，数据库仍只有一条 |
| 明确确认 | [approved_change](../examples/inputs/approved_change.json) | [approved_change](../examples/outputs/approved_change.json) | [approved_change](../examples/traces/approved_change.json) | 只更新草稿状态，未发布 |
| 保存失败 | 同 [normal](../examples/inputs/normal.json)，加 `--fail-save` | [save_failure](../examples/outputs/save_failure.json) | [save_failure](../examples/traces/save_failure.json) | `failed` 与 `simulated_storage_failure`，数据库无草稿 |

`test_step_limit_returns_incomplete` 与 `test_tool_limit_returns_incomplete` 验证超限返回明确未完成；`test_model_cannot_save_without_observed_review` 验证模型越过审核直接保存时被工具拒绝。

## 失败与已知限制

- 当前环境尚未配置模型 API 密钥，真实模型路径**未运行、未验证模型选择动作的实际效果**。至少两条不同的离线 Trace 可证明工具观察后流程改变，不能替代考核要求的真实模型决策记录。获得凭证后应在 `--mode deepseek` 或 `--mode openai` 下重跑冲突与风险两条路径并提交其 Trace。
- 合成规则仅是演示，无法替代真实内容、版权、平台政策审核。没有线上排期系统与发布接口。
- 用字符串匹配候选时段，要求输入采用 `data/schedule.json` 的时区格式；没有跨时区归一化或复杂时间窗优化。
- 数据库的唯一请求键不包含素材修订号。素材更新后同一请求可能返回旧草稿，生产实现需带版本并触发复审。
- SQLite 适合本地演示；跨进程高并发调度需共享事务存储和更强的锁策略。

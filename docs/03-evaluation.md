# 03 评估结果与限制

2026-11-01 在 Python 3.14.3 执行 `python3 -m unittest discover -s tests -v`：**14 项通过**，原始记录见 [test-results.txt](../examples/test-results.txt)。下表离线示例由真实 CLI 调用生成，命令为 `python3 examples/run_examples.py`；输出和独立 Trace 均保存在 `examples/`，模式为 `mock_policy`。

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

## 真实模型决策记录

2026-11-01 使用 `deepseek-flash` 的非思考模式运行 `python3 examples/run_model_examples.py --mode deepseek`，工具函数由模型实际选择。本次样例使用独立数据库，未使用真实业务数据。

| 路径 | 输入 | 实际输出 | Trace | 工具观察后的后续动作 |
| --- | --- | --- | --- | --- |
| 冲突调整 | [conflict](../examples/inputs/conflict.json) | [deepseek_conflict](../examples/model_outputs/deepseek_conflict.json) | [deepseek_conflict](../examples/model_traces/deepseek_conflict.json) | 18:00 返回占用后选 `query_slot(19:00)`；空闲后选 `save_draft(19:00)`，结果为 `pending_confirmation`，6 步 |
| 规则阻断 | [risk](../examples/inputs/risk.json) | [deepseek_risk](../examples/model_outputs/deepseek_risk.json) | [deepseek_risk](../examples/model_traces/deepseek_risk.json) | `check_rules` 返回风险后选 `finish`，无排期查询或保存，3 步 |

`model_turn` 表示一次模型响应。风险用例中读取素材与规则检查来自同一模型响应的两个只读调用；模型收到两项结果后才决定结束。冲突用例每步均为独立模型响应。

首次 API 调试遇到本机 Python 证书链错误；指定系统证书后，发现 DeepSeek 可在一次响应中给出多个只读工具请求。适配器现支持逐个执行只读调用并汇总回传，涉及写入的并行请求会被拒绝。上述两条为修复后的实际结果。

## 失败与已知限制

- 真实模型仅验证了冲突与规则风险两条路径；其余验收点使用离线策略与工具测试验证。OpenAI 模式已实现但本次未实测。两条样例不能推断真实模型在所有素材上的准确率。
- 合成规则仅是演示，无法替代真实内容、版权、平台政策审核。没有线上排期系统与发布接口。
- 用字符串匹配候选时段，要求输入采用 `data/schedule.json` 的时区格式；没有跨时区归一化或复杂时间窗优化。
- 数据库的唯一请求键不包含素材修订号。素材更新后同一请求可能返回旧草稿，生产实现需带版本并触发复审。
- SQLite 适合本地演示；跨进程高并发调度需共享事务存储和更强的锁策略。

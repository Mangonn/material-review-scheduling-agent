# 题目 1：素材审核与发布排期 Agent

一个 CLI 项目：读取合成素材、检查规则与时段，最多保存 SQLite 草稿。**没有发布工具，也不会实际发布。**

## 评审最快入口

需要 Python 3.11+；项目只用标准库，无需 `pip install`。在仓库根目录执行：

```bash
python3 -m unittest discover -s tests -v
python3 examples/run_examples.py
python3 -m src.cli examples/inputs/conflict.json --db work/review.sqlite3
python3 -m src.cli examples/inputs/conflict.json --db work/review.sqlite3
python3 -m src.cli examples/inputs/approved_change.json --db work/review.sqlite3
```

前三次 CLI 运行依次展示：冲突后建议 19:00 并待确认、重复请求返回同一草稿、用户明确确认后更新草稿时段状态。每次输出均含步骤、参数、工具结果和简短决策依据。`work/review.sqlite3` 是本地状态，可删除后重跑。

## 其他验收命令

```bash
python3 -m src.cli examples/inputs/normal.json --db work/normal.sqlite3
python3 -m src.cli examples/inputs/missing.json --db work/missing.sqlite3
python3 -m src.cli examples/inputs/risk.json --db work/risk.sqlite3
python3 -m src.cli examples/inputs/normal.json --db work/failure.sqlite3 --fail-save
python3 -m src.cli examples/inputs/normal.json --db work/limit.sqlite3 --max-steps 2
```

失败与未完成情形返回退出码 2，并在 JSON 中给出 `completion_status`、`save_error` 或 `stop_reason`。示例的实际输出在 [examples/outputs](examples/outputs)，独立 Trace 在 [examples/traces](examples/traces)，测试记录在 [examples/test-results.txt](examples/test-results.txt)。

## 真实模型入口

DeepSeek：在根目录创建被 `.gitignore` 排除的 `.env`，填入 `DEEPSEEK_API_KEY=...`，然后执行：

```bash
python3 -m src.cli examples/inputs/conflict.json --mode deepseek --db work/deepseek.sqlite3
```

默认模型 `deepseek-flash`，可用 `DEEPSEEK_MODEL` 更改。使用 DeepSeek Chat Completions 的函数调用；API 设置依据 [DeepSeek 官方工具调用](https://api-docs.deepseek.com/guides/tool_calls/)和[Chat Completions 文档](https://api-docs.deepseek.com/api/create-chat-completion/)。

OpenAI：

```bash
export OPENAI_API_KEY='你的密钥'
export OPENAI_MODEL='gpt-6.1-sol'
python3 -m src.cli examples/inputs/conflict.json --mode openai --db work/model.sqlite3
```

真实模式每一步均由模型从 `read_material`、`check_rules`、`query_slot`、`save_draft`、`finish` 中选择，工具输出再送回模型。OpenAI 模式使用 Responses API，结构参考 [OpenAI 官方函数调用文档](https://developers.openai.com/api/docs/guides/function-calling)。`--mode mock` 是默认的确定性离线策略，只验证流程、工具和防护；截至当前文档版本，**尚未产生真实模型运行记录或真实模型效果结论**。

## 输入和结果

输入 JSON：`material_id`、带时区的 `requested_slot`、`requirement`（`hard` 或 `soft`），可选 `approved_alternative_slot`。硬性时段被占用时，替代时段只作为待确认建议保存。只有用户明确提供与已有建议完全一致的 `approved_alternative_slot`，已有草稿才会更新为 `confirmed_time`。这仍是草稿，`published` 始终为 `false`。

输出包含 `review_status`、`risk_reasons`、`missing_fields`、`suggested_slot`、`pending_confirmation`、`draft_status`、`save_error`、`completion_status` 和 `trace`。所有素材、规则、时段均为合成数据。默认最多 10 个决策步骤、8 次工具调用，到上限返回 `incomplete`。

## 文档

- [需求与成功标准](docs/01-requirements.md)
- [方案与动态决策](docs/02-solution.md)
- [评估与限制](docs/03-evaluation.md)
- [AI 使用记录](docs/04-ai-usage.md)
- [复盘](docs/05-retrospective.md)

本地项目可运行；GitHub URL 与远端 commit SHA 需在获得仓库写入权限并推送后填写，不能以本地提交代替远端交付。

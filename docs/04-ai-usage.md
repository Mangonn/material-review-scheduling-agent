# 04 AI 使用与个人贡献

本项目在本次对话中由 Codex AI 助手辅助完成：需求拆解、代码与合成数据生成、测试编写、运行示例、文档初稿及检查。OpenAI Docs 和 DeepSeek 官方 API 文档用于核对模型接入格式。没有使用真实业务资料；用户提供的 DeepSeek API 密钥仅用于运行验证，未写入仓库、输出或 Trace。

可核实的人工作用：用户提供题目、交付规范及验收重点，创建公开 GitHub 仓库，并提供 DeepSeek 验证凭证；截至本文档生成时，用户尚未在本次对话提供本人代码修改或独立复核记录。因此**不声称候选人已亲自实现、修改或验证**。提交前应由候选人实际运行测试、审阅关键防护并在此记录其个人修改及结果；不能把 AI 产出写成个人独立完成。

已执行验证：`python3 -m unittest discover -s tests -v`，19 项通过；`python3 examples/run_examples.py` 生成 7 组 CLI 离线实际输出和 Trace。使用 DeepSeek API 实际运行冲突和规则风险两组，分别得到 `pending_confirmation` 与 `blocked`；记录见 `examples/model_outputs/` 和 `examples/model_traces/`。离线 Mock 输出只证明程序流程、工具防护与持久化行为，不证明模型决策准确率。

实际耗时：本次 AI 辅助实现、离线与真实模型验证、仓库交付约为 2026-11-01 22:23–23:03（北京时间），约 40 分钟。候选人个人用时和个人修改尚未发生，须在正式提交前据实补录。

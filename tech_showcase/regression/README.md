# Prompt 回归测试

让 Supervisor Agent 的任何 Prompt / 模型 / Tool 改动，都能**用数据说话**。

## 为什么需要

改了 Supervisor prompt 想确认效果？之前只能：
- 凭感觉手跑两个 demo
- 回头发现某种 case 偷偷挂了

有了回归测试后：
- 跑一条命令，跑完 8 条（未来 30+）case
- 对比上次 baseline，自动生成 Markdown 报告
- 每条 case 的路由、关键词、LLM judge 分数、耗时都有记录
- 退出码 0/1 供 CI 未来接入

## 目录速览

```
tech_showcase/regression/
├── seed_cases.yaml       # 测试用例（source of truth，入 git）
├── run_regression.py     # 回归运行器
├── sync_to_langsmith.py  # 把 YAML 推成 LangSmith dataset（可选）
├── baseline.json         # 冻结的基线（入 git，首次自动生成）
├── latest.json           # 最近一次运行（不入 git）
├── reports/              # 每次运行的 Markdown 报告（入 git 留档）
│   └── YYYYMMDD-HHMMSS.md
└── README.md             # 本文档
```

---

## 日常使用

### 1. 跑一次回归

```bash
cd /Users/photonpay/java-to-agent
.venv/bin/python tech_showcase/regression/run_regression.py
```

输出：
- 终端逐条 case 显示 pass/fail + 路由 + judge 分
- 生成 `reports/YYYYMMDD-HHMMSS.md`
- 覆盖 `latest.json`
- 首次运行会**自动把 latest 另存为 baseline.json**
- 退出码 0（全通过）或 1（有失败）

### 2. 改完 prompt 验证

```bash
# 改 tech_showcase/langgraph_supervisor.py 的 SUPERVISOR_PROMPT_TEMPLATE
# 然后：
.venv/bin/python tech_showcase/regression/run_regression.py
```

报告里会多出 `## vs baseline` 段，看通过率、judge 平均分、耗时的 diff。

### 3. 满意的话固化为新 baseline

```bash
mv tech_showcase/regression/latest.json tech_showcase/regression/baseline.json
git add tech_showcase/regression/baseline.json tech_showcase/regression/reports/
git commit -m "regression: update baseline after prompt tweak"
```

### 4. 不满意就回滚 prompt 继续改

```bash
git checkout tech_showcase/langgraph_supervisor.py   # 或手动回滚
# 再跑一次
```

---

## 如何持续积累测试用例（**重点**）

### 方式 A：手写 YAML（主流做法）

遇到 bad case（比如生产里某个问题 Supervisor 搞错了），立刻加进 `seed_cases.yaml`：

```yaml
- name: 一个描述性 name
  query: "那条让 Agent 翻车的 query"
  conversation_history: ""    # 多轮场景才填
  expected_route: ["parser", "analyzer"]   # 期望路由
  expected_keywords: ["关键词"]              # 答案里该出现的词
  expected_final_report: false
  notes: "人类备注：为什么这 case 值得留"
```

**TDD 思路**：先写 case 复现 bug（观察失败）→ 改 prompt → 再跑（观察转绿）→ 固化新 baseline。
这是工业级 Prompt 工程的黄金流程。

### 方式 B：从 LangSmith trace 里捞

1. 浏览器打开 https://smith.langchain.com/ → java-to-agent 项目 → Traces
2. 找到一条"可疑 trace"（Agent 决策奇怪、耗时异常、回答不满意）
3. 右上角 `Add to Dataset` → 选 `java-to-agent-regression`
4. （当前版本）手动对照那条 trace 的 Input，在 `seed_cases.yaml` 追加对应条目
5. 跑 `sync_to_langsmith.py` 让两侧保持一致

> **说明**：`sync_to_langsmith.py` 当前只做 YAML → LangSmith 的单向推送。
> 从 LangSmith 反向拉回 YAML 的功能（`--pull` 模式）留到后续版本。

### 积累节奏建议

| 时间 | 目标 case 数 | 动作 |
|------|-------------|------|
| 第 1 周 | 12-15 条 | 跑 20+ 次 demo，把 5 条有意思的固化下来 |
| 第 1 月 | 25-30 条 | 覆盖所有主要路由组合（parser / analyzer / reporter / follow-up / 越界） |
| 长期 | 50-100 条 | 每次 bug / 生产投诉都加一条。**再也不会回归同一个 bug** |

### 案例筛选原则（我加哪条、不加哪条）

✅ **值得加**：
- 上次回归里通过的 case（守住现有能力）
- 出过 bug 的真实用户问题
- 边界情况（时间边界、空数据、越界问题、多轮追问）
- 路由分支覆盖（每种 Agent 组合至少 1 条）

❌ **不加**：
- 纯复读（和已有 case 只差一两个字）
- 依赖外部状态的 case（比如要求特定时间段数据）
- 跑一次要 30 秒以上的（回归集是要高频跑的）

---

## 三层评估是怎么算的

| 层次 | 方法 | 加进"pass"判断 |
|------|------|---------------|
| **硬断言：路由** | `expected_route` 里的 Agent 都在实际路径出现过 | ✅ |
| **硬断言：关键词** | `expected_keywords` 都在 agent_outputs 里出现（大小写不敏感） | ✅ |
| **硬断言：report** | `final_report` 是否按预期存在 | ✅ |
| **LLM judge** | qwen-plus 根据 "直接回答 + 基于真实日志 + 简洁" 打 0/0.5/1 分 | 不进 pass 门槛，但进趋势对比 |
| **性能** | 每条 case 的 duration_s 记录下来 | 不进 pass 门槛，进对比 |

> **为什么 judge 不进 pass 门槛**：LLM judge 有 self-judgment bias，绝对分不可靠，但**相对 diff**（改前改后对比）是稳的。所以 judge 分只用于趋势监控。

---

## Judge 模型可换

默认 judge 用 `settings.model_name`（即你主模型 qwen-plus）。想换更强的 judge：

```bash
# 环境变量临时覆盖
REGRESSION_JUDGE_MODEL=qwen-max \
  .venv/bin/python tech_showcase/regression/run_regression.py
```

或者固化到 `.env`：
```bash
REGRESSION_JUDGE_MODEL=qwen-max
```

**权衡**：
- qwen-plus 作 judge：免费跟被测同源，但 self-bias 偏高
- qwen-max 作 judge：贵 3 倍但分更客观（跨模型评估）
- 换了 judge 模型就**必须**重新 baseline（分数体系变了）

---

## LangSmith Dataset 同步

```bash
.venv/bin/python tech_showcase/regression/sync_to_langsmith.py
```

把 `seed_cases.yaml` 推成 LangSmith 里的 `java-to-agent-regression` dataset。
之后在 LangSmith UI 可以：
- Datasets & Experiments → 看 case 列表
- 建 Experiment 批量跑评估（官方功能，本项目暂未集成）

---

## 未来演进（路线图）

**短期（本项目后续可做）**：
- [ ] 报告里每个 case 附 LangSmith trace URL（方便点过去看详细调用链）
- [ ] 支持 `--case <name>` 只跑某条（调试单一 bad case 时）
- [ ] 支持 `--runs N` 同一条跑 N 次取均值（消除 LLM 采样抖动）

**中期**：
- [ ] `sync_to_langsmith.py --pull`：从 LangSmith dataset 把新增 example 拉回 YAML
- [ ] 可视化趋势图：把 `reports/` 下所有报告聚合，画通过率和 judge 分的时间序列

**长期**：
- [ ] GitHub Actions CI：PR 触发 → 跑回归 → PR 评论贴 Markdown 报告
- [ ] 对比实验（A/B）：同一 dataset 跑两个不同 prompt，生成对比表

---

## Java 类比速查

| 概念 | 对应 Java 世界 |
|------|---------------|
| `seed_cases.yaml` | JUnit `@Test` 方法们 |
| `run_regression.py` | JUnit Runner + 自定义 Reporter |
| `baseline.json` | Approved snapshot（类比 [ApprovalTests](https://approvaltests.com/)） |
| `latest.json` | Received snapshot（本次跑的） |
| `reports/*.md` | Surefire/JUnit 报告 |
| `LLM judge` | 没有直接对应物 —— Java 世界的断言是 deterministic 的，AI 世界要 LLM 打分 |
| 退出码 0/1 | Maven `test` 的 BUILD SUCCESS/FAIL |

# 公共政策研究助手 · Policy Research Assistant

> 把政策文本变成**可发表的分析结果**：导入 → 编码 → 信度 → 分析 → 导出。
> 面向公共事业管理、公共政策、计算社会科学方向的研究者与研究生。

在政策文本分析里，真正耗时的从来不是「跑模型」，而是这几件事：

- 几百份 PDF/HTML 里的发文机关、文号、日期要一条条抄进 Excel
- 编码手册写在 Word 里，改了之后前面的编码全部作废
- 审稿人问「编码信度多少」，答不上来
- 论文要交复现包，发现脚本散落在十几个文件夹

`pra` 把这条链路做成一条命令，并且**每一步都留痕**。

---

## 特性

| 模块 | 能力 |
|---|---|
| **语料管理** | PDF / HTML / DOCX / TXT 解析，自动抽取发文机关、文号、日期、效力层级、地区 |
| **政策工具编码** | 泽格维尔德三分法（供给型 / 需求型 / 环境型 + 14 个二级类目），规则基线与 LLM 双通道 |
| **信度检验** | Krippendorff's α、Cohen's κ、一致率，自动列出分歧单元 |
| **分析** | 工具分布、时间趋势、地区/层级差异、政策组合共现 |
| **报告导出** | 单文件 HTML，含图表、方法学附录初稿、样本清单，可直接打印成 PDF |
| **可复现** | 编码手册即配置、SQLite 单文件归档、provenance 记录（谁/何时/什么模型） |
| **离线可用** | 规则基线不依赖网络与 API key，换台机器也能逐字节复现 |

## 快速开始

```bash
# 1. 安装
pip install -e .                    # 核心（仅依赖 pyyaml）
pip install -e ".[ingest,ui]"       # 加上解析与网页界面

# 2. 抓一批示例语料（或把自己的文件放进 data/sample）
python scripts/fetch_samples.py --limit 20

# 3. 导入 → 编码 → 报告
pra import data/sample
pra code --method rules --coder rules
pra report -o exports/report.html

# 4. 打开报告
start exports/report.html           # macOS: open / Linux: xdg-open

# 5. 网页界面（推荐日常使用）
pra serve
```

> 没装成命令行？用 `python -m pra ...` 完全等价（例如 `python -m pra info`）。
> 想一条命令跑完整个流程看效果：`python scripts/demo.py`。

打开 <http://localhost:8501>，界面里有「概览 / 导入 / 编码 / 复核 / 信度 / 导出」六个页签。

## 典型工作流

```
┌─────────┐   ┌─────────┐   ┌──────────┐   ┌────────┐   ┌────────┐
│  导入   │ → │ 机器编码 │ → │ 人工复核 │ → │ 信度   │ → │  报告  │
│ 解析+元数据│  │ rules/llm│  │ 勾选纠错 │  │ α / κ  │  │  HTML  │
└─────────┘   └─────────┘   └──────────┘   └────────┘   └────────┘
```

### 双人编码与信度

```bash
# 编码员 A：规则基线
pra code --coder alice --method rules

# 编码员 B：换一种方法（或换一个人）再编一次
pra code --coder bob --method llm     # 需设置 PRA_LLM_API_KEY

# 计算信度，并导出分歧明细
pra reliability --coder-a alice --coder-b bob --export exports/disagreements.csv
```

> 没有 API key 也能做双人编码：用规则基线跑一次，人工复核后再算 α。
> 复核结果会以 `coder=human` 写入，可与机器结果对比——这正是论文里最有说服力的一张表。

**关于判定空间**：`pra` 计算信度时使用「文档 × 编码手册类目」的完整网格
（例如 6 篇 × 14 类 = 84 个判定单元），而不是只统计有人勾选过的单元。
原因是后者会丢掉「两人都判定为不存在」的单元，导致边际分布失真、
κ 出现「一致率 0.93 但 κ = 0」的悖论。这是政策文本编码里很常见的一个坑。

### LLM 辅助编码（可选）

```bash
set PRA_LLM_API_KEY=sk-...           # Windows
export PRA_LLM_API_KEY=sk-...        # macOS / Linux
pra code --method llm --coder llm
```

支持任何 OpenAI 兼容接口：`PRA_LLM_BASE_URL`、`PRA_LLM_MODEL` 均可覆盖。
LLM 输出的每条编码都会记录模型名与 prompt 版本，写方法学附录时可直接引用。

## 编码手册

编码手册是 `pra/codebook/zegveld.yaml`，包含 14 个二级类目、关键词与排除规则：

```
供给型  资金投入 / 人才培养 / 技术支持 / 公共服务 / 信息支持
需求型  政府采购 / 价格补贴 / 贸易管制 / 海外交流
环境型  目标规划 / 法规管制 / 金融支持 / 税收优惠 / 策略性措施
```

改手册 → `pra code --coder rules` 重跑 → 全语料按新规则重编，幂等可重复。
判定规则、边界案例、论文方法段落模板见 [docs/codebook.md](docs/codebook.md)。

## 报告长什么样

`pra report` 生成单文件 HTML，包含：

1. 概览指标（文本数、编码数、篇均工具数）
2. 政策工具总体分布（条形图 + 明细表）
3. 时间趋势（按年分组柱状图）
4. 地区与层级差异
5. 政策组合（工具共现对）
6. 编码信度
7. **方法学附录初稿**：可直接改写进论文
8. 样本清单

图表为内联 SVG，不依赖 matplotlib，任何机器打开都一样，也方便截图进论文。

## 目录结构

```
pra/
  ingest/     文件解析 + 元数据抽取
  codebook/   编码手册（YAML，唯一事实来源）
  coder/      规则编码器、LLM 编码器、信度计算
  analyze/    描述统计、政策组合
  report/     HTML 报告生成
  cli.py      命令行入口
app/
  streamlit_app.py   网页界面
scripts/
  fetch_samples.py   示例语料抓取
data/sample/         示例政策文本
docs/codebook.md     编码手册（人读版）
tests/               端到端测试
```

## 设计取舍

- **为什么规则基线是默认？** 可复现性优先。LLM 输出会随版本漂移，规则不会。
  两者并用（规则打底、LLM 补充召回）才是稳妥做法。
- **为什么用 SQLite 而不是 CSV？** 编码有 provenance（方法、模型、置信度、标注者），
  CSV 存不下；且单文件便于随论文归档。
- **为什么报告是 HTML？** 浏览器直接打印成 PDF，图表与表格不会跑版；
  比 Word 少一层格式折腾。

## 测试

```bash
# 方式一：不需要额外依赖（推荐用于快速自检）
python scripts/smoke.py

# 方式二：pytest
pip install -e ".[dev]"
pytest -q
```

`smoke.py` 覆盖 27 项检查：编码手册校验、规则编码（含否定语境）、信度计算
（完全一致 / 完全分歧 / 判定空间补齐）、存储与幂等重编码、分析与报告生成、真实文本解析。
pytest 版本覆盖同样的链路，另加空数据容错。

## 路线图

- [ ] 政策力度量化（发文层级 × 工具数量）作为强度变量
- [ ] 政策扩散：文本相似度矩阵 + 传播时序图
- [ ] 支持自定义编码手册（多框架并存）
- [ ] 导出 LaTeX 表格与 BibTeX 条目
- [ ] 中文分词与词频趋势（jieba 可选依赖）

## 免责声明

本工具用于公开政策文本的学术分析，不构成政策建议。
抓取语料请遵守来源网站的 robots 协议与版权规定，仅用于研究目的。

## 许可

Unlicense（公共领域）。

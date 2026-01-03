# TradingAgents-CN 项目优化需求文档

> **项目仓库**: https://github.com/hsliuping/TradingAgents-CN

---

## 一、项目背景

### 1.1 项目简介

TradingAgents-CN 是一个基于多智能体 LLM 的中文金融交易分析框架，fork 自 TauricResearch/TradingAgents 并进行了中文本地化增强。

**核心架构**：
- 后端：FastAPI + Python
- 前端：Vue 3 + Element Plus
- 数据库：MongoDB + Redis
- 部署：Docker 容器化

**多智能体架构**：
```
┌─────────────────────────────────────────────────────────────┐
│                      Analyst Team                           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │Fundamental│ │Technical │ │  News    │ │Sentiment │       │
│  │ Analyst  │ │ Analyst  │ │ Analyst  │ │ Analyst  │       │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘       │
└───────┼────────────┼────────────┼────────────┼──────────────┘
        │            │            │            │
        └────────────┴─────┬──────┴────────────┘
                           │
                    ┌──────▼──────┐
                    │  Research   │
                    │   Team      │
                    │ (Bull/Bear) │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │   Trader    │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │    Risk     │
                    │ Management  │
                    └─────────────┘
```

---

## 二、已完成的分析工作

### 2.1 代码结构分析

**关键文件位置**：
```
tradingagents/
├── agents/
│   ├── analysts/
│   │   ├── china_market_analyst.py  ← 本次重点优化的文件
│   │   ├── fundamental.py
│   │   ├── technical.py
│   │   ├── news.py
│   │   └── sentiment.py
│   ├── managers/
│   ├── researchers/
│   ├── risk_mgmt/
│   ├── trader/
│   └── utils/
│       └── google_tool_handler.py
├── dataflows/
└── utils/
```

### 2.2 发现的问题

**问题 1：Prompt 冗余**

在 `china_market_analyst.py` 中存在两层 Prompt 拼接：

```python
# 第一层：详细的 system_message（约1500字）
system_message = """您是一位专业的中国股市分析师...
分析重点：
- 技术面分析
- 基本面分析
- 政策面分析
..."""

# 第二层：ChatPromptTemplate 中又定义了系统指令
prompt = ChatPromptTemplate.from_messages([
    ("system", "您是一位专业的AI助手...{system_message}..."),
    ...
])
```

**问题**：Token 浪费、职责混淆（与其他专业分析师重复）

**问题 2：职责边界不清**

`china_market_analyst.py` 的 Prompt 要求该 Agent 同时负责：
- 技术面分析（应由 Technical Analyst 负责）
- 基本面分析（应由 Fundamental Analyst 负责）
- 政策面分析
- 资金面分析
- 市场风格判断

**问题 3：缺乏结构化输出**

当前 Prompt 没有强制要求输出格式，导致：
- 输出内容长度不可控
- 难以进行后续解析和评估
- 用户体验不一致

### 2.3 功能模块定位确认

根据 UI 截图分析，股票筛选页面（`/股票筛选`）的功能流程：

```
用户设置筛选条件（PE、PB、ROE等）
       │
       ▼
┌─────────────────┐
│ 前端发送 API    │
│ 请求到后端      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 后端查询数据库  │  ← 纯数据查询，可能不涉及 LLM
│ (akshare)       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 返回符合条件的  │
│ 股票列表        │
└────────┬────────┘
         │
         ▼ (可选)
┌─────────────────┐
│ 用户点击某只    │
│ 股票进行分析    │ ← 这里可能调用 china_market_analyst.py
└─────────────────┘
```

**待确认**：`china_market_analyst.py` 的实际调用场景

---

## 三、优化方案

### 3.1 Prompt 优化方案

**已设计两种模式的 Prompt**：

#### 模式 A：快速筛选评估（Quick Mode）

用于股票筛选页面的快速评估，目标：
- 输出控制在 300 字以内
- 强制结构化输出格式
- 聚焦关键指标，不展开详细分析

```markdown
## {股票代码} {股票名称} 快速评估

**投资评级**: ⭐⭐⭐⭐☆ (1-5星)
**核心逻辑**: （1句话，不超过30字）
**关键数据**:
| 指标 | 数值 | 行业对比 |
|------|------|----------|
| PE(TTM) | xx | 行业中位数xx |
| ROE | xx% | 行业中位数xx% |

**主要风险**: （1句话）
**操作建议**: 短期/中期/长期 + 建议仓位比例
```

#### 模式 B：深度分析（Deep Mode）

用于单只股票的深度分析，目标：
- 完整的分析报告
- 覆盖市场环境、基本面、技术面、资金面
- 给出明确的止盈止损建议

### 3.2 代码重构方案

**核心改动**：

```python
# 新增模式参数
def create_china_market_analyst(llm, toolkit, mode="quick"):
    """
    mode="quick" → 快速筛选评估
    mode="deep"  → 深度分析
    """

# 便捷工厂函数
def create_quick_analyst(llm, toolkit):
    return create_china_market_analyst(llm, toolkit, mode="quick")

def create_deep_analyst(llm, toolkit):
    return create_china_market_analyst(llm, toolkit, mode="deep")
```

### 3.3 评估体系设计

**评估维度**：

| 维度 | 指标 | 测量方法 |
|------|------|----------|
| 质量 | completeness_score | 检查必要章节是否存在 |
| 质量 | format_compliance | 输出格式是否符合要求 |
| 质量 | data_accuracy | 引用数据是否正确 |
| 效率 | input_tokens | 输入 Token 数 |
| 效率 | output_tokens | 输出 Token 数 |
| 效率 | response_time_ms | 响应时间 |
| 决策 | recommendation | 买入/持有/卖出 |
| 决策 | actual_return | 实际收益（回测） |

---

## 四、任务清单

### 任务 1：确认调用关系（优先级：高）

**目标**：确认 `china_market_analyst.py` 在项目中的实际调用位置和场景

**执行步骤**：
```bash
# 在项目根目录搜索
grep -r "china_market_analyst" --include="*.py" .
grep -r "create_china_market_analyst" --include="*.py" .
grep -r "ChinaMarketAnalyst" --include="*.py" .

# 搜索股票筛选相关的 API
grep -r "stock_screen" --include="*.py" .
grep -r "筛选" --include="*.py" .
```

**输出要求**：
- 列出所有调用位置
- 说明每个调用的触发场景（哪个 API、哪个页面）
- 确认是否需要修改其他文件以适配优化后的代码

---

### 任务 2：集成优化后的代码（优先级：高）

**目标**：将优化后的 `china_market_analyst_optimized.py` 集成到项目中

**执行步骤**：

1. **备份原文件**
   ```bash
   cp tradingagents/agents/analysts/china_market_analyst.py \
      tradingagents/agents/analysts/china_market_analyst.py.bak
   ```

2. **替换文件**
   ```bash
   cp china_market_analyst_optimized.py \
      tradingagents/agents/analysts/china_market_analyst.py
   ```

3. **检查依赖导入**
   - 确认所有 import 语句正确
   - 确认辅助函数 `_get_company_name_for_china_market` 可用

4. **修改调用方**
   - 如果其他文件直接调用 `create_china_market_analyst()`，需要确认参数兼容性
   - 考虑是否需要在调用处指定 `mode` 参数

**输出要求**：
- 修改后的文件清单
- 每个修改的具体内容
- 验证步骤和结果

---

### 任务 3：实现评估脚本（优先级：中）

**目标**：集成 `prompt_evaluator.py` 并运行首次评估

**执行步骤**：

1. **放置评估脚本**
   ```bash
   cp prompt_evaluator.py tradingagents/utils/
   ```

2. **创建测试用例数据**
   ```python
   # test_cases.json
   [
       {"ticker": "600519.SH", "name": "贵州茅台", "type": "白酒龙头"},
       {"ticker": "300750.SZ", "name": "宁德时代", "type": "新能源"},
       ...
   ]
   ```

3. **运行基线测试**
   - 用原版代码跑一遍测试用例
   - 记录各项指标作为 baseline

4. **运行对比测试**
   - 用优化版代码跑相同测试用例
   - 对比各项指标

**输出要求**：
- 测试报告（Markdown 格式）
- 指标对比表格
- 改进/退化分析

---

### 任务 4：确认前后端接口（优先级：中）

**目标**：确认优化后的代码与前端 API 的兼容性

**执行步骤**：

1. **查找 API 路由**
   ```bash
   grep -r "china_market" app/ --include="*.py"
   grep -r "@router" app/ --include="*.py"
   ```

2. **检查返回格式**
   - 原代码返回 `{"china_market_report": report, ...}`
   - 确认前端是否依赖特定字段

3. **测试 API 调用**
   - 使用 curl 或 Postman 调用相关 API
   - 验证返回格式正确

**输出要求**：
- API 接口清单
- 请求/响应示例
- 兼容性确认

---

### 任务 5：Docker 环境测试（优先级：中）

**目标**：在 Docker 环境中验证优化效果

**执行步骤**：

1. **进入后端容器**
   ```bash
   docker exec -it tradingagents-backend /bin/bash
   ```

2. **备份并替换文件**
   ```bash
   # 在容器内
   cd /app/tradingagents/agents/analysts/
   cp china_market_analyst.py china_market_analyst.py.bak
   # 从宿主机复制优化后的文件
   ```

3. **清理 Python 缓存**
   ```bash
   find /app -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
   ```

4. **重启服务**
   ```bash
   # 退出容器后
   docker restart tradingagents-backend
   ```

5. **验证功能**
   - 访问 Web 界面
   - 测试股票筛选功能
   - 测试单只股票分析功能

**输出要求**：
- 测试步骤记录
- 截图或日志
- 问题及解决方案

---

## 五、交付物清单

### 5.1 代码文件

| 文件名 | 说明 | 状态 |
|--------|------|------|
| china_market_analyst_optimized.py | 优化后的中国市场分析师代码 | ✅ 已完成 |
| prompt_evaluator.py | Prompt 效果评估工具 | ✅ 已完成 |
| docker_update_guide.md | Docker 环境更新指南 | ✅ 已完成 |

### 5.2 待完成

| 文件名 | 说明 | 负责人 |
|--------|------|--------|
| integration_report.md | 集成报告，记录所有修改 | Claude Code |
| evaluation_report.md | 评估报告，对比优化前后效果 | Claude Code |
| api_compatibility_check.md | API 兼容性检查报告 | Claude Code |

---

## 六、验收标准

### 6.1 功能验收

- [ ] 优化后的代码能正常运行，无报错
- [ ] 快速模式（quick）输出符合格式要求，字数 < 500
- [ ] 深度模式（deep）输出包含所有必要章节
- [ ] 与现有 API 兼容，前端无需修改

### 6.2 性能验收

- [ ] 输入 Token 数相比原版减少 30% 以上
- [ ] 输出质量评分（completeness）不低于原版
- [ ] 响应时间无明显增加（< 10%）

### 6.3 文档验收

- [ ] 所有修改都有记录
- [ ] 提供回滚方案
- [ ] 评估报告完整

---

## 七、附录

### 7.1 原始代码参考

原始 `china_market_analyst.py` 的关键结构：

```python
def create_china_market_analyst(llm, toolkit):
    def china_market_analyst_node(state):
        # 1. 获取股票信息
        ticker = state["company_of_interest"]
        market_info = StockUtils.get_market_info(ticker)
        company_name = _get_company_name_for_china_market(ticker, market_info)
        
        # 2. 定义工具
        tools = [toolkit.get_china_stock_data, ...]
        
        # 3. 构建 Prompt（问题所在：两层嵌套）
        system_message = """...(很长的详细说明)..."""
        prompt = ChatPromptTemplate.from_messages([
            ("system", "...\n{system_message}..."),
            MessagesPlaceholder(variable_name="messages"),
        ])
        
        # 4. 调用 LLM
        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])
        
        # 5. 返回结果
        return {
            "messages": [result],
            "china_market_report": report,
            "sender": "ChinaMarketAnalyst",
        }
    
    return china_market_analyst_node
```

### 7.2 优化后的代码结构

```python
# Prompt 模板集中管理
QUICK_SCREENING_PROMPT = """..."""
DEEP_ANALYSIS_PROMPT = """..."""

def create_china_market_analyst(llm, toolkit, mode="quick"):
    # 根据模式选择 Prompt
    system_message = QUICK_SCREENING_PROMPT if mode == "quick" else DEEP_ANALYSIS_PROMPT
    
    def china_market_analyst_node(state):
        # ... 精简的实现
        return {
            "messages": [result],
            "china_market_report": report,
            "sender": "ChinaMarketAnalyst",
            "analysis_mode": mode,  # 新增：标记分析模式
        }
    
    return china_market_analyst_node

# 便捷工厂函数
def create_quick_analyst(llm, toolkit):
    return create_china_market_analyst(llm, toolkit, mode="quick")

def create_deep_analyst(llm, toolkit):
    return create_china_market_analyst(llm, toolkit, mode="deep")
```

### 7.3 联系方式

如有问题，请在 GitHub Issues 中提问：
https://github.com/hsliuping/TradingAgents-CN/issues

---

**文档版本**: v1.0

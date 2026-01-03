# TradingAgents-CN Prompt Optimization

> A股市场分析师模块的 Prompt Engineering 优化方案

## 项目简介

本项目是对 [TradingAgents-CN](https://github.com/hsliuping/TradingAgents-CN) 项目中 `china_market_analyst.py` 模块的优化，主要解决以下问题：

1. **Prompt 冗余**: 原代码存在两层 Prompt 嵌套，造成 Token 浪费
2. **职责边界不清**: 单个 Agent 承担过多分析职责
3. **缺乏结构化输出**: 输出格式不统一，难以解析

## 优化内容

### 1. Prompt 结构重构
- 集中管理 Prompt 模板，便于维护和 A/B 测试
- 明确职责边界，聚焦中国市场特色分析

### 2. 分析模式分离

| 模式 | 使用场景 | 输出特点 |
|------|----------|----------|
| **快速模式 (quick)** | 股票筛选页面 | 300字以内，结构化表格 |
| **深度模式 (deep)** | 单只股票分析 | 完整报告，含止盈止损 |

### 3. 结构化输出格式

**快速模式输出示例：**
```markdown
## 600519 贵州茅台 快速评估

**投资评级**: ⭐⭐⭐⭐☆ (4星)
**核心逻辑**: 白酒龙头，估值合理，业绩稳健

**关键数据**:
| 指标 | 数值 | 行业对比 |
|------|------|----------|
| PE(TTM) | 28 | 行业中位数35 |
| ROE | 32% | 行业中位数18% |

**主要风险**: 消费复苏不及预期
**操作建议**: 中期持有，建议仓位10%
```

### 4. 评估体系

提供完整的 A/B 测试评估工具，支持：
- 输出质量评估（完整性、格式符合度）
- Token 效率对比
- 回测验证

## 文件说明

| 文件 | 说明 |
|------|------|
| `china_market_analyst_optimized.py` | 优化后的中国市场分析师代码 |
| `prompt_evaluator.py` | Prompt 效果评估工具 |
| `TradingAgents_CN_Optimization_PRD.md` | 完整的优化需求文档 |

## 使用方法

### 集成到 TradingAgents-CN

```bash
# 1. 备份原文件
cp tradingagents/agents/analysts/china_market_analyst.py \
   tradingagents/agents/analysts/china_market_analyst.py.bak

# 2. 替换文件
cp china_market_analyst_optimized.py \
   tradingagents/agents/analysts/china_market_analyst.py

# 3. 重启服务
docker restart tradingagents-backend
```

### 运行评估

```python
from prompt_evaluator import PromptEvaluator

evaluator = PromptEvaluator()
results = evaluator.run_ab_test(
    analyst_a=original_analyst,
    analyst_b=optimized_analyst,
    mode="quick"
)
```

## 预期效果

| 指标 | 优化目标 |
|------|----------|
| 输入 Token 数 | 减少 30%+ |
| 输出质量评分 | 不低于原版 |
| 响应时间 | 无明显增加 |

## 技术栈

- Python 3.10+
- LangChain
- Pandas (评估工具)

## 作者

基于 TradingAgents-CN 项目优化

## License

MIT License

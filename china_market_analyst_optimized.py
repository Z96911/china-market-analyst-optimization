"""
TradingAgents-CN 股票筛选模块优化版
=====================================

优化内容：
1. 重构 Prompt 结构，明确职责边界
2. 分离"快速筛选评估"和"深度分析"两种模式
3. 添加结构化输出格式
4. 优化 Token 使用效率

使用方法：
1. 备份原文件: cp tradingagents/agents/analysts/china_market_analyst.py tradingagents/agents/analysts/china_market_analyst.py.bak
2. 替换文件: cp china_market_analyst_optimized.py tradingagents/agents/analysts/china_market_analyst.py
3. 重启服务

"""

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
import time
import json

# 导入统一日志系统
from tradingagents.utils.logging_init import get_logger
logger = get_logger("default")

# 导入Google工具调用处理器
from tradingagents.agents.utils.google_tool_handler import GoogleToolCallHandler


# ============================================================================
# Prompt 模板定义（集中管理，便于维护和 A/B 测试）
# ============================================================================

# 快速筛选模式的 Prompt（用于股票筛选页面）
QUICK_SCREENING_PROMPT = """您是一位专注A股市场的**快速评估专家**，为股票筛选模块提供简要分析。

【核心任务】
对筛选出的股票进行快速评估，在2-3分钟内给出投资价值判断。

【评估维度】（每项用1-2句话概括即可）

1. **估值定位**
   - 当前PE/PB相对于行业中位数的位置（偏高/合理/偏低）
   - 相对于自身历史估值的分位（近3年）

2. **成长质量**  
   - 最近2个季度的营收/净利增速
   - 增长是否可持续（一次性收益 vs 主业增长）

3. **资金信号**
   - 近5日北向资金流向
   - 主力资金净流入/流出趋势

4. **风险速查**
   - ST/*ST 状态
   - 大股东质押比例（>50%需警示）
   - 近期是否有减持计划公告

【输出格式】（严格遵守）
```
## {股票代码} {股票名称} 快速评估

**投资评级**: ⭐⭐⭐⭐☆ (1-5星)

**核心逻辑**: （1句话，不超过30字）

**关键数据**:
| 指标 | 数值 | 行业对比 |
|------|------|----------|
| PE(TTM) | xx | 行业中位数xx |
| ROE | xx% | 行业中位数xx% |
| 营收增速 | xx% | - |

**主要风险**: （1句话）

**操作建议**: 短期/中期/长期 + 建议仓位比例
```

【注意事项】
- 这是快速筛选场景，请控制篇幅在300字以内
- 不要展开详细分析，突出关键结论
- 如果数据不足，直接说明而非猜测"""


# 深度分析模式的 Prompt（用于单独的深度分析功能）
DEEP_ANALYSIS_PROMPT = """您是一位资深的A股市场分析师，负责提供深度投资分析报告。

【分析框架】

## 第一部分：市场环境（权重20%）
1. 宏观政策：当前货币/财政政策对该行业的影响
2. 板块位置：该股票所属板块在近期轮动中的位置
3. 市场情绪：整体风险偏好（进攻/防守）

## 第二部分：公司基本面（权重40%）
1. 商业模式：核心竞争力和护城河
2. 财务健康：
   - 盈利能力：ROE趋势（杜邦分析三要素）
   - 现金流质量：经营性现金流/净利润比值
   - 资产质量：商誉/总资产、应收账款周转
3. 成长空间：行业天花板和公司市占率提升潜力

## 第三部分：技术面（权重20%）
1. 趋势判断：均线系统排列
2. 量价配合：放量/缩量特征
3. 关键位置：支撑位和压力位

## 第四部分：资金面（权重20%）
1. 北向资金：持仓变化趋势
2. 融资余额：杠杆资金动向
3. 大宗交易：机构调仓信号

【中国市场特殊考量】
- 涨跌停制度对买卖时机的影响
- 注册制下的估值重构
- 政策敏感型行业的特殊风险

【输出要求】
1. 每个部分给出明确的评分（1-10分）
2. 最终综合评分和投资建议
3. 明确的止盈止损位置建议
4. 附上数据来源和分析时间"""


# 股票筛选器的 Prompt
STOCK_SCREENER_PROMPT = """您是一位专业的A股量化筛选专家，负责根据用户设定的条件筛选股票。

【筛选能力】

1. **估值筛选**
   - PE/PB/PS/PEG 范围
   - 相对估值（vs 行业、vs 历史）

2. **财务筛选**  
   - ROE/ROA 阈值
   - 营收/净利增速
   - 资产负债率
   - 现金流质量

3. **技术筛选**
   - 均线形态（多头/空头排列）
   - 突破/回调形态
   - 成交量特征

4. **特殊筛选**
   - 排除ST/*ST
   - 排除次新股（上市<1年）
   - 排除高质押（>50%）
   - 北向资金持仓要求

【输出格式】
对于每只筛选出的股票，提供：
1. 股票代码和名称
2. 符合的筛选条件（匹配度）
3. 关键财务指标速览
4. 一句话推荐理由

【注意】
- 筛选结果按匹配度排序
- 单次筛选不超过20只
- 明确标注数据截止日期"""


# ============================================================================
# 辅助函数
# ============================================================================

def _get_company_name_for_china_market(ticker: str, market_info: dict) -> str:
    """
    为中国市场分析师获取公司名称（保持原有逻辑不变）
    """
    try:
        if market_info['is_china']:
            from tradingagents.dataflows.interface import get_china_stock_info_unified
            stock_info = get_china_stock_info_unified(ticker)
            
            logger.debug(f"📊 [中国市场分析师] 获取股票信息返回: {stock_info[:200] if stock_info else 'None'}...")
            
            if stock_info and "股票名称:" in stock_info:
                company_name = stock_info.split("股票名称:")[1].split("\n")[0].strip()
                logger.info(f"✅ [中国市场分析师] 成功获取中国股票名称: {ticker} -> {company_name}")
                return company_name
            else:
                logger.warning(f"⚠️ [中国市场分析师] 无法从统一接口解析股票名称: {ticker}，尝试降级方案")
                try:
                    from tradingagents.dataflows.data_source_manager import get_china_stock_info_unified as get_info_dict
                    info_dict = get_info_dict(ticker)
                    if info_dict and info_dict.get('name'):
                        company_name = info_dict['name']
                        logger.info(f"✅ [中国市场分析师] 降级方案成功获取股票名称: {ticker} -> {company_name}")
                        return company_name
                except Exception as e:
                    logger.error(f"❌ [中国市场分析师] 降级方案也失败: {e}")
                
                logger.error(f"❌ [中国市场分析师] 所有方案都无法获取股票名称: {ticker}")
                return f"股票代码{ticker}"
                
        elif market_info['is_hk']:
            try:
                from tradingagents.dataflows.providers.hk.improved_hk import get_hk_company_name_improved
                company_name = get_hk_company_name_improved(ticker)
                logger.debug(f"📊 [中国市场分析师] 使用改进港股工具获取名称: {ticker} -> {company_name}")
                return company_name
            except Exception as e:
                logger.debug(f"📊 [中国市场分析师] 改进港股工具获取名称失败: {e}")
                clean_ticker = ticker.replace('.HK', '').replace('.hk', '')
                return f"港股{clean_ticker}"
                
        elif market_info['is_us']:
            us_stock_names = {
                'AAPL': '苹果公司', 'TSLA': '特斯拉', 'NVDA': '英伟达',
                'MSFT': '微软', 'GOOGL': '谷歌', 'AMZN': '亚马逊',
                'META': 'Meta', 'NFLX': '奈飞'
            }
            company_name = us_stock_names.get(ticker.upper(), f"美股{ticker}")
            logger.debug(f"📊 [中国市场分析师] 美股名称映射: {ticker} -> {company_name}")
            return company_name
        else:
            return f"股票{ticker}"
            
    except Exception as e:
        logger.error(f"❌ [中国市场分析师] 获取公司名称失败: {e}")
        return f"股票{ticker}"


def _get_tool_names(tools: list) -> str:
    """安全地获取工具名称列表"""
    tool_names = []
    for tool in tools:
        if hasattr(tool, 'name'):
            tool_names.append(tool.name)
        elif hasattr(tool, '__name__'):
            tool_names.append(tool.__name__)
        else:
            tool_names.append(str(tool))
    return ", ".join(tool_names)


# ============================================================================
# 主要函数：创建分析师节点
# ============================================================================

def create_china_market_analyst(llm, toolkit, mode: str = "quick"):
    """
    创建中国市场分析师
    
    Args:
        llm: 语言模型实例
        toolkit: 工具集
        mode: 分析模式
            - "quick": 快速筛选评估（默认，用于股票筛选页面）
            - "deep": 深度分析（用于单独的深度分析功能）
    
    Returns:
        分析师节点函数
    """
    
    # 根据模式选择 Prompt
    if mode == "deep":
        system_message = DEEP_ANALYSIS_PROMPT
        analyst_name = "中国市场深度分析师"
    else:
        system_message = QUICK_SCREENING_PROMPT
        analyst_name = "中国市场快速评估师"
    
    def china_market_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        
        # 获取股票市场信息
        from tradingagents.utils.stock_utils import StockUtils
        market_info = StockUtils.get_market_info(ticker)
        
        # 获取公司名称
        company_name = _get_company_name_for_china_market(ticker, market_info)
        logger.info(f"[{analyst_name}] 分析标的: {ticker} ({company_name})")
        
        # 定义工具集
        tools = [
            toolkit.get_china_stock_data,
            toolkit.get_china_market_overview,
            toolkit.get_YFin_data,
        ]
        
        # 构建 Prompt（精简的系统指令，避免重复）
        prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                "{system_message}\n\n"
                "---\n"
                "当前日期: {current_date}\n"
                "分析标的: {ticker} ({company_name})\n"
                "可用工具: {tool_names}\n"
                "---\n"
                "请用中文输出分析结果。",
            ),
            MessagesPlaceholder(variable_name="messages"),
        ])
        
        # 填充变量
        prompt = prompt.partial(
            system_message=system_message,
            current_date=current_date,
            ticker=ticker,
            company_name=company_name,
            tool_names=_get_tool_names(tools)
        )
        
        # 调用 LLM
        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])
        
        # 处理 Google 模型的工具调用
        if GoogleToolCallHandler.is_google_model(llm):
            logger.info(f"📊 [{analyst_name}] 检测到Google模型，使用统一工具调用处理器")
            
            analysis_prompt_template = GoogleToolCallHandler.create_analysis_prompt(
                ticker=ticker,
                company_name=company_name,
                analyst_type=analyst_name,
                specific_requirements="请严格按照输出格式要求返回结果。"
            )
            
            report, messages = GoogleToolCallHandler.handle_google_tool_calls(
                result=result,
                llm=llm,
                tools=tools,
                state=state,
                analysis_prompt_template=analysis_prompt_template,
                analyst_name=analyst_name
            )
        else:
            logger.debug(f"📊 [{analyst_name}] 非Google模型，使用标准处理逻辑")
            report = ""
            if len(result.tool_calls) == 0:
                report = result.content
        
        return {
            "messages": [result],
            "china_market_report": report,
            "sender": "ChinaMarketAnalyst",
            "analysis_mode": mode,  # 新增：标记分析模式
        }
    
    return china_market_analyst_node


def create_china_stock_screener(llm, toolkit):
    """
    创建中国股票筛选器
    """
    
    def china_stock_screener_node(state):
        current_date = state["trade_date"]
        
        tools = [
            toolkit.get_china_market_overview,
        ]
        
        # 使用专门的筛选器 Prompt
        prompt = ChatPromptTemplate.from_messages([
            (
                "system", 
                "{system_message}\n\n"
                "---\n"
                "当前日期: {current_date}\n"
                "可用工具: {tool_names}\n"
                "---\n"
                "请用中文输出筛选结果。",
            ),
            MessagesPlaceholder(variable_name="messages"),
        ])
        
        prompt = prompt.partial(
            system_message=STOCK_SCREENER_PROMPT,
            current_date=current_date,
            tool_names=_get_tool_names(tools)
        )
        
        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])
        
        return {
            "messages": [result],
            "stock_screening_report": result.content,
            "sender": "ChinaStockScreener",
        }
    
    return china_stock_screener_node


# ============================================================================
# 便捷工厂函数
# ============================================================================

def create_quick_analyst(llm, toolkit):
    """创建快速评估分析师（股票筛选页面使用）"""
    return create_china_market_analyst(llm, toolkit, mode="quick")


def create_deep_analyst(llm, toolkit):
    """创建深度分析师（深度分析功能使用）"""
    return create_china_market_analyst(llm, toolkit, mode="deep")

"""
Prompt 效果评估工具
==================

用于评估优化后的 Prompt 相比原版的改进效果。

使用方法：
1. 将此文件放到项目根目录
2. 运行: python prompt_evaluator.py

评估维度：
1. 输出质量（完整性、准确性）
2. Token 效率（输入/输出 token 数）
3. 响应时间
4. 决策效果（回测收益）
"""

import json
import time
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
import pandas as pd
from langchain_core.messages import HumanMessage, ToolMessage


@dataclass
class EvaluationResult:
    """单次评估结果"""
    test_case_id: str
    prompt_version: str
    ticker: str
    date: str
    
    # 质量指标
    completeness_score: float      # 内容完整性 (0-1)
    format_compliance: float       # 格式符合度 (0-1)
    data_accuracy: float           # 数据准确性 (0-1)
    
    # 效率指标
    input_tokens: int
    output_tokens: int
    response_time_ms: int
    
    # 决策指标
    recommendation: str            # 买入/持有/卖出
    confidence: float              # 置信度 (0-1)
    
    # 实际结果（回测时填充）
    actual_return_5d: Optional[float] = None
    actual_return_10d: Optional[float] = None
    
    def to_dict(self):
        return asdict(self)


class PromptEvaluator:
    """Prompt 效果评估器"""
    
    # 测试用例：覆盖不同类型的股票
    DEFAULT_TEST_CASES = [
        # 大盘蓝筹
        {"ticker": "600519.SH", "name": "贵州茅台", "type": "白酒龙头"},
        {"ticker": "601318.SH", "name": "中国平安", "type": "保险龙头"},
        {"ticker": "000858.SZ", "name": "五粮液", "type": "白酒"},
        
        # 科技成长
        {"ticker": "300750.SZ", "name": "宁德时代", "type": "新能源"},
        {"ticker": "002415.SZ", "name": "海康威视", "type": "安防"},
        
        # 周期股
        {"ticker": "601899.SH", "name": "紫金矿业", "type": "有色金属"},
        {"ticker": "600028.SH", "name": "中国石化", "type": "石油"},
        
        # 中小盘
        {"ticker": "300059.SZ", "name": "东方财富", "type": "券商互联网"},
        {"ticker": "002594.SZ", "name": "比亚迪", "type": "新能源汽车"},
        
        # 特殊情况
        {"ticker": "000001.SZ", "name": "平安银行", "type": "银行"},
    ]
    
    # 必须包含的关键内容（用于检查完整性）
    REQUIRED_SECTIONS = {
        "quick": [
            "投资评级",
            "核心逻辑", 
            "关键数据",
            "风险",
        ],
        "deep": [
            "市场环境",
            "基本面",
            "技术面",
            "资金面",
            "投资建议",
        ]
    }
    
    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.results: List[EvaluationResult] = []
        
    def check_completeness(self, output: str, mode: str = "quick") -> float:
        """
        检查输出的完整性
        
        Args:
            output: LLM 输出内容
            mode: "quick" 或 "deep"
            
        Returns:
            完整性得分 (0-1)
        """
        required = self.REQUIRED_SECTIONS.get(mode, self.REQUIRED_SECTIONS["quick"])
        found = sum(1 for section in required if section in output)
        return found / len(required)
    
    def check_format_compliance(self, output: str, mode: str = "quick") -> float:
        """
        检查输出格式是否符合要求
        
        Args:
            output: LLM 输出内容
            mode: 分析模式
            
        Returns:
            格式符合度得分 (0-1)
        """
        score = 0.0
        checks = []
        
        if mode == "quick":
            # 快速模式的格式检查
            checks = [
                ("##" in output, 0.2),                    # 有标题
                ("⭐" in output or "星" in output, 0.2),   # 有评级
                ("|" in output and "---" in output, 0.3), # 有表格
                (len(output) < 1500, 0.3),                # 简洁性（<1500字符）
            ]
        else:
            # 深度模式的格式检查
            checks = [
                ("##" in output, 0.15),                   # 有章节标题
                ("评分" in output or "分" in output, 0.2), # 有评分
                ("|" in output, 0.15),                    # 有表格
                ("止盈" in output or "止损" in output, 0.2), # 有操作建议
                (len(output) > 800, 0.3),                 # 充分性（>800字符）
            ]
        
        for condition, weight in checks:
            if condition:
                score += weight
                
        return min(score, 1.0)
    
    def check_data_accuracy(self, output: str, ground_truth: Dict) -> float:
        """
        检查数据准确性
        
        Args:
            output: LLM 输出内容
            ground_truth: 真实数据字典 {"PE": 30, "ROE": 25, ...}
            
        Returns:
            数据准确性得分 (0-1)
        """
        if not ground_truth:
            return 0.5  # 没有真实数据时返回中性分数
        
        correct = 0
        total = len(ground_truth)
        
        for key, true_value in ground_truth.items():
            # 在输出中查找该指标的值
            # 这里使用简化的匹配逻辑，实际使用时可能需要更复杂的解析
            if str(true_value) in output or key in output:
                correct += 0.5  # 部分分
                # TODO: 更精确的数值比对
                
        return correct / total if total > 0 else 0.5
    
    def extract_recommendation(self, output: str) -> tuple:
        """
        从输出中提取投资建议
        
        Returns:
            (recommendation, confidence)
        """
        recommendation = "持有"  # 默认
        confidence = 0.5
        
        # 简单的关键词匹配
        if "强烈推荐" in output or "买入" in output or "⭐⭐⭐⭐⭐" in output:
            recommendation = "买入"
            confidence = 0.8
        elif "推荐" in output or "⭐⭐⭐⭐" in output:
            recommendation = "买入"
            confidence = 0.6
        elif "回避" in output or "卖出" in output or "⭐" in output:
            recommendation = "卖出"
            confidence = 0.7
        elif "中性" in output or "观望" in output:
            recommendation = "持有"
            confidence = 0.5
            
        return recommendation, confidence
    
    def _execute_tool_calls(self, tool_calls, toolkit):
        """执行工具调用并返回结果"""
        tool_results = []

        # 工具名称到函数的映射
        tool_map = {
            "get_china_stock_data": toolkit.get_china_stock_data,
            "get_china_market_overview": toolkit.get_china_market_overview,
            "get_YFin_data": toolkit.get_YFin_data,
        }

        for tc in tool_calls:
            tool_name = tc.get("name", "")
            tool_args = tc.get("args", {})
            tool_id = tc.get("id", "")

            if tool_name in tool_map:
                try:
                    tool_func = tool_map[tool_name]
                    if hasattr(tool_func, 'invoke'):
                        result = tool_func.invoke(tool_args)
                    else:
                        result = tool_func(**tool_args)

                    tool_results.append(ToolMessage(
                        content=str(result)[:5000],
                        tool_call_id=tool_id
                    ))
                except Exception as e:
                    tool_results.append(ToolMessage(
                        content=f"工具调用失败: {e}",
                        tool_call_id=tool_id
                    ))
            else:
                tool_results.append(ToolMessage(
                    content=f"未知工具: {tool_name}",
                    tool_call_id=tool_id
                ))

        return tool_results

    def run_single_evaluation(
        self,
        analyst_func,
        ticker: str,
        date: str,
        prompt_version: str,
        mode: str = "quick",
        ground_truth: Dict = None,
        toolkit = None
    ) -> EvaluationResult:
        """
        运行单次评估

        Args:
            analyst_func: 分析师函数
            ticker: 股票代码
            date: 分析日期
            prompt_version: Prompt 版本标识
            mode: 分析模式
            ground_truth: 真实数据（用于准确性检验）
            toolkit: 工具集（用于执行工具调用）

        Returns:
            EvaluationResult
        """
        # 构造输入状态
        state = {
            "trade_date": date,
            "company_of_interest": ticker,
            "messages": [HumanMessage(content=f"请分析股票 {ticker}")],
        }

        # 计时
        start_time = time.time()

        # 调用分析师
        try:
            result = analyst_func(state)
            output = result.get("china_market_report", "")

            # 如果没有报告，检查是否有工具调用需要执行
            if not output and toolkit:
                messages = result.get("messages", [])
                if messages and hasattr(messages[0], "tool_calls") and messages[0].tool_calls:
                    # 执行工具调用
                    tool_results = self._execute_tool_calls(messages[0].tool_calls, toolkit)

                    # 更新 state 并再次调用分析师
                    state["messages"] = state["messages"] + [messages[0]] + tool_results
                    result = analyst_func(state)
                    output = result.get("china_market_report", "")

                    # 如果还是没有报告，从 messages 中提取
                    if not output:
                        for msg in result.get("messages", []):
                            if hasattr(msg, "content") and msg.content:
                                output = msg.content
                                break
        except Exception as e:
            print(f"❌ 分析 {ticker} 失败: {e}")
            output = ""

        response_time_ms = int((time.time() - start_time) * 1000)
        
        # 评估各项指标
        completeness = self.check_completeness(output, mode)
        format_score = self.check_format_compliance(output, mode)
        accuracy = self.check_data_accuracy(output, ground_truth or {})
        recommendation, confidence = self.extract_recommendation(output)
        
        # 估算 token 数（简化计算：中文约 2 字符/token）
        input_tokens = len(str(state)) // 2
        output_tokens = len(output) // 2
        
        # 生成测试用例 ID
        test_case_id = hashlib.md5(f"{ticker}_{date}_{prompt_version}".encode()).hexdigest()[:8]
        
        return EvaluationResult(
            test_case_id=test_case_id,
            prompt_version=prompt_version,
            ticker=ticker,
            date=date,
            completeness_score=completeness,
            format_compliance=format_score,
            data_accuracy=accuracy,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            response_time_ms=response_time_ms,
            recommendation=recommendation,
            confidence=confidence,
        )
    
    def run_ab_test(
        self,
        analyst_a,  # 原版分析师
        analyst_b,  # 新版分析师
        test_cases: List[Dict] = None,
        date: str = None,
        mode: str = "quick",
        toolkit = None
    ) -> pd.DataFrame:
        """
        运行 A/B 测试

        Args:
            analyst_a: 原版分析师函数
            analyst_b: 新版分析师函数
            test_cases: 测试用例列表
            date: 测试日期
            mode: 分析模式
            toolkit: 工具集（用于执行工具调用）

        Returns:
            对比结果 DataFrame
        """
        test_cases = test_cases or self.DEFAULT_TEST_CASES
        date = date or datetime.now().strftime("%Y-%m-%d")

        results_a = []
        results_b = []

        print(f"🔬 开始 A/B 测试，共 {len(test_cases)} 个测试用例")
        print("=" * 50)

        for i, case in enumerate(test_cases, 1):
            ticker = case["ticker"]
            name = case.get("name", ticker)

            print(f"\n[{i}/{len(test_cases)}] 测试 {ticker} ({name})")

            # 运行版本 A
            print("  ├─ 运行版本 A (原版)...", end=" ")
            result_a = self.run_single_evaluation(
                analyst_a, ticker, date, "original", mode, toolkit=toolkit
            )
            results_a.append(result_a)
            print(f"完成 (耗时 {result_a.response_time_ms}ms)")

            # 运行版本 B
            print("  └─ 运行版本 B (优化版)...", end=" ")
            result_b = self.run_single_evaluation(
                analyst_b, ticker, date, "optimized", mode, toolkit=toolkit
            )
            results_b.append(result_b)
            print(f"完成 (耗时 {result_b.response_time_ms}ms)")
        
        # 汇总结果
        df_a = pd.DataFrame([r.to_dict() for r in results_a])
        df_b = pd.DataFrame([r.to_dict() for r in results_b])
        
        # 计算统计指标
        summary = self._compute_summary(df_a, df_b)
        
        print("\n" + "=" * 50)
        print("📊 A/B 测试结果汇总")
        print("=" * 50)
        print(summary.to_string())
        
        return summary
    
    def _compute_summary(self, df_a: pd.DataFrame, df_b: pd.DataFrame) -> pd.DataFrame:
        """计算汇总统计"""
        metrics = [
            "completeness_score",
            "format_compliance", 
            "data_accuracy",
            "output_tokens",
            "response_time_ms",
        ]
        
        summary_data = []
        for metric in metrics:
            mean_a = df_a[metric].mean()
            mean_b = df_b[metric].mean()
            improvement = ((mean_b - mean_a) / mean_a * 100) if mean_a != 0 else 0
            
            summary_data.append({
                "指标": metric,
                "原版 (A)": f"{mean_a:.3f}",
                "优化版 (B)": f"{mean_b:.3f}",
                "提升%": f"{improvement:+.1f}%",
            })
        
        return pd.DataFrame(summary_data)


class BacktestEvaluator:
    """
    回测评估器
    用于评估分析师建议的实际投资效果
    """
    
    def __init__(self, data_source=None):
        """
        Args:
            data_source: 数据源（如 akshare, tushare）
        """
        self.data_source = data_source
        
    def get_actual_return(self, ticker: str, date: str, hold_days: int) -> float:
        """
        获取实际收益率
        
        Args:
            ticker: 股票代码
            date: 买入日期
            hold_days: 持有天数
            
        Returns:
            收益率（如 0.05 表示 5%）
        """
        # TODO: 接入实际数据源
        # 示例实现
        try:
            import akshare as ak
            
            # 获取股票历史数据
            df = ak.stock_zh_a_hist(
                symbol=ticker.split('.')[0],
                period="daily",
                start_date=date.replace('-', ''),
                adjust="qfq"
            )
            
            if len(df) < hold_days + 1:
                return 0.0
            
            buy_price = df.iloc[0]['收盘']
            sell_price = df.iloc[hold_days]['收盘']
            
            return (sell_price - buy_price) / buy_price
            
        except Exception as e:
            print(f"⚠️ 获取 {ticker} 收益率失败: {e}")
            return 0.0
    
    def evaluate_recommendations(
        self, 
        evaluation_results: List[EvaluationResult],
        hold_days: int = 5
    ) -> pd.DataFrame:
        """
        评估投资建议的实际效果
        
        Args:
            evaluation_results: 评估结果列表
            hold_days: 持有天数
            
        Returns:
            包含实际收益的 DataFrame
        """
        results = []
        
        for eval_result in evaluation_results:
            actual_return = self.get_actual_return(
                eval_result.ticker,
                eval_result.date,
                hold_days
            )
            
            # 计算策略收益
            if eval_result.recommendation == "买入":
                strategy_return = actual_return
            elif eval_result.recommendation == "卖出":
                strategy_return = -actual_return  # 做空收益
            else:
                strategy_return = 0  # 持有不操作
            
            results.append({
                "ticker": eval_result.ticker,
                "date": eval_result.date,
                "recommendation": eval_result.recommendation,
                "confidence": eval_result.confidence,
                "actual_return": actual_return,
                "strategy_return": strategy_return,
                "prompt_version": eval_result.prompt_version,
            })
        
        df = pd.DataFrame(results)
        
        # 按版本分组统计
        summary = df.groupby("prompt_version").agg({
            "strategy_return": ["mean", "std", "count"],
            "actual_return": "mean",
        }).round(4)
        
        print("\n📈 回测结果汇总")
        print("=" * 50)
        print(summary)
        
        # 计算胜率
        for version in df["prompt_version"].unique():
            version_df = df[df["prompt_version"] == version]
            win_rate = (version_df["strategy_return"] > 0).mean()
            print(f"\n{version} 胜率: {win_rate:.1%}")
        
        return df


# ============================================================================
# 使用示例
# ============================================================================

def example_usage():
    """使用示例"""
    
    print("""
    ╔══════════════════════════════════════════════════════════════╗
    ║              Prompt 效果评估工具 - 使用示例                    ║
    ╚══════════════════════════════════════════════════════════════╝
    
    1. 基本使用流程：
    
    ```python
    from prompt_evaluator import PromptEvaluator
    
    # 创建评估器
    evaluator = PromptEvaluator()
    
    # 假设你有两个分析师函数
    from tradingagents.agents.analysts.china_market_analyst import create_china_market_analyst
    from china_market_analyst_optimized import create_quick_analyst
    
    # 运行 A/B 测试
    results = evaluator.run_ab_test(
        analyst_a=original_analyst,
        analyst_b=optimized_analyst,
        mode="quick"
    )
    ```
    
    2. 回测评估：
    
    ```python
    from prompt_evaluator import BacktestEvaluator
    
    backtest = BacktestEvaluator()
    backtest_results = backtest.evaluate_recommendations(
        evaluation_results,
        hold_days=5
    )
    ```
    
    3. 自定义测试用例：
    
    ```python
    custom_cases = [
        {"ticker": "600519.SH", "name": "贵州茅台"},
        {"ticker": "000858.SZ", "name": "五粮液"},
    ]
    
    results = evaluator.run_ab_test(
        analyst_a, analyst_b,
        test_cases=custom_cases
    )
    ```
    """)


if __name__ == "__main__":
    example_usage()

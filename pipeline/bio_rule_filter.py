"""Level 1/2 BIO 规则快筛 — 零 LLM 成本, 覆盖 ~70% 明确 case。"""

# TODO: 实现规则快筛引擎
# 1. 加载 config/bio_rules.yaml
# 2. Level 1: Link DNA 指纹匹配 (出现即 95%+ 为创作者)
# 3. Level 2: 语义矩阵 (身份/动作/工具关键词 + Emoji 信号)
# 4. 误杀防范 (fan account / studio 排除)
# 5. 返回: {"passed": bool|None, "level": 1|2|0, "type": str, "confidence": float, "signals": list}

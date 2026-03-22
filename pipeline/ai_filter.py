"""Level 3 国产大模型 Bio 过滤 — 处理规则快筛未覆盖的灰区 BIO (~30%)。

所有模型统一通过 OpenAI SDK 兼容接口调用，仅切换 base_url + api_key + model。
支持 Kimi K2.5 / Qwen3.5-Plus / DeepSeek / 智谱 GLM / MiniMax 五 provider。
利用长上下文 (256K) 一次批量处理 50 条 Bio。
"""

# TODO: 实现 AI 过滤服务
# 1. 统一 LLMClient 类 (base_url, api_key, model)
# 2. 批量 Prompt: 一次处理 50 条 Bio, 输出 JSON 数组
# 3. 降级链: Kimi -> Qwen -> DeepSeek -> GLM
# 4. 异步并发: Semaphore(10)
# 5. 错误重试: 3 次指数退避
# 6. 成本追踪: response.usage -> cost_tracking 表

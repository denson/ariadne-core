Here is a comprehensive breakdown of API pricing across the major frontier model providers and open-weight serving platforms as of April 2026. 

This report focuses strictly on API/developer costs (priced per 1 million tokens) rather than consumer subscription tiers. For vision models, most frontier providers have shifted to natively multimodal pricing, where images are simply converted to a set token count against the base text model rate.

## Google Gemini
Google's Gemini ecosystem is natively multimodal, meaning vision and audio capabilities are processed seamlessly through the core models, with pricing reflecting standard text/image inputs.

| Model Tier | Input (per 1M) | Output (per 1M) | Best Use Case |
| :--- | :--- | :--- | :--- |
| **Gemini 3.1 Pro** (≤200K ctx) | $2.00 | $12.00 | Complex reasoning, multi-step logic, high-res vision |
| **Gemini 2.5 Pro** | $1.25 | $10.00 | Balanced capability and cost for general agents |
| **Gemini 3 Flash** | $0.50 | $3.00 | High-speed multimodal processing |
| **Gemini 2.5 Flash** | $0.30 | $2.50 | General fast routing and generation |
| **Gemini 2.5 Flash-Lite** | $0.10 | $0.40 | Simple, ultra-high-volume text classification |
| **Gemini Embedding** (Text) | $0.15 | - | Semantic search, grounding, and knowledge graphs |

*Note: Google offers substantial context caching discounts (often reducing input costs significantly for long, repeated system prompts) and a generous free tier for prototyping in AI Studio.*

## OpenAI
OpenAI has aggressively restructured pricing with the release of the GPT-5 family, while continuing to serve extremely efficient models for high-volume pipelines.

| Model Tier | Input (per 1M) | Output (per 1M) | Best Use Case |
| :--- | :--- | :--- | :--- |
| **GPT-5** | $1.25 | $10.00 | Flagship general-purpose, coding, advanced vision |
| **GPT-4o** (Legacy) | $2.50 | $10.00 | Broad ecosystem support and multimodal tasks |
| **GPT-5 Mini** | $0.25 | $2.00 | Agentic workflows, mid-tier analysis |
| **GPT-4o mini** | $0.15 | $0.60 | Budget-friendly text/vision processing |
| **GPT-4.1 Nano** | $0.10 | $0.40 | Ultra-low-cost classification and simple routing |
| **text-embedding-3-small** | $0.02 | - | Highly efficient standard retrieval and RAG |
| **text-embedding-3-large** | $0.13 | - | High-dimensional semantic precision (3072 dims) |

## Anthropic (Claude)
Anthropic's Claude 4.5 and 4.6 families rely heavily on prompt caching (up to 90% savings) to remain competitive. They currently lack a native embedding API, so developers typically pair Claude with Voyage AI or OpenAI embeddings for vectorization. Vision is inherently supported across the lineup.

| Model Tier | Input (per 1M) | Output (per 1M) | Best Use Case |
| :--- | :--- | :--- | :--- |
| **Claude Opus 4.6** | $5.00 | $25.00 | Peak intelligence, coding excellence, complex data |
| **Claude Sonnet 4.6** | $3.00 | $15.00 | The "sweet spot" for deep coding and workflow speed |
| **Claude Haiku 4.5** | $1.00 | $5.00 | Fast extraction and rapid tool use |

---

## Open Model Providers
For self-hosting or managed open-weight models, platforms like Together AI and Groq offer highly competitive serverless inference, often charging identical rates for input and output.

| Provider / Model | Input (per 1M) | Output (per 1M) | Capabilities / Tier |
| :--- | :--- | :--- | :--- |
| **Together AI / Llama 3.3 70B** | $0.88 | $0.88 | Flagship open-weight text capability |
| **Together AI / Llama 3 8B Lite** | $0.10 | $0.10 | Fast routing, simple entity extraction |
| **Together AI / Llama 3.2 11B Vision** | $0.049 | $0.049 | Specialized open-weight vision processing |
| **Together AI / Embeddings** | ~$0.01 | - | Varies by open model (e.g., Nomic, BGE) |
| **Groq / Llama 3.1 70B** | $0.59 | $0.79 | LPU-accelerated, ultra-low latency inference |
| **Groq / Llama 3.1 8B** | $0.05 | $0.08 | Real-time voice or high-speed chat backends |

### Key Takeaways for Deployment
1. **Context Caching:** Nearly all major providers (Google, OpenAI, Anthropic) now offer automated or explicit context caching. If your architecture relies on heavy, persistent system prompts or static RAG documents, your actual input costs will be 50% to 90% lower than the base rates listed above.
2. **Batch API:** For asynchronous tasks (e.g., bulk classification or graph building), OpenAI and Anthropic offer 50% off standard token pricing if you can tolerate a 24-hour turnaround.
3. **The Race to the Bottom:** The "small" model tier has effectively hit a floor of $0.10 per million input tokens (Gemini 2.5 Flash-Lite, GPT-4.1 Nano, Llama 8B variants), making them cost-effective replacements for simple programmatic regex or parsing functions.

**Provider Documentation Links:**
* Google AI Studio Pricing: [ai.google.dev/pricing](https://ai.google.dev/gemini-api/docs/pricing)
* OpenAI API Pricing: [openai.com/api/pricing](https://openai.com/api/pricing/)
* Anthropic API Docs: [platform.claude.com/docs/pricing](https://platform.claude.com/docs/en/about-claude/pricing)
* Together AI Pricing: [together.ai/pricing](https://www.together.ai/pricing)



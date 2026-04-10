Here is the updated April 2026 model pricing snapshot, incorporating the recent launch of the **Gemma 4** family. This update highlights where these new open-weights models now supersede the performance-to-cost ratios of the proprietary "small" and "flash" tiers.

## New Highlight: Gemma 4 Family (Open-Weights)
Released on April 2, 2026, under a permissive **Apache 2.0 license**, the Gemma 4 family provides near-frontier reasoning and native multimodality at a fraction of the cost of proprietary counterparts.

| Model Variant | Input (per 1M) | Output (per 1M) | Context | Key Supersession |
| :--- | :--- | :--- | :--- | :--- |
| **Gemma 4 31B (Dense)** | $0.14 | $0.40 | 262K | **Supersedes GPT-5 Mini/Gemini 3 Flash** in reasoning-per-dollar. |
| **Gemma 4 26B (MoE)** | $0.13 | $0.40 | 262K | **Supersedes Llama 3.3 70B** in speed and efficiency (only 3.8B active parameters). |
| **Gemma 4 E4B (Edge)** | Local / ~$0.02 | Local / ~$0.04 | 128K | **Supersedes GPT-4.1 Nano** for local mobile/vision tasks. |

---

## Google Gemini (Proprietary)
Gemini models remain the gold standard for massive context (up to 2M+ tokens) and deeply integrated Google Cloud ecosystems.

| Model Tier | Input (per 1M) | Output (per 1M) | Best Use Case |
| :--- | :--- | :--- | :--- |
| **Gemini 3.1 Pro** | $2.00 | $12.00 | Ultra-long context RAG and peak logic |
| **Gemini 2.5 Pro** | $1.25 | $10.00 | General enterprise agents |
| **Gemini 3 Flash** | $0.50 | $3.00 | High-speed multimodal processing |
| **Gemini 2.5 Flash-Lite** | $0.10 | $0.40 | **Note:** Now challenged by Gemma 4 31B on quality. |
| **Gemini Embedding** | $0.15 | - | Knowledge Graph grounding and semantic search |

## OpenAI (Proprietary)
OpenAI continues to lead in developer ecosystem support and high-performance embedding efficiency.

| Model Tier | Input (per 1M) | Output (per 1M) | Status vs. Gemma 4 |
| :--- | :--- | :--- | :--- |
| **GPT-5** | $1.25 | $10.00 | Still the ceiling for general coding capability |
| **GPT-5 Mini** | $0.25 | $2.00 | Higher cost than Gemma 4 31B for similar logic. |
| **GPT-4.1 Nano** | $0.10 | $0.40 | Competitive with Gemma 4 E4B on hosted cost |
| **text-embedding-3-small** | $0.02 | - | Most cost-effective text embedding (RAG) |

## Anthropic (Claude)
Anthropic relies on its 90% prompt caching discount to compete with the aggressive pricing of Gemma 4 and GPT-5 families.

| Model Tier | Input (per 1M) | Output (per 1M) | Best Use Case |
| :--- | :--- | :--- | :--- |
| **Claude Opus 4.6** | $5.00 | $25.00 | Academic-grade research and complex math |
| **Claude Sonnet 4.6** | $3.00 | $15.00 | High-speed, high-reliability coding agents |

---

## Open Model Providers (Managed Hosting)
Gemma 4 significantly alters the value proposition here, offering higher quality than Llama 3.x at lower hosted prices.

| Provider / Model | Input (per 1M) | Output (per 1M) | Capabilities |
| :--- | :--- | :--- | :--- |
| **Together / Gemma 4 26B** | $0.13 | $0.13 | Fast MoE with 256K context. |
| **Together / Llama 3.3 70B** | $0.88 | $0.88 | Reliable but ~6x more expensive than Gemma 4. |
| **Groq / Llama 3.1 70B** | $0.59 | $0.79 | Ultra-low latency via LPU acceleration |

### Critical Supersession Notes
* **Reasoning Floor:** Previously, "small" models ($0.10/M) were limited to simple classification. **Gemma 4 31B** has effectively moved "Pro-tier" reasoning into this price bracket, ranking #3 on the Arena AI leaderboard while costing roughly the same as Gemini Flash-Lite.
* **Multimodality:** Gemma 4 includes **native vision and audio** (up to 60s video support), superseding the need for separate vision models in most open-weight pipelines.
* **Structured Output:** Gemma 4's advanced support for function calling and JSON schemas makes it a superior choice for **Knowledge Graph construction**, providing reliable structured data at a price point that makes large-scale graph-RAG feasible.

Here is a complete breakdown of the economics between API routing and self-hosting, specifically tailored for populating a GraphRAG knowledge store via your Claude CoWork workflow. 

The core variables for these calculations rely on the Gemma 4 31B (Dense) model, comparing its hosted API cost against a standard Google Cloud H100 instance.

### The Baseline Variables

| Infrastructure | Cost Metric | Details |
| :--- | :--- | :--- |
| **Gemma 4 31B API** | $0.14 per 1M Input | Pay purely for usage. Zero idle costs. Infinite concurrency. |
| **Self-Hosted H100 (GCP)** | ~$3.50 per Hour | Flat rate. Fixed throughput limit. Requires infrastructure management. |
| **Document Workload** | 50,000 Tokens | Average size of a complex literature review PDF or financial report, including text and encoded images. |

---

### Use Case 1: Real-Time Synchronous Routing (API Wins)

**Scenario:** A team of 15 analysts logs on at 9:00 AM. Over the first hour, they individually review 30 different financial reports and hit your Claude CoWork tool to extract both the text and the image descriptions immediately so they can query the results right then.

**The API Calculation:**
* Total API usage: 30 reports * 50,000 tokens = 1.5 million input tokens. 
* API Cost: **$0.21 total**. 

**The Self-Hosted Calculation:**
* Because the 15 analysts are submitting jobs at the same time, a single H100 will bottleneck. You would need to spin up at least two H100 instances behind a load balancer to maintain acceptable response times.
* Self-Hosted Cost: 2 instances * $3.50/hour = **$7.00 total**.

**Verdict:** The API is massively cheaper for real-time concurrency. The self-hosted setup costs 33x more because you are paying for capacity, not utilization.

---

### Use Case 2: Asynchronous Batch Processing (Self-Hosted Wins)

**Scenario:** Your analysts spend all week flagging 1,000 academic PDFs for inclusion in a Neo4j database. Your system extracts the text instantly via a cheap routing model, but drops all 1,000 PDFs into a Cloud Run queue to have their complex scientific charts and images described over the weekend. 

**The API Calculation:**
* Total API usage: 1,000 reports * 50,000 tokens = 50 million input tokens.
* API Cost: **$7.00 total**.

**The Self-Hosted Calculation:**
* You trigger a single Cloud Run GPU instance (H100 equivalent). At 100% utilization, the 31B model can process roughly 720 of these heavy document extractions per hour. 
* To clear the 1,000-document queue, the GPU runs at maximum capacity for exactly 1.4 hours and then automatically spins down to zero.
* Self-Hosted Cost: 1.4 hours * $3.50 = **$4.90 total**.

**Verdict:** Self-hosting wins. By controlling the queue and running the hardware at 100% saturation, you flip the economics and save roughly 30% on the batch. 

---

### The Break-Even Formula for the Hybrid Architecture

To decide exactly when your system should route to the API versus spinning up a serverless GPU, you can use a simple break-even calculation based on the volume of your queue.

A single H100 ($3.50/hr) processing at maximum capacity can clear about **25 million input tokens per hour** (for vision-heavy tasks). 

* 25 million tokens via API = **$3.50**
* 25 million tokens via H100 = **$3.50**

**The Golden Rule for Your System:**
If your Claude CoWork tool drops a batch of images into the queue that totals *less* than 25 million tokens (roughly 500 dense reports), process it through the API. If the queue grows *larger* than 25 million tokens, trigger the Cloud Run instance to spin up, clear the backlog, and shut down. 

Are you planning to use a standard message broker like Google Cloud Pub/Sub to monitor the size of this extraction queue and trigger the appropriate route?
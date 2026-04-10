# Starter Deck — Ariadne Core Onboarding

Five prewired beats. Run them in order, one message at a time. Each beat ends
with `AskUserQuestion`. Stop and wait after every beat. After beat 5, the
presenter goes fully dynamic (see `SKILL.md` § "Go dynamic after beat 5").

All hard rules from `SKILL.md` apply to every beat: one image per message,
`AskUserQuestion` at the end, anchor numbers verbatim, model-class language
for rates, acknowledge both audiences.

---

## Beat 1 — The hook (show video, hit high points, ask if they've seen it)

**image_id:** `video_thumbnail`

**image_markdown (embed verbatim — do not reach for `present_files`):**

    ![Nate Jones — Your Claude Sessions Cost 10x What They Should](https://raw.githubusercontent.com/denson/ariadne-core/main/docs/skills/ariadne-core-walkthrough/assets/images/video_thumbnail.png)

**content_guidance:**
This beat does three things in one message:

1. **Show the video thumbnail** by embedding the markdown above directly in
   your message. Cowork renders it inline. Do not call `present_files`, do
   not look up local paths, do not copy files anywhere. If for some reason
   the URL embed doesn't render, still link the YouTube URL inline so the
   user has the artifact in front of them.
2. **Hit the high points of Nate's argument** in 3–4 sentences. Don't just
   tease the title — give them enough that they can decide whether the
   problem is real for them. Use the anchor numbers verbatim. Suggested:
   *"Nate's core point: when you drop raw PDFs into a frontier model's
   context, you're paying frontier-tier rates ($3–$15/M for Sonnet-class
   through Opus-class) for binary metadata, embedded fonts, and layout junk
   the model never even uses. A 4,500-word document is ~100,000 tokens as a
   raw PDF but only ~5,000 as clean Markdown — a 20x reduction per document
   just from format conversion. Multiply across a multi-document research
   session and a wasteful 30-turn Opus session that should cost ~$1 ends up
   costing $8–$10. That's the 10x he's talking about."*
3. **Mention what we have** in one sentence: *"We've built a tool that
   addresses a big chunk of this — open source today, self-installable on
   Railway in about five minutes, with a managed version coming soon for
   people who'd rather not run the infrastructure themselves."*

Then ask whether they've already seen the video. The answer routes beat 2.

**question_template:**
*"Have you already seen Nate's video?"*
Options:
- *Yes, I've seen it*
- *No, but I'm interested*
- *No, and I'd rather just hear it from you*
- *I've seen part of it / read the article*

**Video links** (include both inline so the user has them regardless of
whether the thumbnail renders):
- YouTube: https://youtu.be/5ztI_dbj6ek (document deep-dive at
  https://youtu.be/5ztI_dbj6ek?t=260)
- Substack article: https://natesnewsletter.substack.com/p/your-claude-sessions-cost-10x-what

---

## Beat 2 — The token waste problem (branches on Beat 1 answer)

**image_id:** `onboarding_token_waste`

**content_guidance:**
This beat shows the token-waste illustration and adapts its framing to
whether the user has seen Nate's video. Both branches converge on the same
image and the same `question_template`. Pick the branch from Beat 1's answer:

**If they've seen the video (or read the article):**
Treat them as already on board with the diagnosis. One short paragraph that
*reviews* the argument rather than re-pitches it: *"Then you already know the
shape of this. The image just makes it concrete — same 4,500-word document,
~100,000 tokens of raw PDF on the left versus ~5,000 tokens of clean
Markdown on the right. The 20x ratio is mechanism 1. Mechanism 2 — the
bigger one — is the LLM-driven extraction loop he hints at: frontier models
burning Sonnet-class to Opus-class rates to write Python, call pdfminer, and
retry OCR. We replace both."*

**If they haven't seen it:**
Walk them through Nate's core argument in 3–4 sentences using the same image
as the visual. Then explicitly recommend the video. *"Two mechanisms are
load-bearing here, and Nate covers both. First, raw PDF bloat — a 4,500-word
document is ~100,000 tokens as a raw PDF but only ~5,000 as clean Markdown,
a 20x reduction per document just from format conversion. Second, and this
is the bigger one, the LLM-driven extraction loop: when there's no pipeline,
a frontier model has to figure out extraction itself — write Python, call
pdfminer, debug tables, retry OCR — all at Sonnet-class to Opus-class rates
($3–$15/M). The video is 12 minutes and worth your time; the document
deep-dive starts at 4:20. I'd genuinely watch it before going further."*

In both branches, end with a one-line bridge: *"That's the problem we
address."*

**question_template:**
*"Does this match what you're seeing in your own workflows, or is your
situation different?"*
Options: *Yes, this is us* / *Partially — we've got some of this* / *My
situation is different* / *Continue*

---

## Beat 3 — The audience disambiguator

**image_id:** (none — this is a text-only beat)

**content_guidance:**
Explain in 2–3 sentences that the savings land differently depending on how
the user buys tokens. Subscription users on Claude Code or Claude Cowork
experience the savings as **runway** — hitting usage limits less often,
longer productive sessions, more work per day before rate-limiting. Agentic
systems buying tokens directly (OpenClaw, Open Brain, OB1, custom agents)
experience them as a **direct line-item cost reduction** on the monthly
frontier bill. Same mechanism, different lived experience. This beat sets
the framing for beat 4; don't pick a side yet.

**question_template:**
*"Which of these sounds most like your situation?"*
Options:
- *Subscription (Claude Code, Cowork) — I hit usage limits*
- *Agentic system buying tokens directly — I see a monthly bill*
- *Not sure yet / just curious / both*

---

## Beat 4 — The mechanism (framing shaped by Beat 3)

**image_id:** depends on beat 3 answer:
- Subscription → `onboarding_agent_heavy_lifting` (framed as runway — "your
  agent does the heavy lifting so you get more done per session")
- Agentic buying tokens directly → `roadmap_pay_vs_save` (framed as direct
  line-item cost reduction — the engineering-document bar chart)
- Not sure / both → `roadmap_two_token_economies` (the dramatic scale
  asymmetry image — pennies in vs dollars saved)

**content_guidance:**
Explain the fix in 3–4 sentences, framed for the audience they just picked.
Lead with the deterministic pipeline: MarkItDown + format parsers extract in
pure Python at $0 in tokens; a small embedding model handles text at
~$0.02/M; a small multimodal model handles images at ~$0.14/M. Per-document
cost to us: ~$0.002. The frontier model only ever sees clean Markdown via a
search interface — and gets **better** extracted content than it would have
produced itself. Always mention "better, not just cheaper" — a deterministic
pipeline captures tables, layout, and image semantics more accurately than a
frontier model improvising extraction code.

**question_template:**
*"Does this match how you'd want your agents to handle documents — or is
there something about your stack that would change the picture?"*
Options: *Yes, this is what I want* / *I have constraints — tell me more* /
*Continue* / *Something else*

---

## Beat 5 — Handoff to dynamic mode

**image_id:** (none — this is a text-only beat that opens the dynamic phase)

**content_guidance:**
Briefly name what you've covered (hook → problem → two-audience framing →
the fix) in one sentence, then hand control to the user. Don't summarize
content — just signal the transition. Something like: *"That's the core of
it. From here I can go in whatever direction is most useful — what do you
want to dig into?"*

**question_template:**
*"What do you want to look at next?"*
Pull 3–4 options from the most commonly-useful concept ids in the knowledge
graph. Suggested starting set (rotate based on earlier answers):
- *How the extraction pipeline actually works* → `the_extraction_pipeline`
- *How to deploy it (Railway, Fly, Docker)* → `railway_deployment`
- *The editions and pricing story* → `roadmap_personal_edition` /
  `managed_pricing_overview`
- *The "beyond extraction" metadata + search layer* →
  `beyond_extraction_metadata_layer`
- *Something else* (always offer this as an escape hatch)

After the user answers, you are in dynamic mode. Every subsequent beat is
composed on the fly per the loop in `SKILL.md` § "Go dynamic after beat 5".

# ConceptViz Prompts for Infrastructure Summary

---

**img_01 — Per-User Architecture**

A layered architecture illustration with three distinct horizontal tiers, flowing top to bottom.

Top tier (narrow, labeled "Management Layer"): a single wide rounded rectangle with a dark blue-gray tint. Inside it, four small icons in a row with labels beneath each: a shield icon labeled "OAuth 2.1", a person-plus icon labeled "User Provisioning", a bar-chart icon labeled "Usage Tracking", and a dollar-sign icon labeled "Billing." A subtle train icon (representing Railway) sits in the corner of the provisioning box with a small label "Railway API." A small price tag reads "$20/mo management fee + Railway at cost." Arrows flow downward from this tier.

Middle tier (medium height, labeled "App Tier — Shared, Always-On"): a single wide rounded rectangle with a warm amber tint. Inside, three identical server box icons arranged in a row, each labeled "FastAPI" with a small load-balancer icon distributing arrows to all three. A subtitle reads "Stateless, load-balanced." To the right of the server boxes, two outgoing arrows: one pointing to a cloud labeled "Small Multimodal Model API (default — Gemma 4 class)" and another pointing to a cloud labeled "User's BYO endpoint." A callout box between the arrows reads "Embedding & Vision." Arrows flow downward from this tier, splitting into two paths — one going left, one going right.

Bottom tier (tallest, split into two sections side by side):

Left section (labeled "Per-User Databases"): five small Postgres elephant icons arranged in a staggered vertical column, each inside its own small rounded rectangle. Each rectangle is labeled with a user identifier: "User A", "User B", "User C", "User D", and an ellipsis box "..." at the bottom. Each box has a small storage meter bar showing different fill levels (20%, 45%, 60%, 80%). A callout arrow from the most-full meter reads "Storage alerts before overage."

Right section (labeled "Shared Vector Search"): a single large rounded rectangle with a green tint containing the Weaviate logo (a stylized W or hexagon). Inside, four horizontal tenant bars stacked vertically, each a different pastel shade, labeled "Tenant A", "Tenant B", "Tenant C", "Tenant D." A small badge on the container reads "Native Multi-Tenancy." Another small badge reads "Product Quantization — 30x less RAM."

Caption: "Shared app tier. Isolated databases. One vector cluster."

Colorblind-friendly, no hex codes. These images are for an engineering meeting document — they should be clear, precise, and technically informative while remaining visually accessible. Style for all: flat design, editorial illustration, simple shapes, bold colors on a light warm-gray background. Think "SaaS architecture overview," not whiteboard sketch.

---

**img_02 — What $20/mo Gets You**

A single large card on a light warm-gray background, labeled "Managed — $20/mo + Railway at Cost" with a cool blue tint. The card is split into two sections side by side.

Left section (labeled "Your $20/mo Management Fee"): a vertical list of five rows, each with an icon and label:
- Row 1: shield icon, "Security monitoring & patches"
- Row 2: clock-arrow icon, "Automated backups"
- Row 3: arrow-up icon, "Version upgrades — we handle them"
- Row 4: wrench icon, "Infrastructure provisioning via Railway API"
- Row 5: chart icon, "Usage tracking & alerts"

Right section (labeled "Railway Infrastructure — Passed Through at Cost"): a vertical list of four rows, each with an icon and label:
- Row 1: database icon (Postgres elephant), "Own Postgres Instance"
- Row 2: hexagon icon (Weaviate), "Weaviate Vector Search"
- Row 3: hard-drive icon with a meter bar, "Storage — pay for what you use"
- Row 4: swap-arrows icon, "BYO models or buy from us"

Below both sections, a comparison callout box reads: "DIY means you handle hosting, backups, security, and upgrades yourself. $20/mo means we do it — you just use the system."

A shared footer at the bottom reads: "Same code as Personal. We run it so you don't have to."

Caption: "One tier. $20/mo management fee. Infrastructure at cost."

Colorblind-friendly, no hex codes. These images are for an engineering meeting document — they should be clear, precise, and technically informative while remaining visually accessible. Style for all: flat design, editorial illustration, simple shapes, bold colors on a light warm-gray background. Think "SaaS architecture overview," not whiteboard sketch.

---

**img_03 — Storage Growth: Users Will Hit Overage**

A single-panel illustration showing a timeline of database storage growth for a typical Managed user.

The main element is a horizontal timeline flowing left to right, labeled "Month 1" through "Month 12" with tick marks. Above the timeline, a database cylinder grows taller at each month — starting small at Month 1 and progressively taller through Month 12. The cylinder is filled with a gradient that shifts from calm blue-green at the bottom to warm amber at the top as storage grows.

The growth is not linear — it shows bursts. Month 1-2: slow growth (a few documents). Month 3: a noticeable jump (labeled "Initial bulk ingest"). Month 4-6: steady growth. Month 7: another jump (labeled "Quarterly report batch"). Month 8-12: continued steady growth.

Three annotation callouts at key points:
- At Month 4 (cylinder growing noticeably): a bell icon with "Alert: storage growing — here's your current Railway cost" in a friendly yellow callout
- At Month 7 (cylinder after the quarterly batch jump): a flag icon with "Batch ingest spike — cost increase visible in dashboard" in an amber callout
- At Month 9 (cylinder continuing to grow): a small receipt icon with "Railway storage cost: transparent, billed at cost" — showing it is predictable and visible

Below the timeline, a single comparison box:
- "Managed user — Railway storage billed at cost. Most users see meaningful growth within 3-6 months. Storage alerts keep costs visible."

Caption: "Storage grows. Users need to see it coming, not get surprised."

Colorblind-friendly, no hex codes. These images are for an engineering meeting document — they should be clear, precise, and technically informative while remaining visually accessible. Style for all: flat design, editorial illustration, simple shapes, bold colors on a light warm-gray background. Think "SaaS architecture overview," not whiteboard sketch.

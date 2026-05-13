# ARESense IMU — Story Bible

**Demo corpus for the bw + Ariadne + hypergraph "factory-manager investigative-workflow" arc.**
Target: ~300-500 tickets across a fictional 6-month investigation, seeded into `bw` at slug `aresense`. Designed to make the four-question demo arc light up cleanly (Q1 bw-alone → Q2 vector search → Q3 strained chronological → Q4 hypergraph traversal).

This bible is the spec the ticket-corpus generator (CAPTAIN_ADA) will author against. It is not the corpus itself.

---

## 1. The company

**ARESense Technologies, Boulder, CO.** 152 employees. Founded 2014 by two ex-Honeywell MEMS engineers (Aravind Subramanian and a co-founder who exited in 2019). Profitable since 2019. Mid-volume sensor manufacturer; ~85,000 units/year.

Single product line: the **ARES-IMU-9 series** — 9 degree-of-freedom inertial measurement units (3-axis gyroscope + 3-axis accelerometer + 3-axis magnetometer), at three price/performance tiers:

| Tier | Target | Annual volume | Notes |
|---|---|---|---|
| ARES-IMU-9A | Consumer prosumer drones | ~55k | Cost-driven |
| ARES-IMU-9B | Industrial / agricultural platforms | ~22k | Margin-driven |
| ARES-IMU-9C | Tactical-grade small UAS | ~8k | Performance + ITAR-compliant |

Final assembly, SMT, and calibration are in-house in Boulder. Die-level components, ASIC, package house, and PCB fab are outsourced. Conformal coating is in-house but chemistry is supplied.

**Customers under multi-year volume contracts:**
- **SkyHawk Aviation** (prosumer drones — buys 9A)
- **Pylon Inspection Systems** (utility-line drones — buys 9B)
- **GreenFurrow Robotics** (precision-ag autonomous tractors — buys 9B)
- **Tessera Defense Systems** (small UAS for US allied programs — buys 9C)
- **Halcyon Surgical Robotics** (cancelled Q3 last year; appears only in archive tickets — useful for Q4 gap analysis)

## 2. Supply chain — the eight named suppliers

| Component | Supplier | Location | Relationship |
|---|---|---|---|
| MEMS gyro die | **Yamashiro Microtech** | Yokohama, JP | 6 yrs; transitioned to 200mm wafer line mid-Q3 last year |
| MEMS accelerometer + magnetometer die | **Cascade Microsystems** | Portland, OR | 4 yrs; bundled deal |
| Sensor-fusion ASIC | **TaipeiSilicon Foundry** | Hsinchu, TW | 5 yrs; fab partner |
| Package house | **Penang IC Packaging (PIP)** | Penang, MY | 3 yrs; **switched from incumbent 18 months ago for 22% cost reduction** ← load-bearing for H6 |
| PCB fab | **Frontline Circuits** | Aurora, CO | 5 yrs; domestic mid-volume |
| SMT overflow (line 2 only) | **Maquila Industria de Ensamble (MIE)** | Juárez, MX | Backup capacity |
| Conformal coating chemistry | **Drysdale Coatings** | Reading, PA | **Reformulated for RoHS-3 compliance Q1** ← load-bearing for H2 |
| Thermal-cycling calibration jigs | **Becher Präzision GmbH** | Stuttgart, DE | Single-vendor |

Notice: two supplier-side events in the prior 12 months (PIP unannounced leadframe substitution, Drysdale RoHS-3 reformulation) interact to create the defect. Neither alone is sufficient; the confluence is the root cause.

## 3. Cast — ~28 named characters

**Plant leadership:**
- **Marcus Chen** — Director of Quality & Operations. The "you" of the demo. 18 yrs at ARESense, formerly Honeywell. Pragmatic, data-driven, allergic to scapegoating.
- **Diana Reyes** — Plant Manager. Owns shop-floor execution. Reports to Marcus.
- **Aravind "Ravi" Subramanian** — Co-founder, Director of Engineering. Marcus's peer. Owns design + process. Sharp, sometimes impatient.

**Investigation team (Marcus's circle):**
- **Priya Iyer** — Senior Process Engineer, SMT line owner. 8 yrs. Detail-fanatic. Owns the H3 line.
- **Dale Brennan** — Process Engineer, calibration & test. 6 yrs. Night-shift advocate; sometimes contrarian. Brother of Carl Brennan (night-shift operator). Owns the early H4 surfacing.
- **Won Lee** — Quality Engineer, supplier-facing. 4 yrs. Owns IQC and the supplier escalation arc through H6.

**Operators (representative — final corpus has ~13 named):**
- *Day shift:* Rosa Calderón, Marcus Wright Jr. ("Junior" to disambiguate from Marcus Chen), Karen Holloway, Tomás Aguilar, Jen Park
- *Swing shift:* Devon Hayes, Lucia Martinez, Hank Petrov, Sam Okafor, Marie Doucette
- *Night shift:* Carl Brennan, Annie Wong, Tariq Hassan

**Supplier-side voices (these appear in supplier-ticket comment threads):**
- **Hiroshi Tanaka** — Yamashiro Microtech account engineer
- **Karthik Rao** — Cascade Microsystems account engineer
- **Lim Boon-Hwa** — PIP package house engineering manager (pivotal in months 4-5)
- **Jürgen Becher** — Becher Präzision (calibration jig vendor)
- **Sandy Drysdale** — Drysdale Coatings R&D lead (appears for the coating chemistry tweak)

**Customer reliability engineers (introduce field-failure pressure):**
- **Erika Lundgren** — SkyHawk Aviation reliability lead. Methodical; provides clean monthly summaries.
- **Captain Daniel Park (USAF, ret.)** — Tessera Defense reliability consultant. Politically loud; escalates when frustrated.
- **Joel Mwangi** — Pylon Inspection field engineering (less central).

## 4. The defect — presenting symptom

**Month 1 surfacing.** SkyHawk's monthly reliability summary reports **~4.2% of fleet units operating in winter conditions (ambient below -10°C)** exhibit gyro-Z axis drift exceeding spec: greater than 0.5°/s above the sheet-rated 0.8°/s lifetime drift. Drift manifests in flight as compass-heading slew (operationally inconvenient; safety-margin-eroding rather than immediately dangerous).

**Three load-bearing characteristics make this hard:**

1. **Intermittent.** Same unit may fail one cold-soak and pass the next. Failure is profile-dependent (specific cold-cycle paths trigger; others don't).
2. **Doesn't reproduce at factory ambient.** Field returns mostly pass when re-tested at +22°C. RMA path is hostile.
3. **Multi-customer.** SkyHawk → Pylon → Tessera reports trickle in over months 1-3. Three customers, three slightly different failure-signature reports, one underlying cause.

**Retrospective signal.** Earliest similar one-off reports appear in Tessera and Pylon backlogs from months -3 to 0 — visible in retrospect once the H6+H2 hypothesis crystallizes, not prioritized at the time. *(These archive tickets matter for Q4 — they're the "we didn't realize this was the same defect three months earlier" gap that hypergraph traversal surfaces.)*

## 5. The six-hypothesis stack (the investigation's spine)

The bw corpus carries six competing hypotheses developed over 6 months. Each is parented by an epic-shaped hypothesis ticket; supporting and refuting evidence are child tickets; relationships use `bw dep add` for "supports / refutes / blocks." The hypergraph layer surfaces this structure cleanly.

| # | Hypothesis | Outcome | Q-arc role |
|---|---|---|---|
| H1 | Yamashiro gyro die batch variance | Partial (correlation but no causation) | Early-investigation leading theory |
| H2 | Drysdale conformal coating thermal-stress | **Confirmed contributor** | Co-root; supplies the amplifier |
| H3 | SMT line 2 reflow profile drift | Contributing factor (~30% of line 2 elevation) | Partial cause; independent fix path |
| H4 | Night-shift calibration "fast-cal" shortcut | Ruled out as load-bearing | Q3's content — the dead-end the new editor will ask about |
| H5 | HVAC compressor magnetic interference | Red herring; ruled out month 2 | The "we already checked this" |
| H6 | PIP leadframe alloy substitution | **Confirmed contributor** | Co-root; supplies the weakness |

**H2 + H6 confluence is the root cause.** Either alone is insufficient. Combined: a weaker leadframe alloy (H6) is amplified by a higher-CTE conformal coating (H2), producing thermal-stress micro-crack onset at the gyro-Z bond stack under specific cold-cycle profiles → drift.

## 6. The six-month timeline

### Month 1 — Surfacing
- SkyHawk reliability summary triggers the investigation.
- Marcus opens an epic. Won Lee pulls batch genealogy. **H1 (Yamashiro)** opens: 70% of failed units trace to two Yamashiro lots from late-Q3 (when Yamashiro transitioned to a 200mm wafer line). Hiroshi Tanaka pushes back on the data — Yamashiro's internal QC shows nothing.
- Priya begins reflow-profile data pulls in parallel.

### Month 2 — H5 ruled out, H4 surfaces
- **H5 (HVAC compressor) ruled out month 2 day 14.** Priya's 2-week ON/OFF study shows no correlation. Closes a ~12-15 ticket cluster — all archived, useful as "we already checked this" content for future agents.
- **H4 (night-shift fast-cal) surfaces day 18.** Dale flags that the night-shift gyro-cal protocol was abbreviated from 11 steps to 6 in Q4 last year, unauthorized. Marcus assigns Won Lee (independent — Dale's brother runs night shift). Investigation runs the rest of month 2 and into month 3.

### Month 3 — H4 ruled out, H3 surfaces, partial progress
- **H4 ruled out month 3 day 5** as load-bearing for the field defect. Won Lee pulls Becher jig firmware logs, interviews all 3 night-shift cal operators, replicates the night-shift protocol on day-shift units. Conclusion: the shortcut is real, IS not best practice, AND affects ambient-cal repeatability by ~15% — but does **not** produce the cold-temperature drift hysteresis observed in the field. Marcus opens a **separate epic** for night-shift protocol overhaul (independent improvement). Dale partially vindicated; Carl's team's protocol fixed.
- **H3 (line 2 reflow profile) surfaces day 12.** Priya's pull-rate analysis: line 2 builds are 3.2× over-represented among failures. DOE shows line 2's actual reflow peak temperature is running **7°C hot** because the controller thermocouples drifted (vendor firmware issue). Fix lands month 3 day 28 (thermocouple replacement + monthly calibration SOP). **H3 confirmed as a contributing factor (~30% of line 2 failure-rate elevation), but does not explain line 1 unit failures.**

### Month 4 — H6 surfaces (the real root)
- Third-party failure analysis lab (Sandia under NDA service contract) returns deep-dive results on three RMA field-returns. SEM imaging shows **micro-cracking in the leadframe-to-die bond at the gyro-Z stack location.** Bond pattern is NOT consistent with the alloy spec ARESense provides PIP.
- Won Lee escalates to PIP. **After 2 weeks of escalation, Lim Boon-Hwa at PIP discloses that PIP substituted the leadframe alloy ~5 months ago** — a small composition change PIP considered "within spec envelope," didn't notify ARESense. Substituted alloy has a different thermal-expansion coefficient.
- **H6 opens.** This is the first hypothesis that explains failures in BOTH line 1 AND line 2 units.

### Month 5 — H2 surfaces, H2+H6 confluence confirmed
- With H6 understood, FA lab takes another pass. Leadframe stress alone is insufficient at the rate observed; something is amplifying.
- Marcus cross-references Q1 calendar. **Drysdale Coatings reformulated their conformal coating chemistry for RoHS-3 compliance in Q1** — disclosed at the time, but the downstream impact (slightly higher cure-state CTE) was missed by ARESense IQC review.
- **H2 opens.** The COMBINATION of weaker leadframe alloy (H6) + higher-CTE coating (H2) produces the thermal-stress hysteresis observed.
- Sandy Drysdale (Drysdale Coatings R&D) engages collaboratively on a chemistry tweak (3-month qualification timeline).

### Month 6 — Resolution + remedial (story does NOT fully close)
- IQC tightening: leadframe alloy specs explicitly enumerated. Supplier-substitution requires written notification 60 days in advance per revised supplier governance (Won Lee's epic).
- PIP returns to prior alloy for 9B/9C tiers. 9A consumer tier accepts a redesigned bond pattern at price savings.
- Drysdale modified formulation enters qualification (will not complete until end of Q3).
- SPC introduced on conformal coating thickness with revised control limits.
- Field-fix protocol: SkyHawk + Pylon + Tessera all authorize retrofit slots. ~12,000 in-warranty units re-coated and re-tested rolling through Q3-Q4.

**The corpus stays "alive" at end of month 6.** Several open threads keep `bw ready` non-empty: H3 line 2 fix is mid-rollout, field retrofit is in motion, H6 alloy qualification cycles are open for two additional cases, the Drysdale formulation qualification is open. This matters: a fully-resolved corpus would mute the "still working" feeling the demo needs.

## 7. Ticket-corpus shape (the spec ADA generates against)

Target corpus: **~400 tickets** distributed roughly:

| Ticket category | Approximate count | Notes |
|---|---|---|
| Hypothesis epics (H1-H6) | 6 | Each parents 30-80 children |
| Shift observations / floor reports | ~60 | Across 6 months × 3 shifts; 5-15 per shift-month |
| QC test results / FA reports | ~50 | Detailed for the hypothesis-supporting ones |
| Supplier-event tickets | ~40 | Comms with all 8 suppliers; PIP and Drysdale heavily comment-threaded |
| Customer-report tickets | ~25 | SkyHawk monthly summaries + Tessera/Pylon ad-hoc |
| Equipment-maintenance tickets | ~20 | Including the line 2 reflow-oven thread |
| Operator-interview / debrief tickets | ~25 | Cal-protocol H4 investigation drives many of these |
| Dead-end / red-herring tickets (H5 cluster + others) | ~30 | Closed-as-deferred or closed-as-not-load-bearing |
| Hypothesis-evidence relationship tickets | ~80 | The relational backbone — `bw dep add` for supports / refutes / blocks |
| Tracking / housekeeping tickets | ~35 | Status summaries, retrospective notes, action-item closeout |
| Archive tickets (pre-month-1 retrospective) | ~30 | Tessera + Pylon early one-offs, Halcyon archive |

**Required ticket-level metadata** (each ticket carries):
- `type`: observation / hypothesis / evidence / supplier-event / customer-report / maintenance / interview / decision / archive
- `shift`: day / swing / night / N/A
- `supplier`: one of the 8 (when applicable)
- `hypothesis`: H1-H6 (when applicable)
- `outcome`: confirmed / refuted / partial / open
- `created_at`: spread realistically across the 6-month timeline
- `assignee`: one of the cast
- `tier`: 9A / 9B / 9C / N/A

**Required relational structure (this is what makes Q4 work):**
- Each H epic is parent to its supporting + refuting evidence
- `bw dep add <evidence> blocks <hypothesis-conclusion>` for unresolved-evidence relationships
- Hypothesis-to-hypothesis: H2 supports H6 (confluence); H4 ruled-out blocks H4-conclusion; H5 ruled-out blocks H5-conclusion
- Supplier-event tickets parent the relevant escalation comment threads
- Customer-report tickets are parents to the in-house investigation tickets they triggered

## 8. The four demo queries — calibration

**Q1 (bw-alone):** *"Has PIP's latest leadframe cert come back?"*
Direct ticket lookup. The ARES-PIP supplier ticket (~3-5 in the corpus) has the most recent comment thread from Won Lee. Single-ticket retrieval. bw's sweet spot.

**Q2 (vector search):** *"What's our leading hypothesis on the cold-temp drift and what supports it?"*
Semantic retrieval over hypothesis tickets surfaces H2 + H6 confluence narrative. Returns supporting evidence chain (Sandia FA lab report, Lim Boon-Hwa disclosure, Drysdale reformulation timing). Vector search wins because the question doesn't name H2 or H6 — it names the symptom.

**Q3 (strained search):** *"Walk me through how we ruled out the night-shift calibration theory."*
Chronological reconstruction across the H4 cluster: Dale's flag (month 2 day 18), Marcus's independent-investigator assignment to Won Lee, Becher jig firmware log analysis, operator interviews, replication study, the ruling-out comment (month 3 day 5), the separate epic that spawned from it. Vector search returns the right candidate set; assembling them in narrative order strains — possible without hypergraph but visibly less crisp.

**Q4 (hypergraph required):** *"If the H2+H6 combo is the cause, what tests have we not run yet? Where are the gaps?"*
Graph traversal walks the H2+H6 dependency tree. Identifies absences:
- Multi-cycle thermal fatigue under humidity load — not tested
- 9A consumer tier's redesigned bond pattern at field-realistic vibration — not characterized
- Retroactive examination of Halcyon Surgical archive units for similar bond signatures — not done (could reveal pre-PIP-substitution prevalence)
- Cross-line genealogy for line 1 units briefly run on line 2 during maintenance windows — gap in the H3 closure

Vector search returns existing tickets, not absences. The hypergraph identifies **predicted-but-not-validated** nodes — precisely what Q4 is asking for.

## 9. Act 4 — the meta-agent layer the bible plants hooks for

The corpus is structured so four downstream meta-agents can read the substrate and project to different stores:

1. **Lessons-learned meta-agent** reads the H6 supplier-substitution chain → projects to CI tracker: *"Supplier substitution governance gap: prior process allowed unannounced changes. Revised SOP requires 60-day written change-notification. Audit Q3 to verify uptake."*

2. **Vendor scorecard meta-agent** reads PIP / Drysdale / Yamashiro comment trails → projects to vendor scorecard: *PIP -2 trust points (substitution without notification); Drysdale neutral (reformulation disclosed but downstream impact missed by ARESense IQC); Yamashiro +1 (initial suspicion not validated; data transparency commendable).*

3. **CMMS preventive-maintenance meta-agent** reads the H3 reflow-oven cluster → projects to CMMS: *"Reflow oven RFO-002 (line 2): add monthly thermocouple calibration check; firmware-vendor escalation open; vendor patch ETA Q3."*

4. **Runbook meta-agent** reads the H2+H6 confluence pattern → projects to defect-signature runbook: *"Cold-temp gyro-Z drift signature: check (a) leadframe alloy COC against current spec, (b) conformal coating CTE characterization, (c) field-return micro-crack signature at bond stack."*

The same substrate. Four downstream stores. Each meta-agent extracts a different shape; none of them mutates the bw/Ariadne layer.

## 10. Generation constraints for the corpus author (ADA)

**Realism requirements:**
- Ticket titles read like real factory ops shorthand ("ARES-9B Lot 2024-W47 — gyro-Z drift uplift in SkyHawk batch return", not "Investigation of defect").
- Comments include realistic timestamps spread within the relevant week.
- Operator-author tickets use shift-appropriate language (terse, observational); engineer-author tickets use analytical language; supplier-comm tickets use professional-formal.
- Some tickets are short (one-line observation + closure); some are deeply threaded (10+ comments over weeks).
- Dates spread across a fictional Sept 2025 → Feb 2026 window.

**Anti-realism to avoid:**
- No anachronistic vocabulary (don't use 2026 tooling terms in operator language).
- No conspicuously "AI-written" phrasing (don't have every operator write like a structured analyst).
- No perfect timeline — let some tickets be slightly out of order, occasional typos in operator tickets, occasional comments that go off-topic.

**Determinism for the generator:**
- ADA should produce the corpus as a structured artifact (jsonl or yaml manifest) that the seeder reads — not as a sequence of `bw create` calls. This makes the corpus version-controlled, reproducible, and editable.
- Corpus manifest lands at `agents/design/factory-demo/CORPUS_MANIFEST.{jsonl|yaml}`.
- A separate seeder script (one of the next-up tasks) walks the manifest and emits `bw create` / `bw comment` / `bw dep add` calls.

---

## Status

This bible is the spec for the corpus generation task. Once PRINCIPAL signs off, dispatch CAPTAIN_ADA with this bible as the design artifact + a tight generation brief.

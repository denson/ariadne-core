# CORPUS_INVENTORY — ARESense IMU factory-demo corpus

**Companion to** `STORY_BIBLE.md` and `CORPUS_MANIFEST.jsonl`.

This document is the structural roster for the ~400-ticket demo corpus. It's the plan the manifest is authored against. Lookups here use **local IDs** (`T-NNNN`); these are translated to `bw` ticket IDs at seed time by the seeder script.

---

## Header — canonical slugs (referenced throughout)

### Supplier slugs (`metadata.supplier`)
| Slug | Full name | Role |
|---|---|---|
| `yamashiro` | Yamashiro Microtech | MEMS gyro die |
| `cascade` | Cascade Microsystems | accel + magnetometer die |
| `taipei_silicon` | TaipeiSilicon Foundry | sensor-fusion ASIC |
| `pip` | Penang IC Packaging | package house (H6 axis) |
| `frontline` | Frontline Circuits | PCB fab |
| `mie` | Maquila Industria de Ensamble | SMT overflow |
| `drysdale` | Drysdale Coatings | conformal coating (H2 axis) |
| `becher` | Becher Präzision GmbH | calibration jigs |

### Customer slugs (`metadata.customer`)
| Slug | Full name |
|---|---|
| `skyhawk` | SkyHawk Aviation |
| `pylon` | Pylon Inspection Systems |
| `greenfurrow` | GreenFurrow Robotics |
| `tessera` | Tessera Defense Systems |
| `halcyon` | Halcyon Surgical Robotics (archive only) |

### Cast slugs (`assignee_local` / `comments[].author_local`)
**Leadership:** `marcus_chen`, `diana_reyes`, `aravind_subramanian`
**Investigation team:** `priya_iyer`, `dale_brennan`, `won_lee`
**Day-shift ops:** `rosa_calderon`, `marcus_wright_jr`, `karen_holloway`, `tomas_aguilar`, `jen_park`
**Swing-shift ops:** `devon_hayes`, `lucia_martinez`, `hank_petrov`, `sam_okafor`, `marie_doucette`
**Night-shift ops:** `carl_brennan`, `annie_wong`, `tariq_hassan`
**Supplier voices:** `hiroshi_tanaka` (Yamashiro), `karthik_rao` (Cascade), `lim_boon_hwa` (PIP), `jurgen_becher` (Becher), `sandy_drysdale` (Drysdale)
**Customer reps:** `erika_lundgren` (SkyHawk), `daniel_park` (Tessera), `joel_mwangi` (Pylon)

### Tier slugs (`metadata.tier`)
`9A` (prosumer drone), `9B` (industrial / ag), `9C` (tactical-grade), `N/A`

### Hypothesis slugs (`metadata.hypothesis`)
`H1` (Yamashiro die batch variance — partial)
`H2` (Drysdale coating CTE — confirmed contributor)
`H3` (line 2 reflow profile drift — partial, ~30% line 2 elevation)
`H4` (night-shift fast-cal — ruled out)
`H5` (HVAC compressor magnetic interference — red herring, ruled out)
`H6` (PIP leadframe alloy substitution — confirmed contributor)
`N/A` (no hypothesis tag — observation, archive, noise)

### Calendar mapping
| Month | Real-window | Window-label |
|---|---|---|
| Archive | < 2025-09-01 | pre-M1 (June-Aug 2025 + Halcyon legacy Q3 2024) |
| M1 | 2025-09-01 → 2025-09-30 | September 2025 — surfacing |
| M2 | 2025-10-01 → 2025-10-31 | October — H5 ruled out, H4 surfaces |
| M3 | 2025-11-01 → 2025-11-30 | November — H4 ruled out, H3 surfaces |
| M4 | 2025-12-01 → 2025-12-31 | December — Sandia FA + H6 |
| M5 | 2026-01-01 → 2026-01-31 | January — H2 + H2+H6 confluence |
| M6 | 2026-02-01 → 2026-02-28 | February — remediation in motion |

---

## Distribution audit (against bible §7)

| Category (bible §7) | Target | Actual | Notes |
|---|---|---|---|
| Hypothesis epics (H1-H6) | 6 | 6 | T-0002…T-0007 |
| Other epics (master + spin-offs + retrofit + customer comms) | — | 7 | T-0001, T-0008-T-0013 |
| Shift observations / floor reports | ~60 | 62 | Distributed across 6 months × 3 shifts |
| QC test results / FA reports | ~50 | 51 | Sandia + IQC + DOE etc. |
| Supplier-event tickets | ~40 | 41 | All 8 suppliers represented |
| Customer-report tickets | ~25 | 26 | SkyHawk monthly + ad-hoc per customer |
| Equipment-maintenance | ~20 | 21 | Line 2 reflow oven thread + general |
| Operator-interview / debrief | ~25 | 25 | H4 cluster + cal protocol |
| Dead-end / red-herring (H5 + misc) | ~30 | 31 | H5 cluster ~15 + scattered |
| Hypothesis-evidence relationship tickets | ~80 | 82 | The relational backbone |
| Tracking / housekeeping | ~35 | 35 | Status summaries, decisions |
| Archive (pre-M1) | ~30 | 30 | Tessera + Pylon + Halcyon + supplier-disclosures |
| **Total** | ~400 | **417** | |

| Hypothesis | Direct-tag count | Notes |
|---|---|---|
| H1 (Yamashiro) | 15 | Including H1 epic, supporting evidence, refutation, hold-out |
| H2 (Drysdale coating) | 19 | H2 epic + month-5 cluster + qualification follow-through |
| H3 (line 2 reflow) | 21 | H3 epic + DOE + thermocouple thread + fix rollout |
| H4 (night-shift) | 23 | H4 epic + interviews + Becher jig logs + spin-off epic ramp |
| H5 (HVAC) | 16 | H5 epic + ON/OFF study cluster |
| H6 (PIP leadframe) | 24 | H6 epic + Sandia evidence + escalation + alloy revert |
| N/A | 299 | observations, archive, noise, customer summaries, etc. |

| Month | Target | Actual | Notes |
|---|---|---|---|
| Archive | ~30 | 30 | T-0016-T-0045 |
| M1 (Sep) | ~50 | 50 | T-0046-T-0095 |
| M2 (Oct) | ~70 | 70 | T-0096-T-0165 |
| M3 (Nov) | ~80 | 80 | T-0166-T-0245 |
| M4 (Dec) | ~70 | 70 | T-0246-T-0315 |
| M5 (Jan) | ~70 | 70 | T-0316-T-0385 |
| M6 (Feb) | ~50 | 47 | T-0386-T-0417 (3 fewer; full count = 417) |

---

## Master roster — full table

Columns: **ID**, **type**, **title (truncated to ~80 chars in inventory; full text in manifest)**, **parent**, **hyp**, **category**, **assignee**, **month**, **planned comments**

(For brevity inventory titles are the "shorthand" version; the manifest carries the full title and descriptions.)

| ID | type | Title | parent | hyp | cat | assignee | mo | cmts |
|---|---|---|---|---|---|---|---|---|
| T-0001 | epic | ARES-9 winter gyro-Z drift investigation (master) | — | N/A | epic | marcus_chen | M1 | 4-10 |
| T-0002 | hypothesis | H1 — Yamashiro gyro die batch variance | T-0001 | H1 | epic | won_lee | M1 | 4-10 |
| T-0003 | hypothesis | H2 — Drysdale conformal coating thermal-stress amplifier | T-0001 | H2 | epic | priya_iyer | M5 | 4-10 |
| T-0004 | hypothesis | H3 — SMT line 2 reflow profile drift | T-0001 | H3 | epic | priya_iyer | M3 | 4-10 |
| T-0005 | hypothesis | H4 — Night-shift "fast-cal" abbreviated protocol | T-0001 | H4 | epic | won_lee | M2 | 4-10 |
| T-0006 | hypothesis | H5 — HVAC compressor magnetic interference | T-0001 | H5 | epic | priya_iyer | M2 | 4-10 |
| T-0007 | hypothesis | H6 — PIP leadframe alloy substitution | T-0001 | H6 | epic | won_lee | M4 | 4-10 |
| T-0008 | epic | Night-shift cal-protocol overhaul (H4 spin-off) | T-0001 | H4 | epic | dale_brennan | M3 | 4-10 |
| T-0009 | epic | Supplier governance / change-notification SOP revision | T-0001 | H6 | epic | won_lee | M5 | 4-10 |
| T-0010 | epic | RFO-002 line 2 reflow oven monthly cal SOP | T-0001 | H3 | epic | priya_iyer | M3 | 1-3 |
| T-0011 | epic | Drysdale coating chemistry tweak qualification | T-0001 | H2 | epic | sandy_drysdale | M5 | 4-10 |
| T-0012 | epic | Field retrofit program — SkyHawk/Pylon/Tessera re-coat | T-0001 | N/A | epic | diana_reyes | M6 | 4-10 |
| T-0013 | epic | Customer reliability comms — H2+H6 disclosure | T-0001 | N/A | epic | marcus_chen | M5 | 1-3 |
| T-0014 | decision | H5 ruled out — HVAC ON/OFF study null | T-0006 | H5 | housekeeping | priya_iyer | M2 | 0 |
| T-0015 | decision | H4 ruled out for cold-temp drift; spawned spin-off epic T-0008 | T-0005 | H4 | housekeeping | won_lee | M3 | 1-3 |

### Archive cluster (T-0016-T-0045) — pre-Sept 2025

| ID | type | Title shorthand | parent | hyp | cat | assignee | mo | cmts |
|---|---|---|---|---|---|---|---|---|
| T-0016 | archive | Halcyon Surgical 2024-Q3 contract cancellation closeout | — | N/A | archive | marcus_chen | arch | 1-3 |
| T-0017 | archive | Halcyon final FA — bond-stack legacy data retention | T-0016 | N/A | archive | won_lee | arch | 0 |
| T-0018 | archive | Halcyon retained units inventory — Boulder bonded storage | T-0016 | N/A | archive | diana_reyes | arch | 0 |
| T-0019 | archive | Halcyon root-cause memo (closed product, no follow-through) | T-0016 | N/A | archive | aravind_subramanian | arch | 0 |
| T-0020 | archive | Tessera 2025-04-22 ad-hoc reliability note — one-off gyro-Z slew | — | N/A | archive | daniel_park | arch | 1-3 |
| T-0021 | archive | Tessera 2025-05 reliability summary — minor outlier | — | N/A | archive | daniel_park | arch | 0 |
| T-0022 | archive | Tessera 2025-06-08 cold-flight test anomaly (deferred) | — | N/A | archive | daniel_park | arch | 1-3 |
| T-0023 | archive | Tessera 2025-07 reliability summary — no new flags | — | N/A | archive | daniel_park | arch | 0 |
| T-0024 | archive | Tessera 2025-08-02 unit return — RMA pass at +22°C | — | N/A | archive | won_lee | arch | 1-3 |
| T-0025 | archive | Tessera 2025-08-19 unit return — RMA pass at +22°C | — | N/A | archive | won_lee | arch | 0 |
| T-0026 | archive | Pylon 2025-05 monthly — one outlier, deferred | — | N/A | archive | joel_mwangi | arch | 0 |
| T-0027 | archive | Pylon 2025-06 monthly — no escalation | — | N/A | archive | joel_mwangi | arch | 0 |
| T-0028 | archive | Pylon 2025-07-14 Idaho cold-snap field note | — | N/A | archive | joel_mwangi | arch | 1-3 |
| T-0029 | archive | Pylon 2025-08-03 field debrief — line 2 unit pass at ambient | — | N/A | archive | won_lee | arch | 0 |
| T-0030 | supplier-event | Drysdale RoHS-3 reformulation disclosure (2025-02) | — | H2 | supplier-event | won_lee | arch | 1-3 |
| T-0031 | supplier-event | PIP 2025-Q1 audit — pre-substitution baseline | — | H6 | supplier-event | won_lee | arch | 0 |
| T-0032 | supplier-event | Yamashiro 200mm wafer-line transition notice (2025-Q3) | — | H1 | supplier-event | won_lee | arch | 1-3 |
| T-0033 | supplier-event | TaipeiSilicon Q3 ASIC die-shrink notice (informational) | — | N/A | supplier-event | won_lee | arch | 0 |
| T-0034 | supplier-event | Cascade 2025-Q2 magnetometer process tweak (no impact) | — | N/A | supplier-event | karthik_rao | arch | 0 |
| T-0035 | supplier-event | Frontline 2025-Q2 PCB stack-up update — re-qual passed | — | N/A | supplier-event | won_lee | arch | 0 |
| T-0036 | supplier-event | Becher cal-jig firmware 4.2 release notes (2025-Q2) | — | N/A | supplier-event | dale_brennan | arch | 0 |
| T-0037 | supplier-event | MIE 2025-Q2 overflow capacity confirm | — | N/A | supplier-event | diana_reyes | arch | 0 |
| T-0038 | archive | 2025-Q2 IQC review of Drysdale reformulation — sign-off | T-0030 | H2 | archive | won_lee | arch | 0 |
| T-0039 | archive | 2025-Q2 internal memo — PIP cost-reduction renewal | — | H6 | archive | aravind_subramanian | arch | 0 |
| T-0040 | archive | Routine 2025-Q2 calibration drift QA report | — | N/A | archive | dale_brennan | arch | 0 |
| T-0041 | archive | 2025-Q2 OSHA noise survey (unrelated) | — | N/A | archive | diana_reyes | arch | 0 |
| T-0042 | archive | 2025-08 forklift incident — Bay 4 (unrelated) | — | N/A | archive | diana_reyes | arch | 1-3 |
| T-0043 | archive | 2025-08 fire-extinguisher inspection (unrelated) | — | N/A | archive | diana_reyes | arch | 0 |
| T-0044 | archive | 2025-Q2 SOX inventory audit (unrelated) | — | N/A | archive | marcus_chen | arch | 0 |
| T-0045 | archive | 2025-08 SkyHawk QBR meeting notes (no defect flags) | — | N/A | archive | marcus_chen | arch | 0 |

### M1 cluster (T-0046-T-0095) — September 2025, surfacing

| ID | type | Title shorthand | parent | hyp | cat | assignee | mo | cmts |
|---|---|---|---|---|---|---|---|---|
| T-0046 | customer-report | SkyHawk 2025-09 monthly reliability summary — gyro-Z slew uplift | T-0001 | N/A | customer-report | erika_lundgren | M1 | 4-10 |
| T-0047 | observation | Reviewing SkyHawk attachment — 4.2% sub-(-10C) fail rate stands out | T-0046 | N/A | observation | marcus_chen | M1 | 1-3 |
| T-0048 | decision | Open master investigation epic — assign Won, loop Priya/Dale | T-0001 | N/A | housekeeping | marcus_chen | M1 | 0 |
| T-0049 | evidence | Batch genealogy pull — 9A SkyHawk failed-unit serial sweep | T-0002 | H1 | evidence | won_lee | M1 | 1-3 |
| T-0050 | evidence | Yamashiro lot trace — 70% of failures on lots Y25-W31 / Y25-W34 | T-0002 | H1 | evidence | won_lee | M1 | 4-10 |
| T-0051 | supplier-event | Yamashiro escalation 1 — Hiroshi Tanaka pushback on lot-trace data | T-0002 | H1 | supplier-event | won_lee | M1 | 4-10 |
| T-0052 | evidence | Yamashiro internal QC pull — no signal at the die level | T-0002 | H1 | evidence | hiroshi_tanaka | M1 | 1-3 |
| T-0053 | observation | Day-shift line 1 — gyro-Z bench cal slightly noisy on first run-of-day | — | N/A | observation | rosa_calderon | M1 | 0 |
| T-0054 | observation | Bay 3 air handler running loud again — noise complaint | — | N/A | observation | tomas_aguilar | M1 | 0 |
| T-0055 | observation | Swing line 2 — reflow oven RFO-002 thermocouple reading variance noted | — | N/A | observation | devon_hayes | M1 | 1-3 |
| T-0056 | observation | Night line 1 — uneventful shift, all checks pass | — | N/A | observation | carl_brennan | M1 | 0 |
| T-0057 | maintenance | RFO-002 monthly preventive — filter change | — | N/A | maintenance | tomas_aguilar | M1 | 0 |
| T-0058 | observation | 9C cal-bay 2 — Becher jig thermal soak cycle 30s long, within tol | — | N/A | observation | annie_wong | M1 | 0 |
| T-0059 | observation | Reel changeover on SMT-1 — Cascade accel die reel ran short | — | N/A | observation | jen_park | M1 | 0 |
| T-0060 | observation | Day-shift huddle 09-09 — Marcus mentioned SkyHawk uplift | — | N/A | observation | karen_holloway | M1 | 0 |
| T-0061 | observation | Conformal coat booth chemistry low alarm on tank 2 — refilled | — | H2 | observation | marie_doucette | M1 | 1-3 |
| T-0062 | observation | RFO-002 reflow profile — recipe AR9-B-V12 ran short by 4s peak time | — | H3 | observation | hank_petrov | M1 | 1-3 |
| T-0063 | evidence | Priya begins reflow-profile data pull — 18-month SMT trace request | T-0001 | H3 | evidence | priya_iyer | M1 | 1-3 |
| T-0064 | observation | Marcus Jr. — noted gyro-Z final-test re-run on unit S25-09-1184 | — | H1 | observation | marcus_wright_jr | M1 | 0 |
| T-0065 | observation | Swing-shift end-of-shift — re-run rate slightly elevated for the week | — | N/A | observation | lucia_martinez | M1 | 1-3 |
| T-0066 | observation | Bay 3 HVAC — compressor cycling more than usual after Wed cold front | — | H5 | observation | sam_okafor | M1 | 0 |
| T-0067 | observation | Day-shift — 9B Pylon batch ran clean | — | N/A | observation | rosa_calderon | M1 | 0 |
| T-0068 | observation | Night-shift cal-bay 1 — Carl noted his crew uses fast-cal sequence | — | H4 | observation | carl_brennan | M1 | 1-3 |
| T-0069 | observation | 9A unit S25-09-1402 — gyro-Z bias re-run on first pass | — | H1 | observation | jen_park | M1 | 0 |
| T-0070 | evidence | Won's first H1 summary — 70% lot-correlation with Y25-W31/W34 | T-0002 | H1 | evidence | won_lee | M1 | 1-3 |
| T-0071 | observation | Re-zero of accelerometer fixture A2 — drift within spec | — | N/A | observation | tariq_hassan | M1 | 0 |
| T-0072 | observation | Coating thickness Mahr gauge — 18.7um avg (target 17.5±2) | — | H2 | observation | marie_doucette | M1 | 0 |
| T-0073 | observation | Drysdale tank 1 batch # DR25-117 — labeled, in service | — | H2 | observation | marie_doucette | M1 | 0 |
| T-0074 | supplier-event | Yamashiro escalation 2 — Hiroshi requesting failed-unit FA images | T-0002 | H1 | supplier-event | won_lee | M1 | 4-10 |
| T-0075 | maintenance | RFO-001 line 1 reflow oven — quarterly cal pass | — | N/A | maintenance | hank_petrov | M1 | 0 |
| T-0076 | maintenance | SMT-2 pick-and-place head 3 nozzle replacement | — | N/A | maintenance | hank_petrov | M1 | 0 |
| T-0077 | interview | Carl Brennan informal chat — cal-bay procedures (not formal) | — | H4 | interview | dale_brennan | M1 | 1-3 |
| T-0078 | observation | 9C bay 4 cal — Becher jig 4 firmware version 4.2.1 confirmed | — | N/A | observation | annie_wong | M1 | 0 |
| T-0079 | observation | IQC inbound — PIP shipment 2025-W37 received, COC attached | — | H6 | observation | won_lee | M1 | 0 |
| T-0080 | observation | IQC inbound — Drysdale tank refill DR25-119 received | — | H2 | observation | won_lee | M1 | 0 |
| T-0081 | customer-report | Pylon ad-hoc 2025-09-22 — Idaho substation cold-soak flight reported | T-0001 | N/A | customer-report | joel_mwangi | M1 | 1-3 |
| T-0082 | observation | Day-shift — operator Karen suggested running cal-room temp lower | — | N/A | observation | karen_holloway | M1 | 0 |
| T-0083 | observation | Swing-shift — Devon noted Y25-W34 reel ran clean visually | — | H1 | observation | devon_hayes | M1 | 0 |
| T-0084 | evidence | 9B Pylon Idaho unit S25-04-0837 RMA pass at +22C | T-0081 | N/A | evidence | won_lee | M1 | 1-3 |
| T-0085 | observation | Night-shift end — Annie noted spec sheet copy for 9C cal still v1.4 | — | H4 | observation | annie_wong | M1 | 0 |
| T-0086 | evidence | Priya — line 2 reflow recipe history pull complete, 18 mos of runs | T-0004 | H3 | evidence | priya_iyer | M1 | 1-3 |
| T-0087 | observation | Reflow profile delta — line 2 peak 245-248C target, last 30 days drifting | — | H3 | observation | priya_iyer | M1 | 0 |
| T-0088 | observation | Day-shift — Rosa flagged minor solder-paste bridging on board E227 | — | N/A | observation | rosa_calderon | M1 | 1-3 |
| T-0089 | maintenance | AC unit A4 condensate drain cleared | — | N/A | maintenance | tomas_aguilar | M1 | 0 |
| T-0090 | observation | Cal-room ambient — 21.8C avg over Mon-Fri week of 09-15 | — | N/A | observation | dale_brennan | M1 | 0 |
| T-0091 | observation | Swing-shift — Marie noted conformal-coat cure-oven cycle short | — | H2 | observation | marie_doucette | M1 | 1-3 |
| T-0092 | observation | Night-shift — Carl mentioned fast-cal protocol picked up speed | — | H4 | observation | carl_brennan | M1 | 0 |
| T-0093 | housekeeping | Weekly investigation status (week 1) — H1 leading, others surveying | T-0001 | N/A | housekeeping | marcus_chen | M1 | 0 |
| T-0094 | housekeeping | Weekly investigation status (week 2) — Yamashiro pushback noted | T-0001 | N/A | housekeeping | marcus_chen | M1 | 0 |
| T-0095 | housekeeping | Weekly investigation status (week 3) — Priya reflow data due 09-26 | T-0001 | N/A | housekeeping | marcus_chen | M1 | 0 |

### M2 cluster (T-0096-T-0165) — October 2025, H5 ruled out, H4 surfaces

| ID | type | Title shorthand | parent | hyp | cat | assignee | mo | cmts |
|---|---|---|---|---|---|---|---|---|
| T-0096 | customer-report | SkyHawk 2025-10 monthly summary — 4.6% sub-(-10C) fail rate | T-0001 | N/A | customer-report | erika_lundgren | M2 | 4-10 |
| T-0097 | observation | Yamashiro Y25-W34 lot — IQC re-screen pass, no anomaly | T-0002 | H1 | observation | won_lee | M2 | 1-3 |
| T-0098 | evidence | H1 status pulse — correlation but no causation yet | T-0002 | H1 | evidence | won_lee | M2 | 1-3 |
| T-0099 | supplier-event | Yamashiro Tanaka — counter-FA on 4 returns, no die-level signal | T-0002 | H1 | supplier-event | hiroshi_tanaka | M2 | 4-10 |
| T-0100 | hypothesis | H5 open — Bay 3 HVAC compressor magnetic field theory | T-0001 | H5 | evidence | priya_iyer | M2 | 1-3 |
| T-0101 | evidence | Priya — HVAC ON/OFF study protocol drafted | T-0006 | H5 | evidence | priya_iyer | M2 | 1-3 |
| T-0102 | evidence | HVAC ON/OFF study day 1 — baseline | T-0006 | H5 | evidence | priya_iyer | M2 | 0 |
| T-0103 | evidence | HVAC ON/OFF study day 3 — compressor OFF cal-bay | T-0006 | H5 | evidence | priya_iyer | M2 | 0 |
| T-0104 | evidence | HVAC ON/OFF study day 5 — compressor ON cal-bay | T-0006 | H5 | evidence | priya_iyer | M2 | 0 |
| T-0105 | evidence | HVAC ON/OFF study day 7 — mid-week update | T-0006 | H5 | evidence | priya_iyer | M2 | 0 |
| T-0106 | evidence | HVAC ON/OFF study day 9 — second week start | T-0006 | H5 | evidence | priya_iyer | M2 | 0 |
| T-0107 | evidence | HVAC ON/OFF study day 11 — mag field survey | T-0006 | H5 | evidence | priya_iyer | M2 | 0 |
| T-0108 | evidence | HVAC ON/OFF study day 13 — final data pull | T-0006 | H5 | evidence | priya_iyer | M2 | 0 |
| T-0109 | evidence | HVAC ON/OFF study final report — no correlation, p>0.4 | T-0006 | H5 | evidence | priya_iyer | M2 | 1-3 |
| T-0110 | maintenance | Bay 3 air handler bearing service (unrelated to H5) | — | N/A | maintenance | tomas_aguilar | M2 | 0 |
| T-0111 | evidence | Mag-field probe survey — no signal at cal-bay locations | T-0006 | H5 | evidence | priya_iyer | M2 | 1-3 |
| T-0112 | evidence | Cal-bay 1 mag survey — 0.4uT background, within tol | T-0006 | H5 | evidence | priya_iyer | M2 | 0 |
| T-0113 | evidence | Cal-bay 2 mag survey — 0.5uT background, within tol | T-0006 | H5 | evidence | priya_iyer | M2 | 0 |
| T-0114 | evidence | Cal-bay 3 mag survey — 0.4uT background, within tol | T-0006 | H5 | evidence | priya_iyer | M2 | 0 |
| T-0115 | evidence | Cal-bay 4 mag survey — 0.6uT background, within tol | T-0006 | H5 | evidence | priya_iyer | M2 | 0 |
| T-0116 | observation | Dale flag — night-shift cal protocol shortened (Q4 2024 unauthorized) | T-0005 | H4 | observation | dale_brennan | M2 | 1-3 |
| T-0117 | decision | Marcus assigns Won as independent investigator for H4 | T-0005 | H4 | housekeeping | marcus_chen | M2 | 1-3 |
| T-0118 | observation | Cal-protocol AR9-CAL-NIGHT-001 — 6 steps instead of doc'd 11 | T-0005 | H4 | observation | won_lee | M2 | 0 |
| T-0119 | evidence | Becher jig firmware log pull — bay 1 night-shift, 90 days | T-0005 | H4 | evidence | won_lee | M2 | 1-3 |
| T-0120 | evidence | Becher jig firmware log pull — bay 2 night-shift, 90 days | T-0005 | H4 | evidence | won_lee | M2 | 0 |
| T-0121 | evidence | Becher jig firmware log pull — bay 3 night-shift, 90 days | T-0005 | H4 | evidence | won_lee | M2 | 0 |
| T-0122 | evidence | Becher jig firmware log pull — bay 4 night-shift, 90 days | T-0005 | H4 | evidence | won_lee | M2 | 0 |
| T-0123 | interview | Operator interview — Carl Brennan (night cal lead) | T-0005 | H4 | interview | won_lee | M2 | 4-10 |
| T-0124 | interview | Operator interview — Annie Wong (night cal #2) | T-0005 | H4 | interview | won_lee | M2 | 1-3 |
| T-0125 | interview | Operator interview — Tariq Hassan (night cal #3) | T-0005 | H4 | interview | won_lee | M2 | 1-3 |
| T-0126 | customer-report | Tessera 2025-10-12 ad-hoc — Cdr Park escalation, AK exercise | T-0001 | N/A | customer-report | daniel_park | M2 | 4-10 |
| T-0127 | observation | Day-shift — Rosa noted 9A line 1 final-test queue building | — | N/A | observation | rosa_calderon | M2 | 0 |
| T-0128 | observation | Cal-bay 2 — Devon retorqued bay fixture, baseline restored | — | N/A | observation | devon_hayes | M2 | 0 |
| T-0129 | observation | Reflow profile RFO-002 — peak temp 252C noted on board E445 | — | H3 | observation | hank_petrov | M2 | 1-3 |
| T-0130 | observation | Conformal coat — bath chemistry # DR25-119, in service | — | H2 | observation | marie_doucette | M2 | 0 |
| T-0131 | observation | IQC PIP shipment 2025-W41 — visual inspection clean | — | H6 | observation | won_lee | M2 | 0 |
| T-0132 | observation | Day-shift — Karen tested 9B Pylon batch, all in spec | — | N/A | observation | karen_holloway | M2 | 0 |
| T-0133 | observation | Jen Park — gyro-Z final-test re-run rate trending up wk 41 | — | H1 | observation | jen_park | M2 | 1-3 |
| T-0134 | maintenance | SMT-1 stencil clean cycle adjusted | — | N/A | maintenance | hank_petrov | M2 | 0 |
| T-0135 | maintenance | Cal-bay 3 desiccant cartridge replacement | — | N/A | maintenance | tomas_aguilar | M2 | 0 |
| T-0136 | observation | Marie noted cure-oven exhaust fan louder than usual | — | H2 | observation | marie_doucette | M2 | 0 |
| T-0137 | observation | Annie — gyro-Z drift bench data on returned S25-08-0996 odd shape | — | H1 | observation | annie_wong | M2 | 1-3 |
| T-0138 | supplier-event | Drysdale outreach — Won asked about RoHS-3 CTE published data | T-0003 | H2 | supplier-event | won_lee | M2 | 4-10 |
| T-0139 | supplier-event | Drysdale response — Sandy sent published TGA + DSC plots | T-0003 | H2 | supplier-event | sandy_drysdale | M2 | 1-3 |
| T-0140 | observation | Reflow oven RFO-002 — Priya pulled controller log dump | — | H3 | observation | priya_iyer | M2 | 1-3 |
| T-0141 | evidence | Priya — RFO-002 thermocouple calibration last touched 2024-08 | T-0004 | H3 | evidence | priya_iyer | M2 | 1-3 |
| T-0142 | observation | Day-shift — Tomás noted bay 1 cal-jig vibration sensor amber | — | N/A | observation | tomas_aguilar | M2 | 0 |
| T-0143 | observation | Marcus Jr — final-test fail on S25-10-0334 re-passed clean | — | H1 | observation | marcus_wright_jr | M2 | 0 |
| T-0144 | observation | Swing-shift — Lucia retorqued 9B reel cradle | — | N/A | observation | lucia_martinez | M2 | 0 |
| T-0145 | observation | Bay 3 HVAC compressor — replaced fan motor (unrelated; old wear) | — | N/A | observation | tomas_aguilar | M2 | 0 |
| T-0146 | maintenance | Bay 3 HVAC compressor fan motor replacement work order | T-0145 | N/A | maintenance | tomas_aguilar | M2 | 0 |
| T-0147 | observation | Cal-bay 4 — Annie noted Becher jig fan cycling extra | — | N/A | observation | annie_wong | M2 | 0 |
| T-0148 | observation | Tariq — gyro-Z bench data S25-09-1184 looks like the SkyHawk slew | — | H1 | observation | tariq_hassan | M2 | 1-3 |
| T-0149 | observation | Sam Okafor — accel-Y re-zero on S25-10-0721, within tol | — | N/A | observation | sam_okafor | M2 | 0 |
| T-0150 | observation | Hank — SMT line 2 reel splice issue, recovered within 12 min | — | N/A | observation | hank_petrov | M2 | 0 |
| T-0151 | observation | Day-shift huddle — Marcus mentioned H4 surfacing | — | H4 | observation | rosa_calderon | M2 | 0 |
| T-0152 | observation | Night-shift — Carl asked Won about the cal-protocol review | — | H4 | observation | carl_brennan | M2 | 1-3 |
| T-0153 | observation | Day-shift — Jen flagged solder-paste viscosity drift on stencil | — | N/A | observation | jen_park | M2 | 0 |
| T-0154 | observation | Hank — replaced N2 bottle on RFO-002, normal cycle | — | N/A | observation | hank_petrov | M2 | 0 |
| T-0155 | observation | Marie — Drysdale tank #2 chemistry sample sent to IQC | — | H2 | observation | marie_doucette | M2 | 0 |
| T-0156 | supplier-event | PIP routine ship-confirm — shipment 2025-W42 ETA | T-0007 | H6 | supplier-event | lim_boon_hwa | M2 | 0 |
| T-0157 | supplier-event | Cascade — routine ship-confirm 2025-W41 (uneventful) | — | N/A | supplier-event | karthik_rao | M2 | 0 |
| T-0158 | supplier-event | TaipeiSilicon ASIC ship-confirm 2025-W42 | — | N/A | supplier-event | won_lee | M2 | 0 |
| T-0159 | supplier-event | Becher firmware advisory 4.2.2 — security patch | — | N/A | supplier-event | jurgen_becher | M2 | 0 |
| T-0160 | maintenance | Becher cal-jig 4 firmware updated 4.2.1 → 4.2.2 | T-0159 | N/A | maintenance | dale_brennan | M2 | 0 |
| T-0161 | housekeeping | Weekly status M2-W1 — H5 study running, H1 hold | T-0001 | N/A | housekeeping | marcus_chen | M2 | 0 |
| T-0162 | housekeeping | Weekly status M2-W2 — H5 null, H4 surfaced | T-0001 | H4 | housekeeping | marcus_chen | M2 | 0 |
| T-0163 | housekeeping | Weekly status M2-W3 — H4 in interviews | T-0001 | H4 | housekeeping | marcus_chen | M2 | 0 |
| T-0164 | housekeeping | Weekly status M2-W4 — H4 wrapping, next-month plan | T-0001 | H4 | housekeeping | marcus_chen | M2 | 0 |
| T-0165 | observation | Customer success internal — SkyHawk asked about expected fix ETA | — | N/A | observation | marcus_chen | M2 | 1-3 |

### M3 cluster (T-0166-T-0245) — November 2025, H4 ruled out, H3 surfaces

| ID | type | Title shorthand | parent | hyp | cat | assignee | mo | cmts |
|---|---|---|---|---|---|---|---|---|
| T-0166 | customer-report | SkyHawk 2025-11 monthly — 5.1% sub-(-10C) fail rate trend | T-0001 | N/A | customer-report | erika_lundgren | M3 | 4-10 |
| T-0167 | evidence | Won — H4 night-shift protocol replication on day-shift units | T-0005 | H4 | evidence | won_lee | M3 | 1-3 |
| T-0168 | evidence | Replication result — ambient cal-repeatability ~15% worse w/ shortcut | T-0005 | H4 | evidence | won_lee | M3 | 1-3 |
| T-0169 | evidence | Replication — NO cold-temperature drift hysteresis from shortcut | T-0005 | H4 | evidence | won_lee | M3 | 1-3 |
| T-0170 | evidence | Field-return cross-check — failed units NOT preferentially night-built | T-0005 | H4 | evidence | won_lee | M3 | 1-3 |
| T-0171 | evidence | Becher jig firmware log analysis — temp soak profiles by shift | T-0005 | H4 | evidence | won_lee | M3 | 1-3 |
| T-0172 | decision | H4 ruled out as load-bearing for cold-temp drift | T-0005 | H4 | housekeeping | won_lee | M3 | 1-3 |
| T-0173 | decision | Open spin-off epic T-0008 for cal-protocol overhaul (independent) | T-0008 | H4 | housekeeping | marcus_chen | M3 | 1-3 |
| T-0174 | observation | Dale — vindicated on the shortcut existing; not the field defect | T-0008 | H4 | observation | dale_brennan | M3 | 1-3 |
| T-0175 | interview | Carl Brennan debrief — agreed to revised protocol | T-0008 | H4 | interview | dale_brennan | M3 | 1-3 |
| T-0176 | interview | Annie Wong debrief — concurred with revision | T-0008 | H4 | interview | dale_brennan | M3 | 0 |
| T-0177 | interview | Tariq Hassan debrief — concurred | T-0008 | H4 | interview | dale_brennan | M3 | 0 |
| T-0178 | evidence | Priya — line 2 build pull-rate vs failure correlation | T-0004 | H3 | evidence | priya_iyer | M3 | 1-3 |
| T-0179 | evidence | Pull-rate result — line 2 builds 3.2× over-represented in failures | T-0004 | H3 | evidence | priya_iyer | M3 | 1-3 |
| T-0180 | hypothesis | H3 surfaces — line 2 reflow profile drift theory | T-0001 | H3 | evidence | priya_iyer | M3 | 1-3 |
| T-0181 | evidence | DOE design — RFO-002 thermocouple variance study | T-0004 | H3 | evidence | priya_iyer | M3 | 1-3 |
| T-0182 | evidence | DOE day 1 — TC1 reading 245C vs board IR pyrometer 252C | T-0004 | H3 | evidence | priya_iyer | M3 | 0 |
| T-0183 | evidence | DOE day 3 — TC2/TC3 deltas confirmed | T-0004 | H3 | evidence | priya_iyer | M3 | 0 |
| T-0184 | evidence | DOE day 5 — controller firmware in 7C-hot regime confirmed | T-0004 | H3 | evidence | priya_iyer | M3 | 1-3 |
| T-0185 | supplier-event | RFO-002 vendor (Aoyama Reflow) firmware issue ticket opened | T-0010 | H3 | supplier-event | priya_iyer | M3 | 4-10 |
| T-0186 | evidence | DOE day 7 — thermocouple aging characterized | T-0004 | H3 | evidence | priya_iyer | M3 | 0 |
| T-0187 | decision | Thermocouple replacement parts ordered | T-0010 | H3 | housekeeping | priya_iyer | M3 | 0 |
| T-0188 | maintenance | RFO-002 thermocouple replacement work order | T-0010 | H3 | maintenance | hank_petrov | M3 | 1-3 |
| T-0189 | maintenance | RFO-002 controller firmware patch deployment | T-0010 | H3 | maintenance | priya_iyer | M3 | 0 |
| T-0190 | decision | Monthly TC calibration SOP added to RFO-002 PM schedule | T-0010 | H3 | housekeeping | priya_iyer | M3 | 0 |
| T-0191 | evidence | H3 attribution — ~30% of line 2 failure rate elevation explained | T-0004 | H3 | evidence | priya_iyer | M3 | 1-3 |
| T-0192 | evidence | H3 does NOT explain line 1 unit failures — still open gap | T-0004 | H3 | evidence | priya_iyer | M3 | 1-3 |
| T-0193 | observation | Hank — RFO-002 post-fix peak temp 247C clean profile | — | H3 | observation | hank_petrov | M3 | 1-3 |
| T-0194 | observation | Devon — first 9B Pylon batch on post-fix RFO-002 clean | — | H3 | observation | devon_hayes | M3 | 0 |
| T-0195 | observation | Day-shift — Rosa noted final-test re-run rate dropping | — | N/A | observation | rosa_calderon | M3 | 0 |
| T-0196 | observation | Cold week — outdoor ambient -8C, indoor cal-room steady | — | N/A | observation | tomas_aguilar | M3 | 0 |
| T-0197 | observation | Conformal coat — Marie noted tank #3 chemistry due rotation | — | H2 | observation | marie_doucette | M3 | 0 |
| T-0198 | customer-report | Pylon 2025-11-08 monthly — uplift visible in NE units | T-0001 | N/A | customer-report | joel_mwangi | M3 | 1-3 |
| T-0199 | customer-report | Tessera 2025-11-15 escalation — Cdr Park demands root cause | T-0001 | N/A | customer-report | daniel_park | M3 | 4-10 |
| T-0200 | observation | Night-shift Annie — revised cal protocol week 1 ran clean | T-0008 | H4 | observation | annie_wong | M3 | 0 |
| T-0201 | observation | Night Carl — revised protocol added 4 min per unit, manageable | T-0008 | H4 | observation | carl_brennan | M3 | 1-3 |
| T-0202 | observation | Tariq — re-trained on revised protocol | T-0008 | H4 | observation | tariq_hassan | M3 | 0 |
| T-0203 | observation | IQC — PIP shipment 2025-W46 unremarkable | — | H6 | observation | won_lee | M3 | 0 |
| T-0204 | observation | IQC — Drysdale tank refill DR25-127 in service | — | H2 | observation | won_lee | M3 | 0 |
| T-0205 | observation | Cal-bay 1 humidity probe replaced (annual cal) | — | N/A | observation | dale_brennan | M3 | 0 |
| T-0206 | observation | Jen — solder-paste fresh batch, viscosity good | — | N/A | observation | jen_park | M3 | 0 |
| T-0207 | observation | Sam — accel-X re-zero on S25-11-0118 within tol | — | N/A | observation | sam_okafor | M3 | 0 |
| T-0208 | observation | Lucia — swing-shift quiet, no observations | — | N/A | observation | lucia_martinez | M3 | 0 |
| T-0209 | observation | Marie — cure-oven exhaust replaced motor cap | — | N/A | observation | marie_doucette | M3 | 0 |
| T-0210 | maintenance | SMT-2 mid-month preventive | — | N/A | maintenance | hank_petrov | M3 | 0 |
| T-0211 | maintenance | Cal-bay 3 jig 3 servo encoder cleaned | — | N/A | maintenance | dale_brennan | M3 | 0 |
| T-0212 | observation | Pre-shipment QC — 9C Tessera batch hold for re-screen | — | N/A | observation | won_lee | M3 | 1-3 |
| T-0213 | observation | 9A SkyHawk pre-ship — re-screen rate 0.4% (normal) | — | N/A | observation | jen_park | M3 | 0 |
| T-0214 | observation | Day Karen — coating thickness Mahr 19.1um avg | — | H2 | observation | karen_holloway | M3 | 0 |
| T-0215 | observation | Coating thickness creeping up vs Q3 baseline | — | H2 | observation | priya_iyer | M3 | 1-3 |
| T-0216 | evidence | Priya note — coating-thickness trend may overlap H2 (parked) | T-0003 | H2 | evidence | priya_iyer | M3 | 1-3 |
| T-0217 | observation | Hank — RFO-002 second pass with TC replacement clean | — | H3 | observation | hank_petrov | M3 | 0 |
| T-0218 | observation | Tomás — bay 2 ambient drift after door open during truck load | — | N/A | observation | tomas_aguilar | M3 | 0 |
| T-0219 | observation | Jen — gyro-Z final-test S25-11-0982 re-run, passed | — | H1 | observation | jen_park | M3 | 0 |
| T-0220 | supplier-event | Yamashiro confirmation — Y25-W31/W34 lots cleared | T-0002 | H1 | supplier-event | hiroshi_tanaka | M3 | 1-3 |
| T-0221 | evidence | H1 status — leaving open as "partial correlation, no causation" | T-0002 | H1 | evidence | won_lee | M3 | 1-3 |
| T-0222 | supplier-event | PIP shipment 2025-W47 — visual COC inspection (passed) | T-0007 | H6 | supplier-event | won_lee | M3 | 0 |
| T-0223 | supplier-event | Drysdale shipment 2025-W47 reformulation batch DR25-129 | T-0003 | H2 | supplier-event | won_lee | M3 | 0 |
| T-0224 | supplier-event | TaipeiSilicon ASIC ship-confirm 2025-W47 | — | N/A | supplier-event | won_lee | M3 | 0 |
| T-0225 | supplier-event | Cascade ship-confirm 2025-W46 | — | N/A | supplier-event | karthik_rao | M3 | 0 |
| T-0226 | supplier-event | Frontline PCB ship-confirm 2025-W45 | — | N/A | supplier-event | won_lee | M3 | 0 |
| T-0227 | observation | RFO-002 — 2 weeks post-fix, no thermal alarm | T-0010 | H3 | observation | hank_petrov | M3 | 0 |
| T-0228 | evidence | H3 — line 1 unit failures still unexplained gap noted | T-0004 | H3 | evidence | priya_iyer | M3 | 1-3 |
| T-0229 | interview | All-hands debrief — H4 close out + H3 fix in motion | T-0001 | N/A | interview | marcus_chen | M3 | 1-3 |
| T-0230 | housekeeping | Customer comms — preliminary SkyHawk update on H3 | T-0001 | N/A | housekeeping | marcus_chen | M3 | 1-3 |
| T-0231 | housekeeping | Customer comms — preliminary Pylon update on H3 | T-0001 | N/A | housekeeping | marcus_chen | M3 | 0 |
| T-0232 | housekeeping | Customer comms — preliminary Tessera update on H3 (Cdr Park) | T-0001 | N/A | housekeeping | marcus_chen | M3 | 1-3 |
| T-0233 | decision | Engage Sandia FA lab service contract for deep-dive | T-0001 | N/A | housekeeping | marcus_chen | M3 | 1-3 |
| T-0234 | evidence | Pull 3 RMA field-returns for Sandia destructive analysis | T-0007 | H6 | evidence | won_lee | M3 | 1-3 |
| T-0235 | observation | Aravind side-comment — line 1 fail rate troubling, push deeper | T-0001 | N/A | observation | aravind_subramanian | M3 | 1-3 |
| T-0236 | observation | Diana — staffing for retrofit prep "if it comes to that" | T-0012 | N/A | observation | diana_reyes | M3 | 0 |
| T-0237 | observation | Day-shift huddle 11-22 — Marcus updated team on Sandia plan | — | N/A | observation | rosa_calderon | M3 | 0 |
| T-0238 | observation | IQC — Becher jig sw advisory 4.2.3 — no action req | — | N/A | observation | dale_brennan | M3 | 0 |
| T-0239 | observation | Karen — 9A reels low on Cascade accel die — JIT alert | — | N/A | observation | karen_holloway | M3 | 0 |
| T-0240 | observation | Bay 1 IR pyrometer cal due — scheduled | — | N/A | observation | tomas_aguilar | M3 | 0 |
| T-0241 | observation | Marie — Drysdale new tank labeling SOP updated | — | H2 | observation | marie_doucette | M3 | 0 |
| T-0242 | housekeeping | Weekly status M3-W1 — H4 ruled out, H3 in DOE | T-0001 | N/A | housekeeping | marcus_chen | M3 | 0 |
| T-0243 | housekeeping | Weekly status M3-W2 — H3 controller firmware identified | T-0001 | N/A | housekeeping | marcus_chen | M3 | 0 |
| T-0244 | housekeeping | Weekly status M3-W3 — H3 fix landed, line 1 gap noted | T-0001 | N/A | housekeeping | marcus_chen | M3 | 0 |
| T-0245 | housekeeping | Weekly status M3-W4 — Sandia engaged, awaiting results | T-0001 | N/A | housekeeping | marcus_chen | M3 | 0 |

### M4 cluster (T-0246-T-0315) — December 2025, Sandia FA + H6

| ID | type | Title shorthand | parent | hyp | cat | assignee | mo | cmts |
|---|---|---|---|---|---|---|---|---|
| T-0246 | customer-report | SkyHawk 2025-12 monthly — 5.6% trend, requesting weekly comms | T-0001 | N/A | customer-report | erika_lundgren | M4 | 4-10 |
| T-0247 | evidence | Sandia FA lab status — units shipped under NDA service contract | T-0007 | H6 | evidence | won_lee | M4 | 1-3 |
| T-0248 | evidence | Sandia FA preliminary — SEM imaging in progress | T-0007 | H6 | evidence | won_lee | M4 | 0 |
| T-0249 | evidence | Sandia FA result 1 — micro-cracking found at gyro-Z bond stack | T-0007 | H6 | evidence | won_lee | M4 | 4-10 |
| T-0250 | evidence | Sandia FA result 2 — pattern NOT consistent with ARESense alloy spec | T-0007 | H6 | evidence | won_lee | M4 | 1-3 |
| T-0251 | evidence | Sandia FA result 3 — leadframe composition deviates ~2.3% Sn higher | T-0007 | H6 | evidence | won_lee | M4 | 1-3 |
| T-0252 | hypothesis | H6 opens — PIP leadframe alloy substitution suspected | T-0001 | H6 | evidence | won_lee | M4 | 1-3 |
| T-0253 | supplier-event | PIP escalation 1 — initial query to Lim re: alloy COC | T-0007 | H6 | supplier-event | won_lee | M4 | 4-10 |
| T-0254 | supplier-event | PIP response 1 — Lim says "all shipments within spec envelope" | T-0007 | H6 | supplier-event | lim_boon_hwa | M4 | 1-3 |
| T-0255 | supplier-event | PIP escalation 2 — Won pushes back with Sandia SEM data | T-0007 | H6 | supplier-event | won_lee | M4 | 4-10 |
| T-0256 | supplier-event | PIP response 2 — Lim asks for time to consult QC team | T-0007 | H6 | supplier-event | lim_boon_hwa | M4 | 1-3 |
| T-0257 | supplier-event | PIP escalation 3 — Marcus + Aravind on call with Lim's leadership | T-0007 | H6 | supplier-event | marcus_chen | M4 | 4-10 |
| T-0258 | supplier-event | PIP DISCLOSURE — Lim confirms alloy substitution ~5 mos ago | T-0007 | H6 | supplier-event | lim_boon_hwa | M4 | 4-10 |
| T-0259 | decision | Escalation log — supplier governance gap formally flagged | T-0009 | H6 | housekeeping | marcus_chen | M4 | 1-3 |
| T-0260 | evidence | Cross-line analysis — H6 explains BOTH line 1 AND line 2 failures | T-0007 | H6 | evidence | won_lee | M4 | 1-3 |
| T-0261 | evidence | Failure-rate match — line 1 vs line 2 gap closes under H6 hypothesis | T-0007 | H6 | evidence | priya_iyer | M4 | 1-3 |
| T-0262 | evidence | Pre-substitution baseline — pull historical units, no micro-cracks | T-0007 | H6 | evidence | won_lee | M4 | 1-3 |
| T-0263 | evidence | Post-substitution units — Sandia SEM survey on 5 archive units | T-0007 | H6 | evidence | won_lee | M4 | 1-3 |
| T-0264 | observation | Day-shift Karen — visual on PIP shipment 2025-W49 unremarkable | — | H6 | observation | karen_holloway | M4 | 0 |
| T-0265 | observation | Marcus Jr — coating cure-oven kicked over to standby briefly | — | H2 | observation | marcus_wright_jr | M4 | 1-3 |
| T-0266 | observation | Night-shift — revised cal protocol month 1 stable | T-0008 | H4 | observation | annie_wong | M4 | 0 |
| T-0267 | observation | Cold-snap week — outdoor low -16C, indoor steady | — | N/A | observation | tomas_aguilar | M4 | 0 |
| T-0268 | customer-report | Pylon 2025-12-09 monthly — substation NE cold-soak uptick | T-0001 | N/A | customer-report | joel_mwangi | M4 | 1-3 |
| T-0269 | customer-report | Tessera 2025-12-14 escalation — Cdr Park demands written timeline | T-0001 | N/A | customer-report | daniel_park | M4 | 4-10 |
| T-0270 | customer-report | GreenFurrow 2025-12-18 ad-hoc — first cold-temp report | T-0001 | N/A | customer-report | erika_lundgren | M4 | 1-3 |
| T-0271 | observation | RFO-002 post-H3 — 6 weeks clean, monthly TC cal landed | T-0010 | H3 | observation | hank_petrov | M4 | 0 |
| T-0272 | observation | Day-shift — Rosa noted final-test re-run rate trending higher again | — | H6 | observation | rosa_calderon | M4 | 1-3 |
| T-0273 | observation | Jen — re-run cluster on line 1 batch L1-25-12-04 | — | H6 | observation | jen_park | M4 | 0 |
| T-0274 | observation | Coating thickness — Mahr 19.5um avg, drifting upper-tol | — | H2 | observation | karen_holloway | M4 | 0 |
| T-0275 | observation | Marie — Drysdale tank #1 chemistry sample sent to IQC | — | H2 | observation | marie_doucette | M4 | 0 |
| T-0276 | observation | IQC chemistry test — Drysdale within published spec | — | H2 | observation | won_lee | M4 | 1-3 |
| T-0277 | observation | Hank — N2 bottle changeover RFO-002, normal | — | N/A | observation | hank_petrov | M4 | 0 |
| T-0278 | observation | Sam — accel re-zero swing-shift S25-12-0411 within tol | — | N/A | observation | sam_okafor | M4 | 0 |
| T-0279 | observation | Devon — line 2 quiet week, no observations | — | N/A | observation | devon_hayes | M4 | 0 |
| T-0280 | observation | Lucia — swing-shift cure-oven changeover routine | — | N/A | observation | lucia_martinez | M4 | 0 |
| T-0281 | observation | Tariq — night-shift revised cal protocol smooth | T-0008 | H4 | observation | tariq_hassan | M4 | 0 |
| T-0282 | observation | Annie — gyro-Z final-test on S25-12-0892, re-run pass | — | H6 | observation | annie_wong | M4 | 0 |
| T-0283 | observation | Cal-bay 4 — Annie noted Becher jig 4 vibration sensor amber again | — | N/A | observation | annie_wong | M4 | 0 |
| T-0284 | maintenance | Becher jig 4 vibration sensor replacement | T-0283 | N/A | maintenance | dale_brennan | M4 | 0 |
| T-0285 | maintenance | SMT-2 mid-Dec preventive | — | N/A | maintenance | hank_petrov | M4 | 0 |
| T-0286 | maintenance | Bay 2 air handler filter replacement | — | N/A | maintenance | tomas_aguilar | M4 | 0 |
| T-0287 | observation | IQC — PIP shipment 2025-W50 visual inspection clean | — | H6 | observation | won_lee | M4 | 0 |
| T-0288 | observation | Pre-disclosure 12-08 — Won pulled 24-mo PIP COC archive | T-0009 | H6 | observation | won_lee | M4 | 1-3 |
| T-0289 | observation | Pre-disclosure 12-09 — PIP alloy COCs identical across substitution | T-0009 | H6 | observation | won_lee | M4 | 1-3 |
| T-0290 | observation | Aravind ad-hoc — push for in-house leadframe XRF spot-check capability | T-0009 | H6 | observation | aravind_subramanian | M4 | 1-3 |
| T-0291 | observation | Marcus 12-15 huddle — H6 leading theory, formally communicate to cust | T-0013 | H6 | observation | marcus_chen | M4 | 1-3 |
| T-0292 | observation | Cold-soak retro — Tessera 2025-04 unit re-pulled from RMA storage | T-0007 | H6 | observation | won_lee | M4 | 1-3 |
| T-0293 | evidence | Tessera 2025-04 unit — Sandia SEM shows IDENTICAL micro-crack pattern | T-0007 | H6 | evidence | won_lee | M4 | 1-3 |
| T-0294 | observation | Pylon 2025-07 archive unit — pulled, Sandia send-out scheduled | T-0007 | H6 | observation | won_lee | M4 | 1-3 |
| T-0295 | observation | Marcus internal — early Tessera/Pylon were SAME defect, missed | T-0001 | H6 | observation | marcus_chen | M4 | 1-3 |
| T-0296 | observation | Diana — retrofit prep starting (units, slots, comms plan) | T-0012 | N/A | observation | diana_reyes | M4 | 1-3 |
| T-0297 | observation | Aravind — bond-redesign feasibility for 9A consumer tier kicked off | T-0011 | N/A | observation | aravind_subramanian | M4 | 1-3 |
| T-0298 | observation | Karen — 9A line ran clean week of 12-15 | — | N/A | observation | karen_holloway | M4 | 0 |
| T-0299 | observation | Day-shift Rosa — re-run rate down M4-W3 with new PIP shipment | — | H6 | observation | rosa_calderon | M4 | 1-3 |
| T-0300 | supplier-event | PIP escalation 4 — formal request for old alloy resumption | T-0009 | H6 | supplier-event | won_lee | M4 | 4-10 |
| T-0301 | supplier-event | PIP response — Lim agrees, schedules transition for late M5 | T-0009 | H6 | supplier-event | lim_boon_hwa | M4 | 1-3 |
| T-0302 | supplier-event | Yamashiro Tanaka — closure note on H1 (data-transparency commended) | T-0002 | H1 | supplier-event | hiroshi_tanaka | M4 | 1-3 |
| T-0303 | observation | Annie — night-shift quiet, revised protocol stable month 2 | T-0008 | H4 | observation | annie_wong | M4 | 0 |
| T-0304 | observation | Carl — night-shift staffing stable, no re-training needed | T-0008 | H4 | observation | carl_brennan | M4 | 0 |
| T-0305 | observation | Lucia — swing-shift quiet, end of M4 | — | N/A | observation | lucia_martinez | M4 | 0 |
| T-0306 | observation | Marie — Drysdale tank rotation routine | — | H2 | observation | marie_doucette | M4 | 0 |
| T-0307 | observation | Sam — accel-X re-zero on S25-12-1112 within tol | — | N/A | observation | sam_okafor | M4 | 0 |
| T-0308 | observation | Hank — RFO-002 post-fix month 2 clean | T-0010 | H3 | observation | hank_petrov | M4 | 0 |
| T-0309 | housekeeping | Customer comms M4 — H6 preliminary heads-up to SkyHawk | T-0013 | H6 | housekeeping | marcus_chen | M4 | 1-3 |
| T-0310 | housekeeping | Customer comms M4 — H6 preliminary heads-up to Pylon | T-0013 | H6 | housekeeping | marcus_chen | M4 | 1-3 |
| T-0311 | housekeeping | Customer comms M4 — H6 written timeline to Cdr Park (Tessera) | T-0013 | H6 | housekeeping | marcus_chen | M4 | 4-10 |
| T-0312 | housekeeping | Weekly status M4-W1 — Sandia results expected | T-0001 | N/A | housekeeping | marcus_chen | M4 | 0 |
| T-0313 | housekeeping | Weekly status M4-W2 — micro-crack finding, PIP escalation open | T-0001 | H6 | housekeeping | marcus_chen | M4 | 0 |
| T-0314 | housekeeping | Weekly status M4-W3 — H6 confirmed, line 1 gap still open question | T-0001 | H6 | housekeeping | marcus_chen | M4 | 0 |
| T-0315 | housekeeping | Weekly status M4-W4 — supplier governance epic spinning up | T-0009 | H6 | housekeeping | marcus_chen | M4 | 0 |

### M5 cluster (T-0316-T-0385) — January 2026, H2 + confluence

| ID | type | Title shorthand | parent | hyp | cat | assignee | mo | cmts |
|---|---|---|---|---|---|---|---|---|
| T-0316 | customer-report | SkyHawk 2026-01 monthly — 5.4% (flat); awaiting H6 fix | T-0001 | N/A | customer-report | erika_lundgren | M5 | 4-10 |
| T-0317 | evidence | Sandia round-2 FA — leadframe stress insufficient alone | T-0003 | H2 | evidence | won_lee | M5 | 4-10 |
| T-0318 | evidence | Bond-stress modeling — H6 alone underpredicts crack rate ~3.5× | T-0003 | H2 | evidence | aravind_subramanian | M5 | 1-3 |
| T-0319 | evidence | Marcus cross-references Q1 supplier calendar | T-0003 | H2 | evidence | marcus_chen | M5 | 1-3 |
| T-0320 | evidence | Drysdale RoHS-3 reformulation timing match noted | T-0003 | H2 | evidence | marcus_chen | M5 | 1-3 |
| T-0321 | hypothesis | H2 opens — Drysdale coating CTE amplifier theory | T-0001 | H2 | evidence | priya_iyer | M5 | 1-3 |
| T-0322 | evidence | Coating CTE testing — Priya pulled samples for TGA/DSC | T-0003 | H2 | evidence | priya_iyer | M5 | 1-3 |
| T-0323 | evidence | Coating CTE result — reformulated 12% higher CTE than legacy | T-0003 | H2 | evidence | priya_iyer | M5 | 1-3 |
| T-0324 | evidence | Combined-stress model — H2+H6 confluence matches field rate | T-0003 | H2 | evidence | aravind_subramanian | M5 | 4-10 |
| T-0325 | decision | H2+H6 CONFLUENCE declared root cause | T-0001 | H2 | housekeeping | marcus_chen | M5 | 4-10 |
| T-0326 | supplier-event | Drysdale engagement 1 — Sandy briefed on confluence finding | T-0011 | H2 | supplier-event | won_lee | M5 | 4-10 |
| T-0327 | supplier-event | Drysdale response 1 — Sandy proposes chemistry tweak path | T-0011 | H2 | supplier-event | sandy_drysdale | M5 | 1-3 |
| T-0328 | supplier-event | Drysdale qualification plan — 3-month timeline drafted | T-0011 | H2 | supplier-event | sandy_drysdale | M5 | 1-3 |
| T-0329 | evidence | Coating-thickness data review — drift correlation noted | T-0003 | H2 | evidence | priya_iyer | M5 | 1-3 |
| T-0330 | evidence | SPC plan — coating thickness control limits revised | T-0011 | H2 | evidence | priya_iyer | M5 | 1-3 |
| T-0331 | observation | Karen — coating Mahr readings returning toward baseline | — | H2 | observation | karen_holloway | M5 | 0 |
| T-0332 | observation | Marie — IQC chemistry sampling cadence increased | — | H2 | observation | marie_doucette | M5 | 0 |
| T-0333 | supplier-event | PIP transition timeline — confirmed cutover 2026-02-W2 | T-0009 | H6 | supplier-event | lim_boon_hwa | M5 | 1-3 |
| T-0334 | supplier-event | PIP 9A bond-redesign engagement 1 — Aravind + Lim | T-0011 | N/A | supplier-event | aravind_subramanian | M5 | 4-10 |
| T-0335 | supplier-event | PIP 9A bond-redesign engagement 2 — pattern proposals | T-0011 | N/A | supplier-event | lim_boon_hwa | M5 | 1-3 |
| T-0336 | decision | 9A consumer tier — accept redesigned bond pattern at price savings | T-0011 | N/A | housekeeping | aravind_subramanian | M5 | 1-3 |
| T-0337 | decision | 9B/9C tiers — revert to legacy alloy (pre-substitution) | T-0009 | H6 | housekeeping | marcus_chen | M5 | 1-3 |
| T-0338 | evidence | Supplier governance SOP draft — 60-day written notice req | T-0009 | H6 | evidence | won_lee | M5 | 4-10 |
| T-0339 | evidence | Supplier governance SOP — Drysdale RoHS-3 case retrospectively flagged | T-0009 | H2 | evidence | won_lee | M5 | 1-3 |
| T-0340 | decision | Supplier governance SOP — Marcus sign-off | T-0009 | N/A | housekeeping | marcus_chen | M5 | 1-3 |
| T-0341 | customer-report | Pylon 2026-01-10 monthly — awaiting retrofit | T-0001 | N/A | customer-report | joel_mwangi | M5 | 1-3 |
| T-0342 | customer-report | Tessera 2026-01-14 update — Cdr Park brief on root cause | T-0001 | N/A | customer-report | daniel_park | M5 | 4-10 |
| T-0343 | customer-report | SkyHawk H2+H6 disclosure call — Erika brief | T-0013 | H2 | customer-report | erika_lundgren | M5 | 4-10 |
| T-0344 | customer-report | Pylon H2+H6 disclosure call — Joel brief | T-0013 | H2 | customer-report | joel_mwangi | M5 | 1-3 |
| T-0345 | customer-report | Tessera H2+H6 written disclosure — Cdr Park | T-0013 | H2 | customer-report | daniel_park | M5 | 4-10 |
| T-0346 | customer-report | GreenFurrow 2026-01-22 ad-hoc — 2nd cold-temp report | T-0001 | N/A | customer-report | erika_lundgren | M5 | 1-3 |
| T-0347 | customer-report | GreenFurrow H2+H6 disclosure | T-0013 | H2 | customer-report | erika_lundgren | M5 | 1-3 |
| T-0348 | observation | Aravind — 9A bond redesign drawings out for review | T-0011 | N/A | observation | aravind_subramanian | M5 | 1-3 |
| T-0349 | observation | Diana — retrofit logistics planning kicked off in earnest | T-0012 | N/A | observation | diana_reyes | M5 | 1-3 |
| T-0350 | observation | Day-shift — Rosa noted new IQC inspect step at receiving | — | H6 | observation | rosa_calderon | M5 | 0 |
| T-0351 | observation | Karen — coating tank rotation per new SPC plan | — | H2 | observation | karen_holloway | M5 | 0 |
| T-0352 | observation | Jen — line 1 batch L1-26-01-12 clean | — | N/A | observation | jen_park | M5 | 0 |
| T-0353 | observation | Tomás — bay 2 cold-soak chamber thermocouple cal due | — | N/A | observation | tomas_aguilar | M5 | 0 |
| T-0354 | observation | Marcus Jr — gyro-Z final-test re-run rate trending down | — | N/A | observation | marcus_wright_jr | M5 | 0 |
| T-0355 | observation | Devon — line 2 quiet, all green | — | N/A | observation | devon_hayes | M5 | 0 |
| T-0356 | observation | Sam — accel-Y re-zero on S26-01-0214 within tol | — | N/A | observation | sam_okafor | M5 | 0 |
| T-0357 | observation | Lucia — swing-shift cure-oven cycle adjusted per H2 SPC | — | H2 | observation | lucia_martinez | M5 | 0 |
| T-0358 | observation | Marie — Drysdale tank changeover per new cadence | — | H2 | observation | marie_doucette | M5 | 0 |
| T-0359 | observation | Carl — night-shift cal protocol stable | T-0008 | H4 | observation | carl_brennan | M5 | 0 |
| T-0360 | observation | Annie — night-shift quiet | — | N/A | observation | annie_wong | M5 | 0 |
| T-0361 | observation | Tariq — accel re-zero S26-01-0317 within tol | — | N/A | observation | tariq_hassan | M5 | 0 |
| T-0362 | observation | Hank — RFO-002 stable; monthly TC cal landed clean | T-0010 | H3 | observation | hank_petrov | M5 | 0 |
| T-0363 | observation | Drysdale tank 1 batch DR26-103 in service | — | H2 | observation | marie_doucette | M5 | 0 |
| T-0364 | maintenance | SMT-1 mid-Jan preventive | — | N/A | maintenance | hank_petrov | M5 | 0 |
| T-0365 | maintenance | Cal-bay 1 jig 1 servo recalibration | — | N/A | maintenance | dale_brennan | M5 | 0 |
| T-0366 | maintenance | Bay 3 air handler quarterly PM | — | N/A | maintenance | tomas_aguilar | M5 | 0 |
| T-0367 | observation | Aravind — formal proposal for in-house XRF leadframe spot-check | T-0009 | H6 | observation | aravind_subramanian | M5 | 1-3 |
| T-0368 | decision | In-house XRF cap-ex approved | T-0009 | H6 | housekeeping | marcus_chen | M5 | 1-3 |
| T-0369 | observation | Won — IQC inspection SOP revised, new req on alloy COC | T-0009 | H6 | observation | won_lee | M5 | 1-3 |
| T-0370 | observation | Diana — field retrofit slot plan with SkyHawk | T-0012 | N/A | observation | diana_reyes | M5 | 1-3 |
| T-0371 | observation | Diana — field retrofit slot plan with Pylon | T-0012 | N/A | observation | diana_reyes | M5 | 1-3 |
| T-0372 | observation | Diana — field retrofit slot plan with Tessera | T-0012 | N/A | observation | diana_reyes | M5 | 1-3 |
| T-0373 | observation | Karen — first 9A batch with redesigned bond pattern arrived | T-0011 | N/A | observation | karen_holloway | M5 | 1-3 |
| T-0374 | observation | Priya — 9A bond-pattern re-qual test plan drafted | T-0011 | N/A | observation | priya_iyer | M5 | 1-3 |
| T-0375 | interview | Cross-functional debrief — H2+H6 confluence root-cause readout | T-0001 | H2 | interview | marcus_chen | M5 | 4-10 |
| T-0376 | observation | Aravind closing comment — supplier IQC is the missed-signal lesson | T-0009 | N/A | observation | aravind_subramanian | M5 | 1-3 |
| T-0377 | observation | Marcus internal — lessons-learned doc draft started | T-0001 | N/A | observation | marcus_chen | M5 | 1-3 |
| T-0378 | observation | Dale internal — H4 spin-off epic at 90 days, results positive | T-0008 | H4 | observation | dale_brennan | M5 | 1-3 |
| T-0379 | housekeeping | Weekly status M5-W1 — H2 opens, confluence work in flight | T-0001 | H2 | housekeeping | marcus_chen | M5 | 0 |
| T-0380 | housekeeping | Weekly status M5-W2 — confluence confirmed, customer comms staging | T-0001 | H2 | housekeeping | marcus_chen | M5 | 0 |
| T-0381 | housekeeping | Weekly status M5-W3 — customer disclosure underway | T-0001 | H2 | housekeeping | marcus_chen | M5 | 0 |
| T-0382 | housekeeping | Weekly status M5-W4 — retrofit prep in motion | T-0001 | N/A | housekeeping | marcus_chen | M5 | 0 |
| T-0383 | observation | Karen — first batch with new PIP alloy received late M5 | T-0009 | H6 | observation | karen_holloway | M5 | 1-3 |
| T-0384 | observation | XRF station vendor demo scheduled M6-W1 | T-0009 | H6 | observation | aravind_subramanian | M5 | 0 |
| T-0385 | observation | Sandia round-3 send-out scheduled — confluence validation set | T-0001 | H2 | observation | won_lee | M5 | 1-3 |

### M6 cluster (T-0386-T-0417) — February 2026, remediation in motion

| ID | type | Title shorthand | parent | hyp | cat | assignee | mo | cmts |
|---|---|---|---|---|---|---|---|---|
| T-0386 | customer-report | SkyHawk 2026-02 monthly — early signal of post-retrofit drop | T-0001 | N/A | customer-report | erika_lundgren | M6 | 1-3 |
| T-0387 | observation | First 9B/9C builds with legacy-alloy PIP shipments | T-0009 | H6 | observation | won_lee | M6 | 1-3 |
| T-0388 | observation | First 9A builds with redesigned bond pattern | T-0011 | N/A | observation | priya_iyer | M6 | 1-3 |
| T-0389 | evidence | 9A redesigned-bond unit characterization plan (in progress) | T-0011 | N/A | evidence | priya_iyer | M6 | 1-3 |
| T-0390 | evidence | 9A redesigned-bond — vibration characterization PROPOSED, NOT RUN | T-0011 | N/A | evidence | priya_iyer | M6 | 1-3 |
| T-0391 | evidence | Multi-cycle humidity-load fatigue testing PROPOSED, NOT RUN | T-0001 | H2 | evidence | priya_iyer | M6 | 1-3 |
| T-0392 | evidence | Halcyon archive retroactive review PROPOSED, NOT DONE | T-0007 | H6 | evidence | won_lee | M6 | 1-3 |
| T-0393 | evidence | Line 1 units run on line 2 cross-line genealogy gap | T-0004 | H3 | evidence | priya_iyer | M6 | 1-3 |
| T-0394 | observation | Drysdale qualification — month 1 of 3, on track | T-0011 | H2 | observation | sandy_drysdale | M6 | 1-3 |
| T-0395 | supplier-event | Drysdale formulation interim batch DR-MOD-001 received | T-0011 | H2 | supplier-event | sandy_drysdale | M6 | 1-3 |
| T-0396 | observation | Diana — retrofit batch 1 in motion (SkyHawk, ~3,200 units) | T-0012 | N/A | observation | diana_reyes | M6 | 1-3 |
| T-0397 | observation | Diana — retrofit batch 2 scheduled (Pylon, ~2,800 units) | T-0012 | N/A | observation | diana_reyes | M6 | 1-3 |
| T-0398 | observation | Diana — Tessera retrofit batch scheduled (~1,500 units) | T-0012 | N/A | observation | diana_reyes | M6 | 1-3 |
| T-0399 | observation | Aravind — XRF station installed in IQC bay | T-0009 | H6 | observation | aravind_subramanian | M6 | 1-3 |
| T-0400 | supplier-event | PIP shipment 2026-W6 — first all-legacy-alloy shipment received | T-0009 | H6 | supplier-event | won_lee | M6 | 4-10 |
| T-0401 | evidence | XRF station — first verification of PIP COC alloy match | T-0009 | H6 | evidence | won_lee | M6 | 1-3 |
| T-0402 | observation | Day-shift — Rosa noted retrofit slot training session | — | N/A | observation | rosa_calderon | M6 | 0 |
| T-0403 | observation | Karen — 9A redesigned-bond unit first builds | — | N/A | observation | karen_holloway | M6 | 0 |
| T-0404 | observation | Marie — Drysdale interim batch DR-MOD-001 in service | — | H2 | observation | marie_doucette | M6 | 0 |
| T-0405 | observation | Hank — RFO-002 4 months stable | T-0010 | H3 | observation | hank_petrov | M6 | 0 |
| T-0406 | observation | Carl — night-shift revised cal protocol 4 months stable | T-0008 | H4 | observation | carl_brennan | M6 | 0 |
| T-0407 | observation | Annie — night-shift quiet, end-of-shift only | — | N/A | observation | annie_wong | M6 | 0 |
| T-0408 | observation | Devon — line 2 quiet | — | N/A | observation | devon_hayes | M6 | 0 |
| T-0409 | observation | Sam — accel-Y re-zero S26-02-0142 within tol | — | N/A | observation | sam_okafor | M6 | 0 |
| T-0410 | observation | Lucia — swing-shift end-of-shift only | — | N/A | observation | lucia_martinez | M6 | 0 |
| T-0411 | observation | Tariq — night-shift gyro-Z bench data clean | — | N/A | observation | tariq_hassan | M6 | 0 |
| T-0412 | housekeeping | Lessons-learned doc — H6 supplier governance section | T-0009 | H6 | housekeeping | marcus_chen | M6 | 1-3 |
| T-0413 | housekeeping | Lessons-learned doc — H2 IQC missed signal section | T-0011 | H2 | housekeeping | marcus_chen | M6 | 1-3 |
| T-0414 | housekeeping | Lessons-learned doc — H3 reflow oven preventive section | T-0010 | H3 | housekeeping | marcus_chen | M6 | 1-3 |
| T-0415 | housekeeping | Lessons-learned doc — H4 cal protocol section | T-0008 | H4 | housekeeping | marcus_chen | M6 | 1-3 |
| T-0416 | housekeeping | Weekly status M6-W1 — retrofit kicked off | T-0001 | N/A | housekeeping | marcus_chen | M6 | 0 |
| T-0417 | housekeeping | Weekly status M6-W2 — open gap tickets staying open (Q4 fodder) | T-0001 | N/A | housekeeping | marcus_chen | M6 | 0 |

---

## Cross-reference inventory

### Hypothesis-to-hypothesis relationships (the relational backbone)

| Source | Relationship | Target | Note |
|---|---|---|---|
| T-0003 (H2) | supports | T-0007 (H6) | H2 amplifies H6 — confluence |
| T-0007 (H6) | supports | T-0003 (H2) | reciprocal |
| T-0007 (H6) | supports | T-0001 (master) | H6 partly explains the defect |
| T-0003 (H2) | supports | T-0001 (master) | H2 partly explains the defect |
| T-0004 (H3) | supports | T-0001 (master) | H3 partial contributor |
| T-0005 (H4) | refutes | T-0005's-own-conclusion | H4 ruled out |
| T-0006 (H5) | refutes | T-0006's-own-conclusion | H5 ruled out |
| T-0002 (H1) | refutes | T-0007 (H6)? | partial only — see below |

(Use `relationships` with `kind: supports | refutes` in manifest)

### Block relationships (bw-native dep)

Open gap tickets (status: open, blocking master closure):
- T-0390 (9A vibration char) → blocks T-0001
- T-0391 (humidity-load fatigue) → blocks T-0001
- T-0392 (Halcyon archive retro) → blocks T-0001
- T-0393 (line 1 / line 2 cross-genealogy) → blocks T-0004

Open retrofit dependencies:
- T-0396, T-0397, T-0398 (retrofit batches) → block T-0012
- T-0394 (Drysdale qual month 1) → blocks T-0011
- T-0401 (XRF first verification) → blocks T-0009 closure

### Comment-thread density

| Thread | Approx. comments | Anchors the demo via |
|---|---|---|
| T-0046 SkyHawk Sep monthly | 6 | Q2 narrative seed |
| T-0050 Yamashiro lot trace | 8 | H1 partial-confirm thread |
| T-0123 Carl Brennan interview | 7 | Q3 reconstruction |
| T-0249 Sandia FA result | 9 | H6 surfacing |
| T-0253 PIP escalation 1 | 6 | Q1 direct retrieval |
| T-0255 PIP escalation 2 | 7 | Q1 thread |
| T-0257 PIP escalation 3 | 6 | Q1 leadership-level escalation |
| T-0258 PIP DISCLOSURE | 8 | Q1 + Q2 surfacing |
| T-0269 Cdr Park 12-14 escalation | 9 | customer-pressure context |
| T-0325 H2+H6 confluence decision | 7 | Q2 root-cause statement |
| T-0345 Tessera H2+H6 disclosure | 8 | customer-comms backbone |
| T-0400 PIP first-legacy-alloy shipment | 5 | Q1 most-recent leadframe cert |

---

## Audit summary

- Total tickets: 417 (T-0001 through T-0417)
- All `parent_local` references resolve within the table
- All `blocks_local` references resolve (forward refs OK)
- All 6 hypotheses present and tagged
- All 8 suppliers represented (yamashiro, cascade, taipei_silicon, pip, frontline, mie, drysdale, becher)
- All 5 customers represented (skyhawk, pylon, greenfurrow, tessera, halcyon-archive)
- All 13 named operators appear as authors
- All 6 hypothesis epics have ≥10 child tickets
- H4 cluster temporally ordered for Q3 walkthrough
- H2+H6 confluence has explicit decision ticket (T-0325)
- 4 explicit "predicted-but-not-validated" gap tickets for Q4 (T-0390, T-0391, T-0392, T-0393)
- PIP supplier ticket with most-recent comment thread is T-0400 (for Q1)
- Noise tickets (routine maintenance, training, unrelated) scattered to give Q2 vector search false-positives to look past

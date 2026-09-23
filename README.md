<div align="center">

<img src="assets/brand/standardsforge-mark.png" alt="StandardsForge SF monogram in navy and orange" width="144" height="144">

# StandardsForge

**The already-compressed MIL-STD library for fast, offline, source-linked engineering evidence.**

Download one prepared archive, run one setup command, and search **438 compiled MIL-STD packs** locally. No Git clone, PDF acquisition, corpus compilation, network query, or model call is required to use the included snapshot.

[![Prepared release: 0.1.0a5](https://img.shields.io/badge/prepared_release-0.1.0a5-253247?style=flat-square)](https://github.com/DDNA-Engineering/standards-memory/releases/tag/v0.1.0a5)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat-square)](pyproject.toml)
[![Queries: offline](https://img.shields.io/badge/queries-offline-253247?style=flat-square)](docs/wiki/ARCHITECTURE_AND_TRUST.md)
[![Library: 438 packs](https://img.shields.io/badge/library-438_packs-EA6A23?style=flat-square)](#complete-prepared-library-snapshot)

[Download the prepared library](https://github.com/DDNA-Engineering/standards-memory/releases/download/v0.1.0a5/standardsforge-ready-0.1.0a5.zip) · [SHA-256](https://github.com/DDNA-Engineering/standards-memory/releases/download/v0.1.0a5/standardsforge-ready-0.1.0a5.zip.sha256) · [Wiki](docs/wiki/README.md) · [Contributing](CONTRIBUTING.md)

</div>

---

## Start the offline library

The prepared core supports 64-bit Windows and Linux plus Intel and Apple silicon macOS. You need CPython 3.11 or newer with SQLite FTS5 support, the platform shell shown below, and space for the approximately 1 GB archive plus its extracted local state. The fully offline MCP profile has the narrower requirement of 64-bit Windows and CPython 3.12.

### 1. Download and extract

Download [`standardsforge-ready-0.1.0a5.zip`](https://github.com/DDNA-Engineering/standards-memory/releases/download/v0.1.0a5/standardsforge-ready-0.1.0a5.zip), extract it to a durable local directory, and open PowerShell or a POSIX shell in that extracted directory.

The [published checksum](https://github.com/DDNA-Engineering/standards-memory/releases/download/v0.1.0a5/standardsforge-ready-0.1.0a5.zip.sha256) is available when you want to verify the downloaded archive before extraction.

### 2. Set up the included corpus

```powershell
python .\setup.py
```

```sh
sh ./setup.sh
```

`setup.py` is the portable implementation; `setup.sh` invokes it with `python3`. Setup validates the bundle, creates its isolated Python environment, installs the bundled wheel with package indexes disabled, validates and installs the already-compiled packs, builds the local index, proves full-integrity doctor and a real search, and records a receipt. It does not download standards or compile PDFs.

### 3. Prove the installation is ready

```powershell
python .\run.py doctor `
  --policy policies\prepared-local.json `
  --principal local-user `
  --full-integrity
```

```sh
sh ./standardsforge.sh doctor \
  --policy policies/prepared-local.json \
  --principal local-user \
  --full-integrity
```

A ready report exits `0`. The check opens the installed state read-only, validates every included package, reconciles the selected local policy, and proves one exact source-verifying query through the real evidence path.

### 4. Inventory and search the installed library

```powershell
python .\run.py list-documents `
  --identifier-prefix 'MIL-STD-810' `
  --principal local-user `
  --limit 20
```

This authorization-filtered inventory returns exact identifiers, editions, representations, immutable package digests, record counts, and declared coverage. Use it before resolution when an exact installed identifier or suffix is unknown.

```powershell
python .\run.py search "environmental testing" `
  --principal local-user `
  --query-mode natural_language `
  --limit 5
```

The result is source-linked JSON with the exact package identity, citations, coverage, and interpretation limits.

For a result, use its `evidence_selector` to request the exact record; do not treat a search snippet as a complete answer. A retrieved packet reports the immutable package, physical-page citation and quote verification separately from review and coverage. This excerpt shows selected fields from the published `0.1.0a5` `get-clause` example later in this quickstart (not the full packet or its source text):

```json
{
  "operation": "get_clause",
  "package": { "identifier": "MIL-STD-810H(1)" },
  "evidence": [{
    "record_id": "outline-3302b193c76b284a16ce31d5",
    "citation": { "page": 22, "verified": true }
  }],
  "coverage": { "complete_for_requested_scope": false },
  "provenance": { "derivations": [{ "review_status": "automated_unreviewed" }] }
}
```

### Pin an exact edition and representation

```powershell
$resolved = python .\run.py resolve 'MIL-STD-810H(1)' `
  --representation derived_structure `
  --principal local-user | ConvertFrom-Json

$pin = $resolved.result.package_digest

python .\run.py search "low pressure" `
  --package-digest $pin `
  --principal local-user `
  --limit 5
```

The package digest pins the exact installed representation. It does not decide whether that standard applies to a product or select an approved project baseline.

### What this prepared snapshot can answer today

The included packs support authorized document inventory, lexical discovery, exact source-linked page retrieval, and an automated **unreviewed** MIL-STD-810H outline. For example, this exact `0.1.0a5` outline record retrieves a source-verified passage from physical PDF page 22:

```powershell
python .\run.py get-clause `
  15546007f5f19963f3fc83cdd3da89484036348c49ff1bdf0c27f7bb42ca8f76 `
  'derived:5777493-35978-29528947ea16:document:4.2.2.5' `
  --record-id outline-3302b193c76b284a16ce31d5 `
  --principal local-user `
  --response-profile concise_evidence_v1
```

```sh
sh ./standardsforge.sh get-clause \
  15546007f5f19963f3fc83cdd3da89484036348c49ff1bdf0c27f7bb42ca8f76 \
  'derived:5777493-35978-29528947ea16:document:4.2.2.5' \
  --record-id outline-3302b193c76b284a16ce31d5 \
  --principal local-user \
  --response-profile concise_evidence_v1
```

On this frozen snapshot, the returned source digests and exact quote checks pass, but `review_status` is `automated_unreviewed`, `required_relationships` is empty, and `complete_for_requested_scope` is false. The 438 page-text packs and this outline have no document-wide reviewed obligation classifications or governing-dependency graph. `enumerate-obligations` therefore reports zero **classified** obligations with incomplete source interpretation; that is not evidence that the standards contain no requirements. `diff-editions` needs two separately installed, authorized editions and has no edition pair in this current-edition snapshot.

On Linux or macOS, replace `python .\run.py` in the query examples with `sh ./standardsforge.sh`. Both launchers validate the manifest-bound receipt and owned runtime, anchor state to the extracted directory, and forward only the CLI arguments. Rerun setup when you want a full closed-bundle revalidation.

For setup details and troubleshooting boundaries, use the [prepared-library guide](docs/wiki/PREPARED_LIBRARY.md).

### Published release versus current source

The downloadable `v0.1.0a5` archive is a frozen release with an `outline-v1` MIL-STD-810H pack containing 7,788 automated records. Subsequent source commits improve outline structure and reviewer workflows, but they are **not** in that archive or the published PyPI wheel. Use the exact release artifact for these quickstart commands; building from a newer checkout requires a separately versioned, qualified release. The [maintainer guide](docs/wiki/MAINTAINER_WORKFLOWS.md) and [validation record](VALIDATION_REPORT.md) distinguish those paths.

## Choose an MCP channel

The GitHub prepared archive and PyPI are deliberately separate. The GitHub artifact carries the rights-qualified corpus and supports offline core setup. PyPI carries independently built StandardsForge code and optional dependencies only; it does not bundle, fetch, or authorize standards content.

For a fully offline MCP installation on 64-bit Windows with CPython 3.12, run:

```powershell
.\setup.ps1
```

That Windows-only path installs the archive's exact hash-locked MCP dependency closure from its wheelhouse and proves a real stdio round trip. Point the model host at the absolute path to `standardsforge-mcp.ps1`.

On Linux or macOS, first complete the offline core setup above. Then create an environment outside the closed prepared directory and install the exact MCP code package from PyPI:

```sh
MCP_VENV=/absolute/path/to/standardsforge-mcp-venv
PREPARED_ROOT=/absolute/path/to/standardsforge-ready-0.1.0a5
python3 -m venv "$MCP_VENV"
"$MCP_VENV/bin/python" -m pip install "standardsforge[mcp]==0.1.0a5"
"$MCP_VENV/bin/python" -I -m standardsforge.mcp_server \
  --db "$PREPARED_ROOT/.standardsforge/memory.db" \
  --store "$PREPARED_ROOT/.standardsforge/objects" \
  --principal local-user \
  --result-mode structured_only
```

The pip step is an explicit networked code/dependency install. The server then uses distribution-local corpus state and does not acquire standards. See [model integration](docs/wiki/MODEL_INTEGRATION.md) for model-host configuration and trust boundaries.

## What is included

The prepared snapshot contains:

- **438** compressed MIL-STD page-text packs compiled from **912** verified source PDFs;
- **35,218** source-linked page records across **35,235** physical pages;
- an automated, explicitly unreviewed MIL-STD-810H derived outline;
- the dependency-free StandardsForge core wheel, portable offline core setup and root-anchored CLI launchers, a Windows x64 CPython 3.12 hash-inventoried offline MCP wheelhouse and launcher, exact local policies, inventory, and provenance;
- one-command local indexing for offline queries.

The acquisition snapshot completed **September 21, 2026** against the official DLA ASSIST dataset marked updated September 18, 2026. It includes the selected current publicly exposed components at that cutoff. It does not include historical editions, restricted bytes, other DLA document classes, or document-wide reviewed semantic interpretation.

## Complete prepared library snapshot

The table below is the entire **438-pack prepared MIL-STD library snapshot as of September 21, 2026 (9/21/2026)**. The acquisition completed on September 21, 2026 against the official DLA ASSIST dataset marked updated September 18, 2026. Each row is a fixed snapshot of the listed current-edition composition at that cutoff; it is not a claim that DLA has not changed the record since then or that the standard applies to a particular product.

Of these packs, **413** contain the complete selected current public composition. The other **25** contain every publicly exposed current component but are explicitly partial because **26** current components are restricted and are not included. An additional **26 restricted-only active records** have no readable pack and therefore are not part of this prepared library. Titles and document dates below come from the recorded DLA manifest; “public” describes the acquisition boundary, not blanket republication rights. Readable labels expand DLA suffixes such as `(2)` and `NOT 3` to **Change 2** and **Notice 3** while preserving the exact DLA identifier beside them.

<details>
<summary><strong>Show all 438 prepared standards</strong></summary>

| Readable snapshot | Exact DLA identifier | Official DLA title | DLA document date | Snapshot coverage |
|---|---|---|---:|---|
| MIL-STD-22D — Change 2 · Notice 3 | `MIL-STD-22D(2) NOT 3` | WELDED JOINT DESIGN | 1991-03-21 | 4 of 4 current components public |
| MIL-STD-25C | `MIL-STD-25C` | Ship Structural Symbols for Use on Ship Drawings | 2026-01-06 | 1 of 1 current components public |
| MIL-STD-101C — Notice 1 | `MIL-STD-101C NOT 1` | Color Code for Pipelines and for Compressed Gas Cylinders | 2025-04-21 | 2 of 2 current components public |
| MIL-STD-104C — Notice 1 | `MIL-STD-104C NOT 1` | Limit for Electrical Insulation Color | 2019-07-31 | 2 of 2 current components public |
| MIL-STD-108F | `MIL-STD-108F` | Definitions of and Basic Requirements for Enclosures for Electric and Electronic Equipment | 2025-07-14 | 1 of 1 current components public |
| MIL-STD-129R — Change 3 | `MIL-STD-129R(3)` | Military Marking for Shipment and Storage | 2023-02-25 | 1 of 1 current components public |
| MIL-STD-130N — Change 1 · Notice 1 | `MIL-STD-130N(1) NOT 1` | Identification Marking of U.S. Military Property | 2019-08-26 | 2 of 2 current components public |
| MIL-STD-147E — Change 3 | `MIL-STD-147E(3)` | Palletized Unit Loads | 2024-09-05 | 1 of 1 current components public |
| MIL-STD-161J | `MIL-STD-161J` | Identification Methods for Bulk Petroleum Products Systems Including Hydrocarbon Missile Fuels | 2025-07-23 | 1 of 1 current components public |
| MIL-STD-162E — Notice 3 | `MIL-STD-162E NOT 3` | Materials Handling Equipment: (Preparation for Shipment, Storage, Cyclic Maintenance, Routine Testing and Processing) | 1999-02-12 | 3 of 3 current components public |
| MIL-STD-167-1A — Notice 1 | `MIL-STD-167-1A NOT 1` | Mechanical Vibrations of Shipboard Equipment (Type I - Environmental and Type II - Internally Excited) | 2022-05-20 | 2 of 2 current components public |
| MIL-STD-167-2A — Notice 1 | `MIL-STD-167-2A NOT 1` | MECHANICAL VIBRATIONS OF SHIPBOARD EQUIPMENT (RECIPROCATING MACHINERY AND PROPULSION SYSTEM AND SHAFTING) TYPES III, IV, AND V (CONTROLLED DISTRIBUTION) | 2023-02-09 | Partial: 1 of 2 current components public; 1 restricted |
| MIL-STD-168B — Notice 1 | `MIL-STD-168B NOT 1` | Visual Inspection Guide for all-Rubber Gloves Except Surgical | 1989-02-15 | 2 of 2 current components public |
| MIL-STD-171F | `MIL-STD-171F` | Finishing of Metal and Wood Surfaces | 2011-05-31 | 1 of 1 current components public |
| MIL-STD-177A — Notice 3 | `MIL-STD-177A NOT 3` | Rubber Products, Terms for Visible Defects of | 2023-11-29 | 4 of 4 current components public |
| MIL-STD-186F — Notice 3 | `MIL-STD-186F NOT 3` | Manufacturing Process Protective Finishing for Army Missile Weapon Systems | 2022-07-12 | 4 of 4 current components public |
| MIL-STD-188-110D — Change 1 | `MIL-STD-188-110D(1)` | Interoperability and Performance Standards for Data Modems | 2024-11-06 | 1 of 1 current components public |
| MIL-STD-188-114A — Change 1 · Notice 1 | `MIL-STD-188-114A(1) NOT 1` | Electrical Characteristics of Digital Interface Circuits | 2024-09-25 | 3 of 3 current components public |
| MIL-STD-188-115 — Change 1 · Notice 2 | `MIL-STD-188-115(1) NOT 2` | Interoperability and Performance Standards for Communications Timing and Synchronization Subsystems | 2013-04-04 | 3 of 3 current components public |
| MIL-STD-188-124B — Change 3 · Notice 4 | `MIL-STD-188-124B(3) NOT 4` | Grounding, Bonding and Shielding for Common Long Haul/Tactical Communication Systems Including Ground Based Communications- Electronics Facilities and Equipments | 2013-04-04 | 5 of 5 current components public |
| MIL-STD-188-140A — Notice 1 | `MIL-STD-188-140A NOT 1` | Equipment Technical Design Standards for Common Long Haul/Tactical Radio Communications in the Low Frequency Band and Lower Frequency Bands | 2013-04-04 | 2 of 2 current components public |
| MIL-STD-188-145 — Change 1 · Notice 5 | `MIL-STD-188-145(1) NOT 5` | Interoperability and Performance Standards for Digital Los Microwave Radio Equipment | 2024-02-16 | 6 of 6 current components public |
| MIL-STD-188-154A — Change 1 | `MIL-STD-188-154A(1)` | Subsystem, Equipment, and Interface Standards for Common Long Haul and Tactical Telecommunications Control Facilities | 2014-02-20 | 1 of 1 current components public |
| MIL-STD-188-200 — Notice 1 | `MIL-STD-188-200 NOT 1` | System Design and Engineering Standard for Tactical Communications | 2026-06-05 | 2 of 2 current components public |
| MIL-STD-188-242 — Notice 1 | `MIL-STD-188-242 NOT 1` | Interoperability and Performance Standards for Tactical Single Channel Very High Frequency (VHF) Radio Equipment | 2024-07-30 | 2 of 2 current components public |
| MIL-STD-190C — Notice 6 | `MIL-STD-190C NOT 6` | Identification Marking of Rubber Products | 2024-07-24 | 7 of 7 current components public |
| MIL-STD-196G — Notice 1 | `MIL-STD-196G NOT 1` | Joint Electronics Type Designation Automated System | 2026-02-23 | 2 of 2 current components public |
| MIL-STD-202H — Notice 1 | `MIL-STD-202H NOT 1` | Electronic and Electrical Component Parts | 2020-01-21 | 2 of 2 current components public |
| MIL-STD-203G — Notice 1 | `MIL-STD-203G NOT 1` | Aircrew Station Controls and Displays: Location, Arrangement and Actuation of, for Fixed Wing Aircraft | 2019-09-11 | 2 of 2 current components public |
| MIL-STD-206B — Change 2 · Notice 2 | `MIL-STD-206B(2) NOT 2` | Friction Torque Testing for Bearings, Ball, Annular (Instrument Type) | 2019-08-23 | 4 of 4 current components public |
| MIL-STD-209K | `MIL-STD-209K` | LIFTING AND TIEDOWN PROVISIONS | 2005-02-22 | 1 of 1 current components public |
| MIL-STD-220C — Notice 3 | `MIL-STD-220C NOT 3` | Method of Insertion Loss Measurement | 2024-08-21 | 4 of 4 current components public |
| MIL-STD-252B — Notice 3 | `MIL-STD-252B NOT 3` | Classification of Visual and Mechanical Defects for Equipment, Electronic, Wired, and Other Devices | 2019-08-08 | 4 of 4 current components public |
| MIL-STD-276A — Notice 1 | `MIL-STD-276A NOT 1` | Impregnation of Porous Metal Castings and Powdered Metal Components | 2020-12-24 | 2 of 2 current components public |
| MIL-STD-282B — Notice 2 | `MIL-STD-282B NOT 2` | Filter Units, Protective Clothing, Gas-Mask Components and Related Products: Performance Test Methods | 2025-05-13 | Partial: 2 of 3 current components public; 1 restricted |
| MIL-STD-286C — Change 2 | `MIL-STD-286C(2)` | Propellants, Solid: Sampling, Examination and Testing | 2010-10-13 | 1 of 1 current components public |
| MIL-STD-290H — Change 1 · Notice 1 | `MIL-STD-290H(1) NOT 1` | Packaging and Marking of Petroleum and Related Products | 2021-05-05 | 2 of 2 current components public |
| MIL-STD-291C — Notice 3 | `MIL-STD-291C NOT 3` | Standard Tactical Air Navigation (TACAN) Signal | 2024-03-13 | 4 of 4 current components public |
| MIL-STD-322B — Notice 4 | `MIL-STD-322B NOT 4` | Explosive Components, Electrically Initiated, Basic Evaluation Tests for | 2023-03-06 | 5 of 5 current components public |
| MIL-STD-331D | `MIL-STD-331D` | Fuzes, Ignition Safety Devices and Other Related Components, Environmental and Performance Tests for | 2017-05-31 | 1 of 1 current components public |
| MIL-STD-342A — Notice 1 | `MIL-STD-342A NOT 1` | Procedure for Lubricating Oil Flow Check | 2019-12-03 | 2 of 2 current components public |
| MIL-STD-348B — Change 4 · Notice 1 | `MIL-STD-348B(4) NOT 1` | Radio Frequency Connector Interfaces for MIL-DTL-3643, MIL-DTL-3650, MIL-DTL-3655, MIL-DTL-25516, MIL-PRF-31031, MIL-PRF-39012, MIL-PRF-49142, MIL-PRF-55339, MIL-DTL-83517 | 2024-08-12 | 1 of 1 current components public |
| MIL-STD-398A — Notice 2 | `MIL-STD-398A NOT 2` | Shields, Operational for Ammunition Operations, Criteria for Design of and Tests for Acceptance | 2023-11-14 | 3 of 3 current components public |
| MIL-STD-411F — Notice 1 | `MIL-STD-411F NOT 1` | Aircrew Station Alerting Systems | 2019-08-23 | 2 of 2 current components public |
| MIL-STD-419F — Notice 1 | `MIL-STD-419F NOT 1` | Cleaning, Protecting, and Testing Piping, Tubing, and Fittings for Hydraulic Power Transmission Equipment | 2026-03-18 | 2 of 2 current components public |
| MIL-STD-449D — Change 1 · Notice 2 | `MIL-STD-449D(1) NOT 2` | Radio Frequency Spectrum Characteristics Measurement of | 2013-04-04 | 3 of 3 current components public |
| MIL-STD-461H | `MIL-STD-461H` | Requirements for the Control of Electromagnetic Interference Characteristics of Subsystems and Equipment | 2026-04-17 | 1 of 1 current components public |
| MIL-STD-464D — Notice 1 | `MIL-STD-464D NOT 1` | Electromagnetic Environmental Effects Requirements for Systems | 2026-02-09 | 2 of 2 current components public |
| MIL-STD-633G — Notice 1 | `MIL-STD-633G NOT 1` | Standard Family of Mobile Electric Power Generating Sources General Description Information and Characteristic Data | 2024-07-16 | 2 of 2 current components public |
| MIL-STD-642L | `MIL-STD-642L` | IDENTIFICATION MARKING OF COMBAT AND TACTICAL TRANSPORT VEHICLES | 1991-05-15 | 1 of 1 current components public |
| MIL-STD-644B — Change 2 · Notice 1 | `MIL-STD-644B(2) NOT 1` | Visual Inspection Standards and Inspection Procedures for Inspection of Packaging, Packing and Marking of Small Arms Ammunition | 2023-07-03 | 2 of 2 current components public |
| MIL-STD-648F | `MIL-STD-648F` | Specialized Shipping Containers | 2023-05-26 | 1 of 1 current components public |
| MIL-STD-652D — Change 6 · Notice 10 | `MIL-STD-652D(6) NOT 10` | Propellants, Solid, for Cannons Requirements and Packing | 2023-07-07 | 11 of 11 current components public |
| MIL-STD-655E — Notice 1 | `MIL-STD-655E NOT 1` | Provisions for Evaluating Quality of Cloth, Wool, Worsted and Wool Blends | 2026-04-29 | 2 of 2 current components public |
| MIL-STD-656D — Notice 1 | `MIL-STD-656D NOT 1` | Provisions for Evaluating Quality of Slacks, Women's | 2026-05-26 | 2 of 2 current components public |
| MIL-STD-657B | `MIL-STD-657B` | Provisions for Evaluating Quality of Service Caps | 2025-08-28 | 1 of 1 current components public |
| MIL-STD-662G | `MIL-STD-662G` | V50 Ballistic Test for Armor | 2025-07-23 | 1 of 1 current components public |
| MIL-STD-681F — Change 1 · Notice 2 | `MIL-STD-681F(1) NOT 2` | Identification Coding and Application of Hookup and Lead Wire | 2026-06-04 | 3 of 3 current components public |
| MIL-STD-686C — Notice 2 | `MIL-STD-686C NOT 2` | CABLE AND CORD, ELECTRICAL; IDENTIFICATION MARKING AND COLOR CODING OF | 2018-03-22 | 3 of 3 current components public |
| MIL-STD-690D — Change 4 · Notice 4 | `MIL-STD-690D(4) NOT 4` | Failure Rate (FR) Sampling Plans and Procedures | 2024-06-13 | 1 of 1 current components public |
| MIL-STD-704F — Change 1 · Notice 4 | `MIL-STD-704F(1) NOT 4` | Aircraft Electric Power Characteristics | 2026-06-24 | 3 of 3 current components public |
| MIL-STD-705D — Notice 1 | `MIL-STD-705D NOT 1` | Mobile Electric Power Systems | 2024-11-18 | 2 of 2 current components public |
| MIL-STD-709D — Change 1 · Notice 1 | `MIL-STD-709D(1) NOT 1` | Ammunition Color Coding | 2016-03-30 | 2 of 2 current components public |
| MIL-STD-710D — Notice 1 | `MIL-STD-710D NOT 1` | Synchros, 60 and 400 HZ, Selection and Application of | 2019-08-23 | 2 of 2 current components public |
| MIL-STD-740-2 | `MIL-STD-740-2` | Structureborne Vibratory Acceleration Measurements Acceptance Criteria of Shipboard Equipment | 1986-12-30 | 1 of 1 current components public |
| MIL-STD-750F — Change 3 | `MIL-STD-750F(3)` | Test Methods for Semiconductor Devices | 2021-04-01 | 1 of 1 current components public |
| MIL-STD-751B | `MIL-STD-751B` | Radar Outputs, Naval Ship and Shore | 1998-04-10 | 1 of 1 current components public |
| MIL-STD-758C | `MIL-STD-758C` | Packaging Procedures for Submarine Support Items | 1990-04-13 | 1 of 1 current components public |
| MIL-STD-767H | `MIL-STD-767H` | Control of Hardware Cleanliness | 2023-11-30 | 1 of 1 current components public |
| MIL-STD-769K — Change 1 | `MIL-STD-769K(1)` | Insulation Requirements for U.S. Naval Vessels | 2022-12-15 | 1 of 1 current components public |
| MIL-STD-777F — Change 2 | `MIL-STD-777F(2)` | Schedule of Piping, Valves, Fittings, and Associated Piping Components for Naval Surface Ships | 2018-02-13 | 1 of 1 current components public |
| MIL-STD-790G — Change 3 | `MIL-STD-790G(3)` | Established Reliability and High Reliability Qualified Products List (QPL) Systems for Electrical, Electronic, and Fiber Optic Parts Specifications | 2024-11-15 | 1 of 1 current components public |
| MIL-STD-792F — Change 1 | `MIL-STD-792F(1)` | Manufacturing Process Standard Identification Marking Requirements for Special Purpose Components | 2023-02-23 | 2 of 2 current components public |
| MIL-STD-798A — Notice 1 | `MIL-STD-798A NOT 1` | Design Evaluation Requirements for Valves for Naval Shipboard Use | 2024-03-13 | 2 of 2 current components public |
| MIL-STD-801E — Notice 1 | `MIL-STD-801E NOT 1` | Inspection and Acceptance Standards for Flexible Fuel Cells and Fittings | 2022-05-12 | 2 of 2 current components public |
| MIL-STD-805B — Notice 1 | `MIL-STD-805B NOT 1` | Towing Fittings And Provisions For Military Aircraft, Design Requirements For | 2019-08-01 | 2 of 2 current components public |
| MIL-STD-810H — Change 1 | `MIL-STD-810H(1)` | Environmental Engineering Considerations and Laboratory Tests | 2022-05-18 | 1 of 1 current components public |
| MIL-STD-814D — Notice 1 | `MIL-STD-814D NOT 1` | Requirements for Tiedown, Suspension and Extraction Provisions on Military Materiel for Airdrop | 2002-06-11 | 2 of 2 current components public |
| MIL-STD-849D — Notice 1 | `MIL-STD-849D NOT 1` | Inspection Requirements, Definitions and Classification of Defects for Parachutes | 2024-03-11 | 2 of 2 current components public |
| MIL-STD-859C | `MIL-STD-859C` | Standard Calibration Table for Aeronautical Pressure Measuring Equipment | 2026-01-16 | 1 of 1 current components public |
| MIL-STD-867D — Notice 1 | `MIL-STD-867D NOT 1` | Temper Etch Inspection | 2024-09-26 | 2 of 2 current components public |
| MIL-STD-869E | `MIL-STD-869E` | Thermal Spray | 2022-02-10 | 1 of 1 current components public |
| MIL-STD-870D | `MIL-STD-870D` | Cadmium Plating, Low Embrittlement, Electrodepositon | 2023-01-20 | 1 of 1 current components public |
| MIL-STD-871D — Notice 1 | `MIL-STD-871D NOT 1` | Electro-Chemical Stripping of Inorganic Finishes | 2024-09-26 | 2 of 2 current components public |
| MIL-STD-881F | `MIL-STD-881F` | Work Breakdown Structures for Defense Materiel Items | 2022-05-13 | 1 of 1 current components public |
| MIL-STD-882E — Change 1 · Notice 1 | `MIL-STD-882E(1) NOT 1` | System Safety | 2023-09-27 | 1 of 1 current components public |
| MIL-STD-883L — Change 1 | `MIL-STD-883L(1)(1)` | Microcircuits | 2025-06-27 | 1 of 1 current components public |
| MIL-STD-889D — Notice 1 | `MIL-STD-889D NOT 1` | Galvanic Compatibility of Electrically Conductive Materials | 2026-04-29 | 2 of 2 current components public |
| MIL-STD-901D | `MIL-STD-901D` | Provisions for Evaluating Quality of Caps, Garrison, Men's | 2025-03-05 | 1 of 1 current components public |
| MIL-STD-902B | `MIL-STD-902B` | Provisions for Evaluating Quality of Caps, Garrison, Women's | 2024-11-13 | 1 of 1 current components public |
| MIL-STD-904D | `MIL-STD-904D` | Detection, Identification, and Prevention of Pest Infestation of Subsistence | 2023-02-01 | 1 of 1 current components public |
| MIL-STD-961E — Change 5 · Notice 3 | `MIL-STD-961E(5) NOT 3` | Defense and Program-Unique Specifications Format and Content | 2025-11-25 | 1 of 1 current components public |
| MIL-STD-962D — Change 3 · Notice 1 | `MIL-STD-962D(3) NOT 1` | Defense Standards Format and Content | 2025-05-06 | 1 of 1 current components public |
| MIL-STD-981C — Change 2 · Notice 2 | `MIL-STD-981C(2) NOT 2` | Design, Manufacturing and Quality Standards for Custom Electromagnetic Devices for Space Applications | 2025-02-21 | 3 of 3 current components public |
| MIL-STD-1130C — Notice 2 | `MIL-STD-1130C NOT 2` | Connections, Electrical, Solderless Wrapped | 2023-05-04 | 3 of 3 current components public |
| MIL-STD-1168C — Notice 2 | `MIL-STD-1168C NOT 2` | Ammunition Lot Numbering and Ammunition Data Card | 2023-12-11 | 3 of 3 current components public |
| MIL-STD-1170 — Notice 4 | `MIL-STD-1170 NOT 4` | Visual Standards and Comparison Methods for Evaluating Grain Configuration in 7.62 MM Cartridge Cases | 2026-05-15 | 5 of 5 current components public |
| MIL-STD-1171B — Notice 1 | `MIL-STD-1171B NOT 1` | Energetic Material Description Sheets and Propellant Loading Authorization Sheets | 2023-03-01 | 2 of 2 current components public |
| MIL-STD-1179F | `MIL-STD-1179F` | Lamps, Reflectors and Associated Signaling Equipment for Military Vehicles | 2025-08-08 | 1 of 1 current components public |
| MIL-STD-1180B — Change 1 | `MIL-STD-1180B(1)` | SAFETY STANDARDS FOR MILITARY GROUND VEHICLES | 1991-08-07 | 2 of 2 current components public |
| MIL-STD-1241A — Notice 4 | `MIL-STD-1241A NOT 4` | Optical Terms and Definitions | 2023-03-03 | 5 of 5 current components public |
| MIL-STD-1275F | `MIL-STD-1275F` | Characteristics of 28 Volt DC Input Power to Utilization Equipment in Military Vehicles | 2022-09-07 | 1 of 1 current components public |
| MIL-STD-1276K | `MIL-STD-1276K` | Leads for Electronic Component Parts | 2023-03-24 | 1 of 1 current components public |
| MIL-STD-1285D — Change 4 | `MIL-STD-1285D(4)` | Marking of Electrical and Electronic Parts | 2022-07-01 | 1 of 1 current components public |
| MIL-STD-1289D — Change 1 · Notice 1 | `MIL-STD-1289D(1) NOT 1` | AIRBORNE STORES, GROUND FIT AND COMPATIBILITY REQUIREMENTS | 2025-02-21 | 2 of 2 current components public |
| MIL-STD-1290A — Notice 3 | `MIL-STD-1290A NOT 3` | Light Fixed and Rotary-Wing Aircraft Crash Resistance | 2019-08-28 | 4 of 4 current components public |
| MIL-STD-1309E | `MIL-STD-1309E` | Definitions of Terms for Testing, Measurement, and Diagnostics | 2026-08-18 | 1 of 1 current components public |
| MIL-STD-1310H — Notice 1 | `MIL-STD-1310H NOT 1` | Shipboard Bonding, Grounding, and other Techniques for Electromagnetic Compatibility, Electromagnetic Pulse (EMP) Mitigation, and Safety | 2014-08-12 | 2 of 2 current components public |
| MIL-STD-1311D — Notice 3 | `MIL-STD-1311D NOT 3` | Test Methods for Electron Tubes | 2026-02-09 | 4 of 4 current components public |
| MIL-STD-1316F — Notice 1 | `MIL-STD-1316F NOT 1` | Fuze Design, Safety Criteria for | 2023-02-27 | 2 of 2 current components public |
| MIL-STD-1320E — Notice 1 | `MIL-STD-1320E NOT 1` | For Designing Unit Loads, Truckloads, Railcar Loads, and Intermodal Loads for Ammunition and Explosives | 2026-05-26 | 2 of 2 current components public |
| MIL-STD-1330E | `MIL-STD-1330E` | Precision Cleaning and Testing of Shipboard Oxygen, Helium, Helium-Oxygen, Nitrogen, and Hydrogen Systems | 2022-05-16 | 1 of 1 current components public |
| MIL-STD-1332B — Notice 3 | `MIL-STD-1332B NOT 3` | Definitions of Tactical, Prime, Precise, and Utility Terminologies for Classification of the DOD Mobile Electric Power Engine Generator Set Family | 2024-08-21 | 4 of 4 current components public |
| MIL-STD-1334B — Change 1 · Notice 5 | `MIL-STD-1334B(1) NOT 5` | Process for Barrier Coating of Anti-Friction Bearings | 2019-09-12 | 6 of 6 current components public |
| MIL-STD-1339D | `MIL-STD-1339D` | Fitting Out Procedures-Ships | 2024-06-11 | 1 of 1 current components public |
| MIL-STD-1353D | `MIL-STD-1353D` | Electrical Connectors, Plug-in Sockets and Associated Hardware, Selection and Use of | 2024-09-25 | 1 of 1 current components public |
| MIL-STD-1365D | `MIL-STD-1365D` | General Design Criteria for Handling Equipment Associated with Weapons and Related Items | 2020-10-20 | 1 of 1 current components public |
| MIL-STD-1366E | `MIL-STD-1366E` | Transportability Criteria | 2006-10-31 | 1 of 1 current components public |
| MIL-STD-1373 — Change 3 · Notice 8 | `MIL-STD-1373(3) NOT 8` | Screw-Thread, Modified, 60 Degrees Stub, Double | 2019-09-10 | 9 of 9 current components public |
| MIL-STD-1377 — Notice 1 | `MIL-STD-1377 NOT 1` | Effectiveness of Cable, Connector, and Weapon Enclosure Shielding and Filters in Precluding Hazards of Electromagnetic Radiation to Ordinance, Measurement of | 2021-01-19 | 2 of 2 current components public |
| MIL-STD-1391D | `MIL-STD-1391D` | Provisions for Evaluating Quality of Overcoats, Men's | 1992-06-02 | 1 of 1 current components public |
| MIL-STD-1394B | `MIL-STD-1394B` | Provisions for Evaluating Quality of Cap Crowns | 1989-11-06 | 1 of 1 current components public |
| MIL-STD-1399C — Notice 1 | `MIL-STD-1399C NOT 1` | Interface Standard for Shipboard Systems | 2026-02-18 | 2 of 2 current components public |
| MIL-STD-1399-302A — Notice 1 | `MIL-STD-1399-302A NOT 1` | Interface Standard for Shipboard Systems Section 302 Weather Environment | 2021-01-19 | 2 of 2 current components public |
| MIL-STD-1399-441A — Notice 1 | `MIL-STD-1399-441A NOT 1` | Interface Standard for Shipboard Systems Section 441 Precise Time and Time Interval (PTTI) | 2026-07-29 | 2 of 2 current components public |
| MIL-STD-1399-502A — Notice 1 | `MIL-STD-1399-502A NOT 1` | Interface Standard for Shipboard Systems Section 502 Electronic Systems Parameters | 2021-02-22 | 2 of 2 current components public |
| MIL-STD-1399-532A | `MIL-STD-1399-532A` | Cooling Water for Support of Electronic Equipment | 2021-06-15 | 1 of 1 current components public |
| MIL-STD-1399-702 — Notice 1 | `MIL-STD-1399-702 NOT 1` | Interface Standard for Shipboard Systems Section 702 Synchro Data Transmission | 2021-02-19 | 2 of 2 current components public |
| MIL-STD-1400C — Notice 1 | `MIL-STD-1400C NOT 1` | Engines, Gasoline and Diesel, Methods of Test | 2024-10-29 | 2 of 2 current components public |
| MIL-STD-1411D | `MIL-STD-1411D` | Inspection and Maintenance of Compressed Gas Cylinders | 2024-12-19 | 1 of 1 current components public |
| MIL-STD-1425A — Notice 1 | `MIL-STD-1425A NOT 1` | Safety Design Requirements for Military Lasers and Associated Support Equipment | 2010-03-29 | 2 of 2 current components public |
| MIL-STD-1464A — Change 2 · Notice 2 | `MIL-STD-1464A(2) NOT 2` | Army Nomenclature System | 2023-02-15 | 2 of 2 current components public |
| MIL-STD-1466 — Notice 3 | `MIL-STD-1466 NOT 3` | Safety Criteria and Qualification Requirements for Pyrotechnic Initiated Explosive (PIE) Ammunition | 2015-10-26 | 4 of 4 current components public |
| MIL-STD-1472H — Notice 1 | `MIL-STD-1472H NOT 1` | Human Engineering | 2026-04-10 | 2 of 2 current components public |
| MIL-STD-1474E — Notice 2 | `MIL-STD-1474E NOT 2` | Noise Limits | 2025-03-11 | 3 of 3 current components public |
| MIL-STD-1480E — Notice 1 | `MIL-STD-1480E NOT 1` | Color Codes for Webbing, Textile; Manufacturers' Identification | 2026-04-29 | 2 of 2 current components public |
| MIL-STD-1487A — Notice 1 | `MIL-STD-1487A NOT 1` | Glossary of Cloth Coating Imperfections | 2025-03-12 | 2 of 2 current components public |
| MIL-STD-1488H — Notice 1 | `MIL-STD-1488H NOT 1` | Provisions for Evaluating Quality of Trousers | 2026-04-29 | 2 of 2 current components public |
| MIL-STD-1490H | `MIL-STD-1490H` | Provisions for Evaluating Quality of Coats, Men's, Dress | 2026-08-28 | 1 of 1 current components public |
| MIL-STD-1491 — Change 1 | `MIL-STD-1491(1)` | Glossary of Knitting Imperfections | 1973-09-17 | 2 of 2 current components public |
| MIL-STD-1492D — Notice 1 | `MIL-STD-1492D NOT 1` | Provisions for Evaluating Quality of Men's Shirts | 2026-04-22 | 2 of 2 current components public |
| MIL-STD-1494B | `MIL-STD-1494B` | Provisions for Evaluating Quality of Raincoats | 1988-06-14 | 1 of 1 current components public |
| MIL-STD-1501G | `MIL-STD-1501G` | Chromium Plating, Low Embrittlement, Electrodeposition | 2022-12-22 | 1 of 1 current components public |
| MIL-STD-1504D | `MIL-STD-1504D` | Abrasive Blasting | 2022-05-16 | 1 of 1 current components public |
| MIL-STD-1518E — Change 1 | `MIL-STD-1518E(1)` | Storage, Handling, and Servicing of Aviation Fuels, Lubricating Oils, And Hydraulic Fluids at Contractor Facilities | 2019-08-12 | 1 of 1 current components public |
| MIL-STD-1522A — Change 2 · Notice 3 | `MIL-STD-1522A(2) NOT 3` | Standard General Requirements for Safe Design and Operation of Pressurized Missile and Space Systems | 1992-09-04 | 4 of 4 current components public |
| MIL-STD-1525B — Notice 4 | `MIL-STD-1525B NOT 4` | Verification Testing of Parachute Textile Materials | 2022-08-11 | 5 of 5 current components public |
| MIL-STD-1530D — Change 1 | `MIL-STD-1530D(1)` | Aircraft Structural Integrity Program (ASIP) | 2016-10-13 | 1 of 1 current components public |
| MIL-STD-1531B — Notice 2 | `MIL-STD-1531B NOT 2` | Insert Arrangements for MIL-DTL-83733 Rack to Panel Connectors, Shell Size A | 2024-02-06 | 3 of 3 current components public |
| MIL-STD-1532A — Notice 4 | `MIL-STD-1532A NOT 4` | Insert Arrangements for MIL-C-83733 Rack to Panel Connectors, Shell Size B | 2023-06-26 | 5 of 5 current components public |
| MIL-STD-1537C — Notice 3 | `MIL-STD-1537C NOT 3` | Electrical Conductivity Test for Verification of Heat Treatment of Aluminum Alloys, Eddy Current Method | 2022-12-07 | 4 of 4 current components public |
| MIL-STD-1538 — Notice 2 | `MIL-STD-1538 NOT 2` | Spare Parts and Maintenance Support of Space and Missile Systems Undergoing RDT&E | 2013-03-12 | 3 of 3 current components public |
| MIL-STD-1542B | `MIL-STD-1542B` | Electromagnetic Compatibility and Grounding Requirements for Space System Facilities | 1991-11-15 | 1 of 1 current components public |
| MIL-STD-1545 — Notice 2 | `MIL-STD-1545 NOT 2` | Optional Spare Parts, Maintenance and Inventory Support of Space and Missile Systems | 2013-03-12 | 3 of 3 current components public |
| MIL-STD-1546B — Notice 2 | `MIL-STD-1546B NOT 2` | Parts, Materials, and Processes Control Program for Space and Launch Vehicles | 2008-10-20 | 3 of 3 current components public |
| MIL-STD-1547B — Notice 2 | `MIL-STD-1547B NOT 2` | Electronic Parts, Materials, and Processes for Space and Launch Vehicles | 2008-10-20 | 3 of 3 current components public |
| MIL-STD-1548H — Change 1 · Notice 1 | `MIL-STD-1548H(1) NOT 1` | Into - Plane Servicing of Fuels at Commercial Airports | 2026-05-26 | 2 of 2 current components public |
| MIL-STD-1553C | `MIL-STD-1553C` | Digital Time Division Command/Response Multiplex Data Bus | 2018-02-28 | 1 of 1 current components public |
| MIL-STD-1554A — Change 3 · Notice 1 | `MIL-STD-1554A(3) NOT 1` | Insert Arrangements for MIL-DTL-83723 (Series III) and MIL-DTL-26500, Environment Resisting, Circular, Electrical Connectors | 2026-06-04 | 3 of 3 current components public |
| MIL-STD-1560C — Change 3 · Notice 1 | `MIL-STD-1560C(3) NOT 1` | Insert Arrangements for MIL-DTL-38999, MIL-DTL-27599 and SAE-AS29600 Series A Electrical Circular Connectors | 2026-06-04 | 2 of 2 current components public |
| MIL-STD-1568E | `MIL-STD-1568E` | Materials and Processes for Corrosion Prevention and Control in Aerospace Weapons Systems | 2023-10-11 | 1 of 1 current components public |
| MIL-STD-1580D — Change 1 | `MIL-STD-1580D(1)` | Destructive Physical Analysis for Electronic, Electromagnetic, and Electromechanical Parts | 2025-11-25 | 1 of 1 current components public |
| MIL-STD-1587F | `MIL-STD-1587F` | Material and Process Requirements for Aerospace Weapons Systems | 2024-02-21 | 1 of 1 current components public |
| MIL-STD-1605A — Notice 2 | `MIL-STD-1605A NOT 2` | Procedures for Conducting a Shipboard Electromagnetic Interference (EMI) Survey (Surface Ship) | 2023-08-22 | 3 of 3 current components public |
| MIL-STD-1608C — Change 1 · Notice 1 | `MIL-STD-1608C(1) NOT 1` | Provisions for Evaluating Quality of Coats, Women's, Dress | 1990-06-04 | 2 of 2 current components public |
| MIL-STD-1609D | `MIL-STD-1609D` | Provisions for Evaluating Quality of Women's Skirts | 2026-08-11 | 1 of 1 current components public |
| MIL-STD-1611A — Notice 1 | `MIL-STD-1611A NOT 1` | Provisions for Evaluating Quality of Hoods and Havelocks, Woman's | 1988-01-25 | 2 of 2 current components public |
| MIL-STD-1622B — Change 1 | `MIL-STD-1622B(1)` | Cleaning of Shipboard Compressed Air Systems | 2006-11-15 | 2 of 2 current components public |
| MIL-STD-1623E — Change 1 · Notice 1 | `MIL-STD-1623E(1) NOT 1` | Fire Performance Requirements and Approved Specifications for Interior Finish Materials and Furnishings (Naval Shipboard Use) | 2015-01-29 | 2 of 2 current components public |
| MIL-STD-1625E | `MIL-STD-1625E` | Safety Certification Program for Drydocking Facilities and Shipbuilding Ways for U.S. Navy Ships | 2026-03-19 | 1 of 1 current components public |
| MIL-STD-1627C — Notice 1 | `MIL-STD-1627C NOT 1` | Bending of Pipe or Tube for Ship Piping Systems | 2020-12-24 | 2 of 2 current components public |
| MIL-STD-1632B — Change 1 · Notice 1 | `MIL-STD-1632B(1) NOT 1` | Insert Arrangements for MIL-DTL-28804 High Density, Rectangular, Electrical Connectors | 2022-01-21 | 1 of 1 current components public |
| MIL-STD-1647E — Notice 1 | `MIL-STD-1647E NOT 1` | Identification Markings For Domestically Manufactured Bearings, Ball, Annular For Instruments And Precision Components | 2019-08-28 | 2 of 2 current components public |
| MIL-STD-1651B — Change 3 | `MIL-STD-1651B(3)` | Insert Arrangements for SAE-AS50151, MIL-DTL-22992 (Classes C, J, and R), MIL-DTL-83723 (Series II), and SAE-AS95234 Circular Electrical Connectors | 2024-04-10 | 1 of 1 current components public |
| MIL-STD-1657A | `MIL-STD-1657A` | SWITCHING EQUIPMENT, COMBAT SYSTEM, COMMAND & CONTROL, FIRE CONTROL & INTERIOR COMMUNICATION, REQUIREMENTS FOR | 1983-05-02 | 1 of 1 current components public |
| MIL-STD-1660B — Notice 1 | `MIL-STD-1660B NOT 1` | Ammunition and Ordnance Unit Loads | 2026-02-23 | 2 of 2 current components public |
| MIL-STD-1661 | `MIL-STD-1661` | Mark and Mod Nomenclature System | 1978-08-01 | 1 of 1 current components public |
| MIL-STD-1662D — Notice 1 | `MIL-STD-1662D NOT 1` | Ordnance Alteration (ORDALT) Instructions, Preparation of | 2024-09-19 | 2 of 2 current components public |
| MIL-STD-1666B | `MIL-STD-1666B` | Classification of Defects for Evaluating Quality of Aluminized Firemen's Clothing | 1988-10-10 | 1 of 1 current components public |
| MIL-STD-1667B | `MIL-STD-1667B` | Provisions for Evaluating Quality of Hoods: Cold Weather, Extreme Cold Weather, and Flyer's | 1995-01-18 | 1 of 1 current components public |
| MIL-STD-1668B | `MIL-STD-1668B` | Provisions for Evaluating Quality of Cloth Coveralls | 1988-02-09 | 1 of 1 current components public |
| MIL-STD-1669A — Change 3 · Notice 2 | `MIL-STD-1669A(3) NOT 2` | Insert Arrangements for MIL-DTL-26482 Environment Resisting, Circular Electrical Connectors | 2024-03-05 | 1 of 1 current components public |
| MIL-STD-1674 — Notice 2 | `MIL-STD-1674 NOT 2` | INSERT ARRANGEMENTS FOR MIL-C-85028(AS) CONNECTOR, ELECTRIC, RECTANGULAR, INDIVIDUAL CONTACT SEALING, POLARIZED CENTER JACKSCREW | 2019-08-23 | 3 of 3 current components public |
| MIL-STD-1683B — Notice 1 | `MIL-STD-1683B NOT 1` | Connectors and Jacketed Cable, Electric, Selection Standard for Shipboard Use | 2021-02-24 | 2 of 2 current components public |
| MIL-STD-1684E — Notice 1 | `MIL-STD-1684E NOT 1` | Control of Heat Treatment | 2019-12-06 | Partial: 1 of 2 current components public; 1 restricted |
| MIL-STD-1689A | `MIL-STD-1689A` | FABRICATION, WELDING, AND INSPECTION OF SHIPS STRUCTURE | 1990-11-23 | 1 of 1 current components public |
| MIL-STD-1698B — Change 1 · Notice 2 | `MIL-STD-1698B(1) NOT 2` | Insert Arrangements for MIL-DTL-28840 High Density High Shock Circular Electrical Connectors | 2023-08-30 | 2 of 2 current components public |
| MIL-STD-1699B | `MIL-STD-1699B` | Nondestructive Evaluation of Butt Welds in Crane and Railroad Rails | 1992-07-17 | 1 of 1 current components public |
| MIL-STD-1760F | `MIL-STD-1760F` | Aircraft/Store Electrical Interconnection System | 2025-09-09 | 1 of 1 current components public |
| MIL-STD-1773 — Change 1 · Notice 1 | `MIL-STD-1773(1) NOT 1` | Fiber Optics Mechanization of an Aircraft Internal Time Division Command/Response Multiplex Data Bus | 2017-05-22 | 4 of 4 current components public |
| MIL-STD-1791D — Change 1 | `MIL-STD-1791D(1)` | Designing for Internal Aerial Delivery in Fixed Wing Aircraft | 2021-06-22 | 1 of 1 current components public |
| MIL-STD-1894B | `MIL-STD-1894B` | RADIOGRAPHIC REFERENCE STANDARDS AND RADIOGRAPHIC PROCEDURES FOR PARTIAL-PENETRATION STEEL WELDS | 1998-06-26 | 1 of 1 current components public |
| MIL-STD-1895B | `MIL-STD-1895B` | RADIOGRAPHIC REFERENCE STANDARDS AND RADIOGRAPHIC PROCEDURES FOR PARTIAL-PENETRATION ALUMINUM WELDS | 1998-06-26 | 1 of 1 current components public |
| MIL-STD-2003B — Notice 1 | `MIL-STD-2003B NOT 1` | Electric Plant Installation Standard Methods for Surface Ships and Submarines | 2026-02-09 | 2 of 2 current components public |
| MIL-STD-2003-3B — Notice 1 | `MIL-STD-2003-3B NOT 1` | Electric Plant Installation Standard Methods for Surface Ships and Submarines (Penetrations) | 2026-02-09 | 2 of 2 current components public |
| MIL-STD-2071A — Notice 3 | `MIL-STD-2071A NOT 3` | Testing of Chaff Radar Cross-Section | 2019-06-07 | 4 of 4 current components public |
| MIL-STD-2073-1E — Change 4 · Notice 1 | `MIL-STD-2073-1E(4) NOT 1` | Standard Practice for Military Packaging | 2024-06-27 | 2 of 2 current components public |
| MIL-STD-2088B — Change 1 · Notice 1 | `MIL-STD-2088B(1) NOT 1` | Bomb Rack Unit (BRU), Single Store, Aircraft | 2019-09-13 | 2 of 2 current components public |
| MIL-STD-2100 — Notice 1 | `MIL-STD-2100 NOT 1` | Propellant, Solid, Characterization Of (Except Gun Propellant) | 2024-08-15 | 2 of 2 current components public |
| MIL-STD-2102A — Notice 2 | `MIL-STD-2102A NOT 2` | AIRCREW ESCAPE PROPULSION SYSTEMS; VIBRATION AND SHOCK TESTS FOR | 1991-08-14 | 3 of 3 current components public |
| MIL-STD-2106A | `MIL-STD-2106A` | Development of Shipboard Industrial Test Procedures | 2014-06-04 | 1 of 1 current components public |
| MIL-STD-2110 — Notice 1 | `MIL-STD-2110 NOT 1` | Restoration, Overhaul, and Repair of Electronic Equipment | 1986-12-18 | 2 of 2 current components public |
| MIL-STD-2119A — Notice 1 | `MIL-STD-2119A NOT 1` | Design Requirements for Printed-Wiring Electrical Backplane Assemblies | 2021-02-26 | 2 of 2 current components public |
| MIL-STD-2131A — Notice 1 | `MIL-STD-2131A NOT 1` | Launcher, Ejection, Guided Missile, Aircraft, General Design Criteria for | 2019-08-23 | 2 of 2 current components public |
| MIL-STD-2148A — Notice 1 | `MIL-STD-2148A NOT 1` | Vibration Damping Materials, Procedures for Installation, Maintenance, and Repairs | 2023-02-27 | 2 of 2 current components public |
| MIL-STD-2151A — Notice 1 | `MIL-STD-2151A NOT 1` | Inclined Ladder Tread Test Methods and Equipment for Wear, Slip Resistance, and Impact | 2023-03-21 | 2 of 2 current components public |
| MIL-STD-2156 — Change 1 · Notice 1 | `MIL-STD-2156(1) NOT 1` | Launcher, Rail, Guided Missile, Aircraft, General Design Criteria for | 2019-07-31 | 3 of 3 current components public |
| MIL-STD-2161C — Change 1 · Notice 1 | `MIL-STD-2161C(1) NOT 1` | Paint Schemes and Exterior Markings for U.S. Navy and Marine Corps Aircraft | 2023-07-05 | 1 of 1 current components public |
| MIL-STD-2184A — Notice 1 | `MIL-STD-2184A NOT 1` | Procedures for Installation, Inspection, Maintenance, and Repair of Absorber, Reflector, and Decoupler Acoustic Materials | 2021-11-09 | Partial: 1 of 2 current components public; 1 restricted |
| MIL-STD-2193C — Change 1 · Notice 1 | `MIL-STD-2193C(1) NOT 1` | Ship Hydraulic System Components | 2023-03-23 | 2 of 2 current components public |
| MIL-STD-2202A | `MIL-STD-2202A` | Energy Monitoring and Control Systems, Factory Tests | 1994-06-10 | 1 of 1 current components public |
| MIL-STD-2203A | `MIL-STD-2203A` | Energy Monitoring and Control Systems, Performance Verification and Endurance Tests | 1994-06-10 | 1 of 1 current components public |
| MIL-STD-1839D — Notice 1 | `MIL-STD-1839D NOT 1` | Calibration and Measurement Requirements | 2016-12-19 | 2 of 2 current components public |
| MIL-STD-188-141D — Change 1 | `MIL-STD-188-141D(1)` | Interoperability and Performance Standards for Medium and High Frequency Radio Systems | 2025-05-23 | 1 of 1 current components public |
| MIL-STD-2197A — Change 1 · Notice 1 | `MIL-STD-2197A(1) NOT 1` | Brush Electroplating on Marine Machinery | 2024-09-10 | 1 of 1 current components public |
| MIL-STD-188-243A | `MIL-STD-188-243A` | Tactical Single Channel Ultra High Frequency (UHF) Radio Communications | 2014-05-01 | 1 of 1 current components public |
| MIL-STD-1904C — Notice 1 | `MIL-STD-1904C NOT 1` | Test Standards for Level A and Level B Packaging for Conventional Ammunition | 2023-03-03 | 2 of 2 current components public |
| MIL-STD-2195A — Notice 1 | `MIL-STD-2195A NOT 1` | Inspection Procedure for Detection and Measurement of Dealloying Corrosion on Aluminum Bronze and Nickel-Aluminum Bronze Components | 2024-04-11 | 2 of 2 current components public |
| MIL-STD-188-203-3 — Notice 1 | `MIL-STD-188-203-3 NOT 1` | Subsystem Design and Engineering Standards for Tactical Digital Information Link (Tadil) C | 2013-04-04 | 2 of 2 current components public |
| MIL-STD-188-203-1A — Notice 1 | `MIL-STD-188-203-1A NOT 1` | Interoperability and Performance Standards for Tactical Digital Information Link (Tadil) A | 2013-04-04 | 2 of 2 current components public |
| MIL-STD-1399-72-1A — Notice 1 | `MIL-STD-1399-72-1A NOT 1` | Interface Standard for Shipboard Systems Section 072.1 Blast Environment, Missile Exhaust | 2026-02-18 | 2 of 2 current components public |
| MIL-STD-1399-72-2A — Notice 1 | `MIL-STD-1399-72-2A NOT 1` | Interface Standard for Shipboard Systems Section 072.2 Blast Environment, Gun Muzzle | 2026-02-18 | 2 of 2 current components public |
| MIL-STD-1399-593-2 — Notice 2 | `MIL-STD-1399-593-2 NOT 2` | INTERFACE STANDARD FOR SHIPBOARD SYSTEMS SECTION 593 - PART 2 SEWAGE/WASTE WATER DISPOSAL FOR SUBMARINES | 2021-02-25 | 3 of 3 current components public |
| MIL-STD-1907 — Change 4 · Notice 7 | `MIL-STD-1907(4) NOT 7` | Inspection, Liquid Penetrant and Magnetic Particle, Soundness Requirements for Materials, Parts, and Weldments | 2025-03-11 | 9 of 9 current components public |
| MIL-STD-1477C — Notice 4 | `MIL-STD-1477C NOT 4` | Symbols for Army System Displays (Metric) | 2019-08-27 | 5 of 5 current components public |
| MIL-STD-1796A — Notice 2 | `MIL-STD-1796A NOT 2` | Avionics Integrity Program (AVIP) | 2026-08-26 | 3 of 3 current components public |
| MIL-STD-1797B — Notice 1 | `MIL-STD-1797B NOT 1` | Flying Qualities of Piloted Aircraft | 2012-04-09 | Partial: 1 of 2 current components public; 1 restricted |
| MIL-STD-2198 — Notice 1 | `MIL-STD-2198 NOT 1` | Design Requirements for Metal Electrical Backplane Assemblies | 2021-02-24 | 2 of 2 current components public |
| MIL-STD-600001 — Notice 3 | `MIL-STD-600001 NOT 3` | Mapping, Charting and Geodesy Accuracy | 2025-03-11 | 4 of 4 current components public |
| MIL-STD-2003-1B — Notice 1 | `MIL-STD-2003-1B NOT 1` | Electric Plant Installation Standard Methods for Surface Ships and Submarines (Cable) | 2026-02-09 | 2 of 2 current components public |
| MIL-STD-2003-2B — Notice 1 | `MIL-STD-2003-2B NOT 1` | Electric Plant Installation Standard Methods for Surface Ships and Submarines (Equipment) | 2026-02-09 | 2 of 2 current components public |
| MIL-STD-2003-4B — Notice 1 | `MIL-STD-2003-4B NOT 1` | Electric Plant Installation Standard Methods for Surface Ships and Submarines (Cableways) | 2026-02-09 | 2 of 2 current components public |
| MIL-STD-2003-5B — Notice 1 | `MIL-STD-2003-5B NOT 1` | Electric Plant Installation Standard Methods for Surface Ships and Submarines (Connectors) | 2026-02-09 | 2 of 2 current components public |
| MIL-STD-770A — Notice 1 | `MIL-STD-770A NOT 1` | Ultrasonic Inspection of Lead for Soundness and Bonding | 2020-06-15 | Partial: 2 of 3 current components public; 1 restricted |
| MIL-STD-1691F — Notice 1 | `MIL-STD-1691F NOT 1` | Construction and Material Schedule for Military Medical and Dental Facilities | 2024-09-04 | 2 of 2 current components public |
| MIL-STD-1798D — Notice 1 | `MIL-STD-1798D NOT 1` | Mechanical Equipment and Subsystems Integrity Program | 2026-06-10 | 2 of 2 current components public |
| MIL-STD-2132F — Notice 1 | `MIL-STD-2132F NOT 1` | Nondestructive Examination Requirements for Special Applications | 2022-06-27 | Partial: 3 of 4 current components public; 1 restricted |
| MIL-STD-11991C | `MIL-STD-11991C` | General Standard for Parts, Materials, and Processes | 2026-04-27 | 1 of 1 current components public |
| MIL-STD-2142A | `MIL-STD-2142A` | MAGNETIC SILENCING CHARACTERISTICS, MEASUREMENT OF (METRIC) | 1990-08-06 | 1 of 1 current components public |
| MIL-STD-913A — Notice 1 | `MIL-STD-913A NOT 1` | REQUIREMENTS FOR THE CERTIFICATION OF SLING LOADED MILITARY EQUIPMENT FOR EXTERNAL TRANSPORTATION BY DEPARTMENT OF DEFENSE HELICOPTERS | 2002-06-11 | 2 of 2 current components public |
| MIL-STD-1808C — Change 3 | `MIL-STD-1808C(3)` | System Subsystem Sub-Subsystem Numbering | 2025-05-14 | 1 of 1 current components public |
| MIL-STD-1812A — Notice 1 | `MIL-STD-1812A NOT 1` | Aeronautical and Support Equipment Type Designation System | 2025-03-18 | 2 of 2 current components public |
| MIL-STD-2031 — Notice 1 | `MIL-STD-2031 NOT 1` | Fire And Toxicity Test Methods and Qualification Procedure for Composite Material Systems Used in Hull, Machinery, and Structural Applications Inside Naval Submarines | 2024-05-02 | 2 of 2 current components public |
| MIL-STD-2105E | `MIL-STD-2105E` | Hazard Assessment Tests for Non-Nuclear Munitions | 2022-01-06 | 1 of 1 current components public |
| MIL-STD-1809 | `MIL-STD-1809` | Space Environment for USAF Space Vehicles | 1991-02-15 | 1 of 1 current components public |
| MIL-STD-2037 — Change 1 · Notice 1 | `MIL-STD-2037(1) NOT 1` | Procedure To Obtain Certification for Electric Motor Sealed Insulation Systems | 2026-02-09 | 3 of 3 current components public |
| MIL-STD-2035A — Notice 1 | `MIL-STD-2035A NOT 1` | Nondestructive Testing Acceptance Criteria | 2026-03-09 | 2 of 2 current components public |
| MIL-STD-2177 — Notice 1 | `MIL-STD-2177 NOT 1` | Depot Rework Specification, Air-Launched Weapons, Armament, Ordnance, Missile Launchers, & Peculiar Support Equipment, Preparation of | 2019-07-31 | 2 of 2 current components public |
| MIL-STD-1835D — Notice 3 | `MIL-STD-1835D NOT 3` | Electronic Component Case Outlines | 2019-04-15 | 4 of 4 current components public |
| MIL-STD-1901A | `MIL-STD-1901A` | MUNITION ROCKET AND MISSILE MOTOR IGNITION SYSTEM DESIGN, SAFETY CRITERIA FOR | 2002-06-06 | 1 of 1 current components public |
| MIL-STD-984A | `MIL-STD-984A` | Provisions for Size Labeling for Women's Uniform Clothing | 1994-09-13 | 1 of 1 current components public |
| MIL-STD-2040 — Notice 1 | `MIL-STD-2040 NOT 1` | TUG REQUIREMENTS FOR HANDLING U.S. NAVY SHIPS | 2023-08-23 | 2 of 2 current components public |
| MIL-STD-2223 — Change 1 · Notice 1 | `MIL-STD-2223(1) NOT 1` | Test Methods for Insulated Electric Wire | 2019-08-14 | 3 of 3 current components public |
| MIL-STD-188-181C — Change 4 · Notice 2 | `MIL-STD-188-181C(4) NOT 2` | Interoperability Standard for Access to 5-kHz and 25-kHz UHF Satellite Communications Channels | 2024-10-11 | Partial: 2 of 3 current components public; 1 restricted |
| MIL-STD-188-182B — Change 4 · Notice 2 | `MIL-STD-188-182B(4) NOT 2` | Interoperability Standard for UHF Satcom Dama Orderwire Messages and Protocols | 2024-10-11 | Partial: 3 of 5 current components public; 2 restricted |
| MIL-STD-188-183B — Change 5 · Notice 1 | `MIL-STD-188-183B(5) NOT 1` | Interoperability Standard for Multiple-Access 5-kHz and 25-kHz UHF Satellite Communications Channels | 2024-10-11 | Partial: 1 of 2 current components public; 1 restricted |
| MIL-STD-2191A | `MIL-STD-2191A` | Repair Welding, Cladding, Straightening, and Cold Rolling of Main Propulsion Shafting, Rudder Stocks, and Diving Plane Stocks | 2024-08-15 | 1 of 1 current components public |
| MIL-STD-188-212 — Notice 1 | `MIL-STD-188-212 NOT 1` | Subsystem Design and Engineering Standards for Tactical Digital Information Link (TADIL) B | 2024-07-30 | 2 of 2 current components public |
| MIL-STD-1822B | `MIL-STD-1822B` | Nuclear Compatibility Certification of Nuclear Weapon Systems, Subsystems and Support Equipment | 2017-01-11 | 1 of 1 current components public |
| MIL-STD-188-220D — Change 1 · Notice 1 | `MIL-STD-188-220D(1) NOT 1` | Digital Message Transfer Device Subsystems | 2013-05-10 | 2 of 2 current components public |
| MIL-STD-2217 — Change 2 · Notice 6 | `MIL-STD-2217(2) NOT 6` | Memory Loader/Verifier Multiplex Bus Interface With Avionic Systems, Requirements for | 2022-12-05 | 7 of 7 current components public |
| MIL-STD-2041F | `MIL-STD-2041F` | Control of Detrimental Materials | 2022-12-14 | 1 of 1 current components public |
| MIL-STD-2042C | `MIL-STD-2042C` | Fiber Optic Cable Topology Installation Standard Methods for Surface Ships and Submarines | 2016-10-18 | 1 of 1 current components public |
| MIL-STD-2042-1C | `MIL-STD-2042-1C` | Fiber Optic Cable Topology Installation Standard Methods for Surface Ships and Submarines (Cables) (Part 1 of 7 Parts) | 2016-10-18 | 1 of 1 current components public |
| MIL-STD-2042-2C — Change 1 | `MIL-STD-2042-2C(1)` | Fiber Optic Cable Topology Installation Standard Methods for Surface Ships and Submarines (Equipment) (Part 2 of 7 Parts) | 2017-12-12 | 1 of 1 current components public |
| MIL-STD-2042-3C | `MIL-STD-2042-3C` | Fiber Optic Cable Topology Installation Standard Methods for Surface Ships and Submarines (Cable Penetrations) (Part 3 of 7 Parts) | 2016-10-18 | 1 of 1 current components public |
| MIL-STD-2042-4C | `MIL-STD-2042-4C` | Fiber Optic Cable Topology Installation Standard Methods for Surface Ships and Submarines (Cableways) (Part 4 of 7 Parts) | 2016-10-18 | 1 of 1 current components public |
| MIL-STD-2042-5C | `MIL-STD-2042-5C` | Fiber Optic Cable Topology Installation Standard Methods for Surface Ships and Submarines (Connectors and Interconnections) (Part 5 of 7 Parts) | 2016-10-18 | 1 of 1 current components public |
| MIL-STD-2042-6C | `MIL-STD-2042-6C` | Fiber Optic Cable Topology Installation Standard Methods for Surface Ships and Submarines(Tests) (Part 6 of 7 Parts) | 2016-10-18 | 1 of 1 current components public |
| MIL-STD-188-184A — Notice 2 | `MIL-STD-188-184A NOT 2` | Interoperability Standard for the Data Control Waveform | 2024-12-31 | Partial: 2 of 3 current components public; 1 restricted |
| MIL-STD-1911A — Notice 2 | `MIL-STD-1911A NOT 2` | Hand-Emplaced Ordnance Design, Safety Criteria for | 2014-07-24 | 3 of 3 current components public |
| MIL-STD-2401 — Notice 1 | `MIL-STD-2401 NOT 1` | Depart of Defense World Geodetic System (WGS) | 2004-03-31 | 2 of 2 current components public |
| MIL-STD-188-198A — Change 3 · Notice 6 | `MIL-STD-188-198A(3) NOT 6` | Joint Photographic Experts Group (JPEG) Image Compression for the National Imagery Transmission Format Standard | 2025-03-11 | 7 of 7 current components public |
| MIL-STD-7080 — Notice 1 | `MIL-STD-7080 NOT 1` | Selection and Installation of Aircraft Electric Equipment | 2019-08-14 | 2 of 2 current components public |
| MIL-STD-2052A — Notice 1 | `MIL-STD-2052A NOT 1` | FIBER OPTIC SYSTEMS DESIGN | 2026-04-13 | 2 of 2 current components public |
| MIL-STD-2034C — Notice 1 | `MIL-STD-2034C NOT 1` | Qualification Requirements for Material Specifications | 2019-12-06 | Partial: 1 of 2 current components public; 1 restricted |
| MIL-STD-46855A — Notice 3 | `MIL-STD-46855A NOT 3` | Human Engineering Requirements for Military Systems, Equipment, and Facilities | 2025-09-23 | 4 of 4 current components public |
| MIL-STD-2225 — Notice 1 | `MIL-STD-2225 NOT 1` | Vibration and Noise Testing for Instrument Bearings | 2019-08-28 | 2 of 2 current components public |
| MIL-STD-1766C | `MIL-STD-1766C` | Nuclear Hardness and Survivability Program Requirements for ICBM Weapon Systems | 2017-01-17 | 1 of 1 current components public |
| MIL-STD-188-199 — Change 1 · Notice 4 | `MIL-STD-188-199(1) NOT 4` | Vector Quantization Decompression for the National Imagery Transmission Format Standard | 2025-03-11 | 5 of 5 current components public |
| MIL-STD-2411-1 — Change 5 · Notice 2 | `MIL-STD-2411-1(5) NOT 2` | Registered Data Values for Raster Product Format | 2022-10-07 | 1 of 1 current components public |
| MIL-STD-2411 — Change 2 · Notice 4 | `MIL-STD-2411(2) NOT 4` | Raster Product Format | 2020-06-09 | 5 of 5 current components public |
| MIL-STD-2411-2 — Notice 3 | `MIL-STD-2411-2 NOT 3` | Integration of Raster Product Format Files into the National Imagery Transmission Format | 2025-03-11 | 4 of 4 current components public |
| MIL-STD-2525E — Change 1 | `MIL-STD-2525E(1)` | Joint Military Symbology | 2025-03-02 | 1 of 1 current components public |
| MIL-STD-1913 — Change 1 · Notice 4 | `MIL-STD-1913(1) NOT 4` | Dimensioning of Accessory Mounting Rail for Small Arms Weapons | 2023-07-03 | 6 of 6 current components public |
| MIL-STD-188-185A — Change 3 · Notice 1 | `MIL-STD-188-185A(3) NOT 1` | Interoperability Standard for UHF MILSATCOM DAMA Control System | 2024-10-11 | Partial: 1 of 2 current components public; 1 restricted |
| MIL-STD-188-165B — Change 2 | `MIL-STD-188-165B(2)` | Interoperability of Super High Frequency (SHF) Satellite Communications Phase-Shift Keying (PSK) Modems | 2025-05-09 | 1 of 1 current components public |
| MIL-STD-188-164C — Change 2 | `MIL-STD-188-164C(2)` | Interoperability of Super High Frequency (SHF) Satellite Communications Terminals | 2025-04-29 | 1 of 1 current components public |
| MIL-STD-2414A — Notice 2 | `MIL-STD-2414A NOT 2` | Bar Coding for Geospatial Products | 2020-10-09 | 3 of 3 current components public |
| MIL-STD-1399-406B — Notice 3 | `MIL-STD-1399-406B NOT 3` | Interface Standard for Shipboard Systems Section 406 Digital Computer Grounding (Metric) | 2021-02-23 | 4 of 4 current components public |
| MIL-STD-38784C | `MIL-STD-38784C` | General Style and Format Requirements for Technical Manuals | 2024-09-04 | 1 of 1 current components public |
| MIL-STD-2410 — Notice 1 | `MIL-STD-2410 NOT 1` | Mapping, Charting and Geodesy Reproduction and Printing | 2020-06-10 | 3 of 3 current components public |
| MIL-STD-1916 — Notice 2 | `MIL-STD-1916 NOT 2` | DOD Preferred Methods for Acceptance of Product | 2014-06-05 | 3 of 3 current components public |
| MIL-STD-1370F — Notice 1 | `MIL-STD-1370F NOT 1` | Materials and Process Standard for Instrumentation and Control Equipment | 2022-06-14 | Partial: 2 of 3 current components public; 1 restricted |
| MIL-STD-2407 — Change 1 · Notice 3 | `MIL-STD-2407(1) NOT 3` | Vector Product Format | 2020-06-10 | 4 of 4 current components public |
| MIL-STD-40051E — Change 1 | `MIL-STD-40051E(1)` | Preparation of Digital Technical Information for Technical Manuals (TMs) | 2025-07-30 | 1 of 1 current components public |
| MIL-STD-6013A — Notice 3 | `MIL-STD-6013A NOT 3` | Army Tactical Data Link-1 (ATDL-1) Message Standard, Department of Defense Interface Standard | 2017-05-05 | Partial: 3 of 4 current components public; 1 restricted |
| MIL-STD-7179B — Notice 1 | `MIL-STD-7179B NOT 1` | Finishes, Coatings, and Sealants, for the Protection of Aerospace Weapons Systems and Support Equipment | 2023-11-28 | 2 of 2 current components public |
| MIL-STD-963C — Notice 1 | `MIL-STD-963C NOT 1` | Data Item Descriptions (DIDs) | 2019-11-07 | 2 of 2 current components public |
| MIL-STD-8651 — Notice 2 | `MIL-STD-8651 NOT 2` | Installation of Identification and Modification Plates (For Aircraft) | 2019-11-19 | 3 of 3 current components public |
| MIL-STD-40076A — Notice 1 | `MIL-STD-40076A NOT 1` | Preservation and Packing of Rocket and Missile Systems Equipment for Shipment | 2023-04-17 | 2 of 2 current components public |
| MIL-STD-27733 | `MIL-STD-27733` | MODIFICATION AND MARKING REQUIREMENTS FOR TEST EQUIPMENT IN AEROSPACE VEHICLES AND RELATED SUPPORT EQUIPMENT | 1998-05-18 | 1 of 1 current components public |
| MIL-STD-188-125-1A — Notice 2 | `MIL-STD-188-125-1A NOT 2` | High-Altitude Electromagnetic Pulse (HEMP) Protection for Ground-Based Facilities Performing Critical, Time-Urgent Missions Part 1 Fixed Facilities | 2026-08-31 | Partial: 2 of 3 current components public; 1 restricted |
| MIL-STD-13231 — Change 2 · Notice 1 | `MIL-STD-13231(2) NOT 1` | Marking of Electronic Items | 2022-07-21 | 1 of 1 current components public |
| MIL-STD-3007G | `MIL-STD-3007G` | Unified Facilities Criteria, Facilities Criteria and Unified Facilities Guide Specifications | 2019-11-01 | 1 of 1 current components public |
| MIL-STD-3006D | `MIL-STD-3006D` | Food Protection Requirements for Commercial Food Establishments | 2026-04-17 | 1 of 1 current components public |
| MIL-STD-5522 — Notice 4 | `MIL-STD-5522 NOT 4` | Test Requirements and Methods for Aircraft Hydraulic and Emergency Pneumatic Systems | 2024-06-04 | 5 of 5 current components public |
| MIL-STD-3009 — Notice 2 | `MIL-STD-3009 NOT 2` | LIGHTING, AIRCRAFT, NIGHT VISION IMAGING SYSTEM (NVIS) COMPATIBLE | 2024-04-04 | 3 of 3 current components public |
| MIL-STD-3003B | `MIL-STD-3003B` | Vehicles, Wheeled: Preparation for Shipment and Storage of | 2007-09-24 | 1 of 1 current components public |
| MIL-STD-2042-7 — Notice 2 | `MIL-STD-2042-7 NOT 2` | Fiber Optic Cable Topology Installation Standard Methods for Naval Ships (Pierside Connectivity Cable Assemblies and Interconnection Hardware) (Part 7 of 7 Parts) | 2023-08-04 | 3 of 3 current components public |
| MIL-STD-188-168 — Notice 2 | `MIL-STD-188-168 NOT 2` | Interoperability Standard for SHF Satellite Communications Baseband Equipment | 2020-03-20 | Partial: 2 of 3 current components public; 1 restricted |
| MIL-STD-3010C — Change 1 · Notice 1 | `MIL-STD-3010C(1) NOT 1` | Test Procedures for Packaging Materials and Containers | 2023-05-10 | 1 of 1 current components public |
| MIL-STD-3013B | `MIL-STD-3013B` | Glossary of Definitions, Ground Rules, and Mission Profiles to Define Air Vehicle Performance Capability | 2022-09-01 | 1 of 1 current components public |
| MIL-STD-967 — Change 3 · Notice 1 | `MIL-STD-967(3) NOT 1` | Defense Handbooks Format and Content | 2025-08-27 | 1 of 1 current components public |
| MIL-STD-6040B — Change 1 · Notice 2 | `MIL-STD-6040B(1) NOT 2` | U.S. Message Text Format (USMTF) Description | 2023-01-24 | Partial: 1 of 2 current components public; 1 restricted |
| MIL-STD-3014 — Change 3 · Notice 2 | `MIL-STD-3014(3) NOT 2` | Mission Data Exchange Format | 2026-05-27 | 3 of 3 current components public |
| MIL-STD-188-148A — Notice 1 | `MIL-STD-188-148A NOT 1` | Anti Jam (AJ) Communications in the High Frequency (2-30 MHz) Band (U) | 2021-07-15 | 1 of 1 current components public |
| MIL-STD-1582D — Notice 3 | `MIL-STD-1582D NOT 3` | Extremely High Frequency (EHF) Low Data Rate (LDR) Satellite Data Link Standards (SDLS) Uplinks and Downlinks (U) | 2020-03-19 | 3 of 3 current components public |
| MIL-STD-188-136A — Notice 3 | `MIL-STD-188-136A NOT 3` | Satellite Data Link Standard (SDLS) for EHF Medium Data Rate (MDR) Uplinks and Downlinks (U) | 2020-03-19 | 3 of 3 current components public |
| MIL-STD-3015A — Notice 2 | `MIL-STD-3015A NOT 2` | Satellite Data Link Standard (SDLS) for Advanced Extremely High Frequency (AEHF) Extended Data Rate (XDR) Uplinks and Downlinks (U) | 2020-03-19 | 3 of 3 current components public |
| MIL-STD-8591 — Change 1 · Notice 3 | `MIL-STD-8591(1) NOT 3` | Airborne Stores, Suspension Equipment and Aircraft-Store Interface (Carriage Phase) | 2022-06-01 | 3 of 3 current components public |
| MIL-STD-6004 — Notice 3 | `MIL-STD-6004 NOT 3` | Tactical Data Link (TDL) Link-4 Message Standard | 2007-08-28 | 2 of 2 current components public |
| MIL-STD-3020 — Notice 1 | `MIL-STD-3020 NOT 1` | Fire Resistance of U.S. Naval Surface Ships | 2024-05-02 | 2 of 2 current components public |
| MIL-STD-3022 — Change 1 · Notice 1 | `MIL-STD-3022(1) NOT 1` | Documentation of Verification, Validation, and Accreditation (VV&A) for Models and Simulations | 2026-02-09 | 2 of 2 current components public |
| MIL-STD-3021 — Change 2 · Notice 2 | `MIL-STD-3021(2) NOT 2` | Materials Deposition, Cold Spray | 2025-03-21 | 3 of 3 current components public |
| MIL-STD-3026A — Notice 1 | `MIL-STD-3026A NOT 1` | Chemical Cleaning of Sewage Collection Piping Systems on Navy Surface Ships | 2026-04-14 | 2 of 2 current components public |
| MIL-STD-3028 — Change 2 · Notice 1 | `MIL-STD-3028(2) NOT 1` | Joint Modular Intermodal Container | 2021-09-30 | 2 of 2 current components public |
| MIL-STD-3031B — Change 1 | `MIL-STD-3031B(1)` | Army Business Rules for S1000D: International Specification for Technical Publications Utilizing a Common Source Data Base | 2025-07-31 | 2 of 2 current components public |
| MIL-STD-3029 — Notice 1 | `MIL-STD-3029 NOT 1` | Hot Gun Cook-Off Hazards Assessment, Test and Analysis | 2021-04-27 | 2 of 2 current components public |
| MIL-STD-31000C | `MIL-STD-31000C` | Technical Data Packages | 2025-02-03 | 1 of 1 current components public |
| MIL-STD-3030 — Notice 2 | `MIL-STD-3030 NOT 2` | Error Budgets for Gun Effectiveness Modeling | 2025-10-23 | Partial: 2 of 3 current components public; 1 restricted |
| MIL-STD-1678-3C — Change 3 | `MIL-STD-1678-3C(3)` | Fiber Optic Cabling Systems Requirements and Measurements Physical, Mechanical, Environmental and Material Measurements (Part 3 of 6 Parts) | 2025-03-24 | 1 of 1 current components public |
| MIL-STD-1678-2A — Change 1 · Notice 1 | `MIL-STD-1678-2A(1) NOT 1` | Fiber Optic Cabling Systems Requirements and Measurements (Part 2: Optical Measurements) (Part 2 of 6 Parts) | 2022-01-07 | 1 of 1 current components public |
| MIL-STD-1678-1D — Change 3 | `MIL-STD-1678-1D(3)` | Fiber Optic Cabling Systems Requirements and Measurements (Part 1: Design, Installation and Maintenance Requirements) (Part 1 of 6 Parts) | 2024-11-21 | 2 of 2 current components public |
| MIL-STD-1678-4C — Change 4 | `MIL-STD-1678-4C(4)` | Fiber Optic Cabling Systems Requirements and Measurements (Part 4: Test Sample Configuration and Fabrication Requirements) (Part 4 of 6 Parts) | 2025-06-23 | 1 of 1 current components public |
| MIL-STD-1678-5B — Change 2 | `MIL-STD-1678-5B(2)` | Fiber Optic Cabling Systems Requirements and Measurements (Part 5: Design Phase, Supplemental and Legacy Measurements) (Part 5 of 6 Parts) | 2022-06-24 | 1 of 1 current components public |
| MIL-STD-3033 — Notice 3 | `MIL-STD-3033 NOT 3` | Particle/Sand Erosion Testing of Rotor Blade Protective Materials | 2025-03-21 | 4 of 4 current components public |
| MIL-STD-3034A — Notice 2 | `MIL-STD-3034A NOT 2` | Reliability-Centered Maintenance (RCM) Process | 2024-03-27 | 3 of 3 current components public |
| MIL-STD-6018D — Notice 1 | `MIL-STD-6018D NOT 1` | Integrated Broadcast Service (IBS) Common Message Format (CMF) Standard | 2025-04-25 | 5 of 5 current components public |
| MIL-STD-3038 — Notice 1 | `MIL-STD-3038 NOT 1` | Test Methods for Ballistic Defeat Materials | 2024-03-21 | 2 of 2 current components public |
| MIL-STD-750-1B — Change 2 | `MIL-STD-750-1B(2)` | Environmental Test Methods for Semiconductor Devices Part 1: Test Methods 1000 Through 1999 | 2023-04-18 | 1 of 1 current components public |
| MIL-STD-750-2B — Change 4 | `MIL-STD-750-2B(1)(4)` | Mechanical Test Methods for Semiconductor Devices Part 2: Test Methods 2001 Through 2999 | 2026-04-08 | 1 of 1 current components public |
| MIL-STD-750-5 — Change 1 | `MIL-STD-750-5(1)` | High Reliability Space Application Test Methods for Semiconductor Devices Part 5: Test Methods 5000 Through 5999 | 2018-08-10 | 1 of 1 current components public |
| MIL-STD-750-3 — Change 2 · Notice 1 | `MIL-STD-750-3(1)(2) NOT 1` | Transistor Electrical Test Methods for Semiconductor Devices Part 3: Test Methods 3000 Through 3999 | 2026-05-29 | 1 of 1 current components public |
| MIL-STD-750-4A | `MIL-STD-750-4A` | Diode Electrical Test Methods for Semiconductor Devices Part 4: Test Methods 4000 Through 4999 | 2026-03-26 | 1 of 1 current components public |
| MIL-STD-2169D — Notice 1 | `MIL-STD-2169D NOT 1` | High-Altitude Electromagnetic Pulse (HEMP) Environment | 2023-07-26 | 3 of 3 current components public |
| MIL-STD-1678-6A — Change 2 | `MIL-STD-1678-6A(2)` | Fiber Optic Cabling Systems Requirements and Measurements (Part 6: Parts and Support Equipment Commonality and Standardization Requirements) (Part 6 of 6 Parts) | 2022-01-07 | 1 of 1 current components public |
| MIL-STD-3041A | `MIL-STD-3041A` | Requirements for Food and Water Risk Assessments (FWRA) | 2022-06-01 | 1 of 1 current components public |
| MIL-STD-3048C | `MIL-STD-3048C` | Air Force Business Rules for the Implementation of S1000D | 2023-05-15 | 1 of 1 current components public |
| MIL-STD-3035 — Notice 1 | `MIL-STD-3035 NOT 1` | USAF Aircraft Arresting Systems (Design Criteria) | 2018-04-09 | 2 of 2 current components public |
| MIL-STD-3036 — Notice 1 | `MIL-STD-3036 NOT 1` | USAF Aircraft Arresting Systems (Test Method) | 2018-04-11 | 2 of 2 current components public |
| MIL-STD-3049 — Change 1 · Notice 1 | `MIL-STD-3049(1) NOT 1` | Materials Deposition, DDM: Direct Deposition of Metal for Remanufacture, Restoration and Recoating | 2021-08-27 | 2 of 2 current components public |
| MIL-STD-3045A — Notice 1 | `MIL-STD-3045A NOT 1` | U.S. Navy Surface Ship Machinery Arrangements | 2026-04-14 | Partial: 1 of 2 current components public; 1 restricted |
| MIL-STD-188-204 — Change 1 · Notice 1 | `MIL-STD-188-204(1) NOT 1` | Soldier Radio Waveform Soldier System Combat Communications Mode | 2024-02-23 | Partial: 1 of 2 current components public; 1 restricted |
| MIL-STD-3001-1A — Change 2 · Notice 1 | `MIL-STD-3001-1A(2) NOT 1` | Preparation of Digital Technical Information for Multi-Output Presentation of Technical Manuals (Part 1 of 8 Parts) | 2026-04-21 | 2 of 2 current components public |
| MIL-STD-3001-2A — Change 2 · Notice 1 | `MIL-STD-3001-2A(2) NOT 1` | Digital Technical Information for Multi-Output Presentation of Technical Manuals Description, Principles of Operation, and Operation Data (Part 2 of 8 Parts) | 2026-04-21 | 2 of 2 current components public |
| MIL-STD-3001-3A — Change 2 · Notice 1 | `MIL-STD-3001-3A(2) NOT 1` | Digital Technical Information for Multi-Output Presentation of Technical Manuals Testing and Troubleshooting Procedures (Part 3 of 8 Parts) | 2026-04-21 | 2 of 2 current components public |
| MIL-STD-3001-4A — Change 2 · Notice 1 | `MIL-STD-3001-4A(2) NOT 1` | Digital Technical Information for Multi-Output Presentation of Technical Manuals Maintenance Information with Illustrated Parts Breakdown (IPB) (Part 4 of 8 Parts) | 2026-04-21 | 2 of 2 current components public |
| MIL-STD-3001-5A — Change 2 · Notice 1 | `MIL-STD-3001-5A(2) NOT 1` | Digital Technical Information for Multi-Output Presentation of Technical Manuals Aircraft Wiring Information (Part 5 of 8 Parts) | 2026-04-21 | 3 of 3 current components public |
| MIL-STD-3001-6A — Change 2 · Notice 1 | `MIL-STD-3001-6A(2) NOT 1` | Digital Technical Information for Multi-Output Presentation of Technical Manuals Structural Repair Information (Part 6 of 8 Parts) | 2026-04-21 | 2 of 2 current components public |
| MIL-STD-3001-7A — Change 2 · Notice 1 | `MIL-STD-3001-7A(2) NOT 1` | Digital Technical Information for Multi-Output Presentation of Technical Manuals Periodic Maintenance Requirements (Part 7 of 8 Parts) | 2026-04-21 | 2 of 2 current components public |
| MIL-STD-3001-8A — Change 2 · Notice 1 | `MIL-STD-3001-8A(2) NOT 1` | Digital Technical Information for Multi-Output Presentation of Technical Manuals Illustrated Parts Breakdown (IPB) (Part 8 of 8 Parts) | 2026-04-21 | 2 of 2 current components public |
| MIL-STD-202-206 — Notice 2 | `MIL-STD-202-206 NOT 2` | Method 206, Life (Rotational) | 2024-10-22 | 3 of 3 current components public |
| MIL-STD-202-101 — Notice 2 | `MIL-STD-202-101 NOT 2` | Method 101, Salt Atmosphere (Corrosion) | 2024-10-23 | 3 of 3 current components public |
| MIL-STD-202-201 — Notice 2 | `MIL-STD-202-201 NOT 2` | Method 201, Vibration | 2024-10-22 | 3 of 3 current components public |
| MIL-STD-202-203 — Change 1 · Notice 2 | `MIL-STD-202-203(1) NOT 2` | Method 203, Random Drop | 2025-02-10 | 4 of 4 current components public |
| MIL-STD-202-104 — Notice 2 | `MIL-STD-202-104 NOT 2` | Method 104, Immersion | 2024-10-23 | 3 of 3 current components public |
| MIL-STD-202-204 — Notice 2 | `MIL-STD-202-204 NOT 2` | Method 204, Vibration, High Frequency | 2024-10-22 | 3 of 3 current components public |
| MIL-STD-202-105 — Notice 2 | `MIL-STD-202-105 NOT 2` | Method 105, Barometric Pressure (Reduced) | 2024-10-23 | 3 of 3 current components public |
| MIL-STD-202-208A — Notice 1 | `MIL-STD-202-208A NOT 1` | Method 208, Solderability | 2024-10-29 | 2 of 2 current components public |
| MIL-STD-202-106 — Notice 2 | `MIL-STD-202-106 NOT 2` | Method 106, Moisture Resistance | 2024-10-23 | 3 of 3 current components public |
| MIL-STD-202-107 — Notice 2 | `MIL-STD-202-107 NOT 2` | Method 107, Thermal Shock | 2024-10-23 | 3 of 3 current components public |
| MIL-STD-202-108 — Notice 2 | `MIL-STD-202-108 NOT 2` | Method 108, Life (at Elevated Ambient Temperature) | 2024-10-23 | 3 of 3 current components public |
| MIL-STD-202-207A | `MIL-STD-202-207A` | Method 207, High Impact Shock | 2025-03-19 | 1 of 1 current components public |
| MIL-STD-202-109 — Notice 2 | `MIL-STD-202-109 NOT 2` | Method 109, Explosion | 2024-10-22 | 3 of 3 current components public |
| MIL-STD-202-210 — Notice 2 | `MIL-STD-202-210 NOT 2` | Method 210, Resistance to Soldering Heat | 2024-10-28 | 3 of 3 current components public |
| MIL-STD-202-110 — Notice 2 | `MIL-STD-202-110 NOT 2` | Method 110, Sand and Dust | 2024-10-22 | 3 of 3 current components public |
| MIL-STD-202-111 — Notice 2 | `MIL-STD-202-111 NOT 2` | Method 111, Flammability (External Flame) | 2024-10-23 | 3 of 3 current components public |
| MIL-STD-202-211 — Change 1 · Notice 2 | `MIL-STD-202-211(1) NOT 2` | Method 211, Terminal Strength | 2025-09-16 | 2 of 2 current components public |
| MIL-STD-202-112A | `MIL-STD-202-112A` | Test Method Standard Method 112, Seal | 2024-10-31 | 1 of 1 current components public |
| MIL-STD-202-301 — Notice 2 | `MIL-STD-202-301 NOT 2` | Method 301, Dielectric Withstanding Voltage | 2024-10-22 | 3 of 3 current components public |
| MIL-STD-202-212 — Notice 2 | `MIL-STD-202-212 NOT 2` | Method 212, Acceleration | 2024-10-24 | 3 of 3 current components public |
| MIL-STD-202-302 — Notice 2 | `MIL-STD-202-302 NOT 2` | Method 302, Insulation Resistance | 2024-10-22 | 3 of 3 current components public |
| MIL-STD-202-213 — Notice 2 | `MIL-STD-202-213 NOT 2` | Method 213, Shock (Specified Pulse) | 2024-10-24 | 3 of 3 current components public |
| MIL-STD-202-214 — Notice 2 | `MIL-STD-202-214 NOT 2` | Method 214, Random Vibration | 2024-10-24 | 3 of 3 current components public |
| MIL-STD-202-303 — Notice 2 | `MIL-STD-202-303 NOT 2` | Method 303, DC Resistance | 2024-10-24 | 3 of 3 current components public |
| MIL-STD-202-309 — Notice 2 | `MIL-STD-202-309 NOT 2` | Method 309, Voltage Coefficient of Resistance Determination Procedure | 2024-10-28 | 3 of 3 current components public |
| MIL-STD-202-308 — Notice 2 | `MIL-STD-202-308 NOT 2` | Method 308, Current-Noise Test for Fixed Resistors | 2024-10-28 | 3 of 3 current components public |
| MIL-STD-202-103 — Notice 2 | `MIL-STD-202-103 NOT 2` | Method 103, Humidity (Steady State) | 2024-10-23 | 3 of 3 current components public |
| MIL-STD-202-215A — Notice 1 | `MIL-STD-202-215A NOT 1` | Method 215, Resistance to Solvents | 2025-09-16 | 2 of 2 current components public |
| MIL-STD-202-305 — Notice 2 | `MIL-STD-202-305 NOT 2` | Method 305, Capacitance | 2024-10-24 | 3 of 3 current components public |
| MIL-STD-202-306 — Notice 2 | `MIL-STD-202-306 NOT 2` | Method 306, Quality Factor (Q) | 2024-10-24 | 3 of 3 current components public |
| MIL-STD-202-307 — Notice 2 | `MIL-STD-202-307 NOT 2` | Method 307, Contact Resistance | 2024-10-24 | 3 of 3 current components public |
| MIL-STD-202-310 — Notice 2 | `MIL-STD-202-310 NOT 2` | Method 310, Contact-Chatter Monitoring | 2024-10-24 | 3 of 3 current components public |
| MIL-STD-202-304 — Notice 2 | `MIL-STD-202-304 NOT 2` | Method 304, Resistance-Temperature Characteristic | 2024-10-28 | 3 of 3 current components public |
| MIL-STD-202-311 — Notice 2 | `MIL-STD-202-311 NOT 2` | Method 311, Life, Low Level Switching | 2024-10-22 | 3 of 3 current components public |
| MIL-STD-202-312 — Notice 2 | `MIL-STD-202-312 NOT 2` | Method 312, Life, Intermediate Current Switching | 2024-10-23 | 3 of 3 current components public |
| MIL-STD-202-217 — Notice 1 | `MIL-STD-202-217 NOT 1` | Method 217, Particle Impact Noise Detection (PIND) | 2020-01-22 | 2 of 2 current components public |
| MIL-STD-3050A | `MIL-STD-3050A` | Aircrew Breathing Systems (ACBS) | 2022-07-01 | 1 of 1 current components public |
| MIL-STD-202-209A | `MIL-STD-202-209A` | Method 209, Radiographic Inspection | 2019-09-06 | 1 of 1 current components public |
| MIL-STD-3053 — Notice 4 | `MIL-STD-3053 NOT 4` | Satellite Systems Natural and Nuclear Environment Standard | 2025-08-12 | 4 of 4 current components public |
| MIL-STD-1791-1 — Notice 1 | `MIL-STD-1791-1 NOT 1` | Criteria for Nonstandard Airdrop Equipment and Payloads | 2026-05-26 | Partial: 1 of 2 current components public; 1 restricted |
| MIL-STD-3040A — Change 1 | `MIL-STD-3040A(1)` | Qualification, Fabrication, Welding, and Inspection of Armor and Non-Armor Steel Weldments | 2024-02-14 | 1 of 1 current components public |
| MIL-STD-81259 — Notice 2 | `MIL-STD-81259 NOT 2` | Naval Airframe Interface Requirements for Tie-Downs | 2026-04-21 | Partial: 2 of 3 current components public; 1 restricted |
| MIL-STD-3037 | `MIL-STD-3037` | Inspection Criteria for International Organization for Standardization (ISO) Containers and Department of Defense Standard Family of ISO Shelters AMSC | 2017-01-27 | 1 of 1 current components public |
| MIL-STD-18717 — Notice 2 | `MIL-STD-18717 NOT 2` | Design Criteria for Naval Aircraft Arresting Hook Systems | 2026-08-04 | Partial: 2 of 3 current components public; 1 restricted |
| MIL-STD-3058 | `MIL-STD-3058` | Occupant-Centric Protection for Military Ground Vehicles | 2017-05-04 | 1 of 1 current components public |
| MIL-STD-3057 — Notice 1 | `MIL-STD-3057 NOT 1` | Arc Welding Of Armor Grade Aluminum | 2019-05-13 | 2 of 2 current components public |
| MIL-STD-202-218 — Change 1 | `MIL-STD-202-218(1)` | Method 218, Board Flex | 2018-09-19 | 1 of 1 current components public |
| MIL-STD-202-219 — Change 1 · Notice 1 | `MIL-STD-202-219(1) NOT 1` | Method 219, Shear Stress | 2025-03-25 | 2 of 2 current components public |
| MIL-STD-202-220 — Notice 1 | `MIL-STD-202-220 NOT 1` | Method 220, Ultrasonic Inspection | 2022-07-08 | 2 of 2 current components public |
| MIL-STD-3060 — Change 2 | `MIL-STD-3060(2)` | Foundation Geoint Digital Print and Color Separation | 2021-11-02 | 1 of 1 current components public |
| MIL-STD-3004-1C — Change 1 | `MIL-STD-3004-1C(1)` | Quality Assurance for Bulk Fuels, Lubricants, and Related Products | 2025-07-21 | 1 of 1 current components public |
| MIL-STD-3004-2A | `MIL-STD-3004-2A` | Quality Assurance and Shelf-Life Extension Testing for Packaged Fuels, Lubricants and Related Products | 2020-11-16 | 1 of 1 current components public |
| MIL-STD-1399-300-2 — Notice 1 | `MIL-STD-1399-300-2 NOT 1` | Department of Defense Interface Standard Section 300, Part 2 Medium Voltage Electric Power, Alternating Current | 2024-03-06 | 2 of 2 current components public |
| MIL-STD-1399-300-1 — Notice 1 | `MIL-STD-1399-300-1 NOT 1` | Department of Defense Interface Standard Section 300, Part 1 Low Voltage Electric Power, Alternating Current | 2024-03-06 | 2 of 2 current components public |
| MIL-STD-3063 — Notice 1 | `MIL-STD-3063 NOT 1` | Rotorcraft Structural Integrity Program (RSIP) | 2023-08-22 | 2 of 2 current components public |
| MIL-STD-3059 — Notice 1 | `MIL-STD-3059 NOT 1` | Acceptance Criteria for Adhesives for High-Loading Rate Applications | 2023-12-04 | 2 of 2 current components public |
| MIL-STD-3064 — Notice 1 | `MIL-STD-3064 NOT 1` | Evaluation of Quality of Textile Materials | 2024-04-04 | 2 of 2 current components public |
| MIL-STD-883-3 — Change 1 | `MIL-STD-883-3(1)` | Electrical Tests (Digital) for Microcircuits Part 3: Test Methods 3000-3999 | 2025-03-07 | 1 of 1 current components public |
| MIL-STD-883-1 — Change 2 · Notice 1 | `MIL-STD-883-1(2) NOT 1` | Environmental Test Methods for Microcircuits Part 1: Test Methods 1000-1999 | 2024-07-03 | 2 of 2 current components public |
| MIL-STD-883-2 — Change 1 | `MIL-STD-883-2(1)` | Mechanical Test Methods for Microcircuits Part 2: Test Methods 2000-2999 | 2022-01-12 | 1 of 1 current components public |
| MIL-STD-883-4 — Change 1 | `MIL-STD-883-4(1)` | Electrical Tests (Linear) for Microcircuits Part 4: Test Methods 4000-4999 | 2025-03-28 | 1 of 1 current components public |
| MIL-STD-883-5 — Change 2 | `MIL-STD-883-5(1)(2)` | Test Procedures for Microcircuits Part 5: Test Methods 5000-5999 | 2026-01-14 | 1 of 1 current components public |
| MIL-STD-3065 — Notice 1 | `MIL-STD-3065 NOT 1` | Satellite Systems Nuclear Survivability Protection (SSNS-P) | 2025-08-12 | Partial: 1 of 2 current components public; 1 restricted |
| MIL-STD-8047 — Notice 1 | `MIL-STD-8047 NOT 1` | Quality Assurance and Shelf-Life Extension Testing for Paints, Sealers, Adhesives and Related Products | 2026-06-03 | 2 of 2 current components public |
| MIL-STD-3067 | `MIL-STD-3067` | Insert Arrangements for MIL-DTL-32689 Circular Electrical Connectors | 2021-11-19 | 1 of 1 current components public |
| MIL-STD-188-241B — Notice 1 | `MIL-STD-188-241B NOT 1` | Single Channel Ground and Airborne Radio System (SINCGARS) | 2023-01-31 | 2 of 2 current components public |
| MIL-STD-3069 | `MIL-STD-3069` | Specialized Reusable Metal Container Design for Naval Aviation Repairables (Non-Ordnance) | 2022-10-11 | 1 of 1 current components public |
| MIL-STD-1399-407 | `MIL-STD-1399-407` | Interface Standard Section 407 DC Magnetic Field Environment | 2022-07-14 | 1 of 1 current components public |
| MIL-STD-3071 — Change 1 | `MIL-STD-3071(1)` | Tactical Microgrid Communications and Control | 2024-07-08 | 1 of 1 current components public |
| MIL-STD-3072 | `MIL-STD-3072` | Ground Vehicle 600 Volts DC Electric Power Characteristics | 2023-01-23 | 1 of 1 current components public |
| MIL-STD-3076 — Notice 1 | `MIL-STD-3076 NOT 1` | Rotorcraft Structural Demonstration | 2024-09-27 | 2 of 2 current components public |
| MIL-STD-3078 | `MIL-STD-3078` | Interoperability Standard for Batteries Utilized in Army Equipment | 2024-11-14 | 1 of 1 current components public |
| MIL-STD-1399-300-3 | `MIL-STD-1399-300-3` | Department of Defense Interface Standard Section 300, Part 3 Low Voltage Electric Power Direct Current | 2026-04-09 | 1 of 1 current components public |
| MIL-STD-3077 | `MIL-STD-3077` | Army Airborne Radar System Airworthiness Qualification and Verification Requirements | 2026-01-28 | 1 of 1 current components public |
| MIL-STD-3083 | `MIL-STD-3083` | Preparation of Digital Technical Information for Army Aviation Operator’s Manuals and Checklists for Crewed and Uncrewed Aircraft Systems | 2026-04-30 | 1 of 1 current components public |
| MIL-STD-3087 | `MIL-STD-3087` | Army Airworthiness Qualification Engine Control System and Accessory Components | 2026-06-16 | 1 of 1 current components public |

</details>

## What the engine preserves

Evidence packets retain exact edition and package identity, source citations, any available governing context, derivation and review status, authorization scope, coverage, and known evidence limits. Missing or unclassified context remains explicit rather than being inferred.

StandardsForge supplies evidence. It does not decide applicability, approve requirements or test plans, select a project baseline, or certify compliance. Those decisions remain with the responsible engineering and program authorities.

## Documentation

| Goal | Guide |
|---|---|
| Install and operate the prepared library | [Prepared library](docs/wiki/PREPARED_LIBRARY.md) |
| Search, retrieve, enumerate, and compare evidence | [Query guide](docs/wiki/QUERY_GUIDE.md) |
| Connect a local model through read-only MCP | [Model integration](docs/wiki/MODEL_INTEGRATION.md) |
| Acquire sources and rebuild packs or releases | [Maintainer workflows](docs/wiki/MAINTAINER_WORKFLOWS.md) |
| Understand authorization, integrity, rights, and evidence layers | [Architecture and trust](docs/wiki/ARCHITECTURE_AND_TRUST.md) |
| Run qualification and release gates | [Validation and releases](docs/wiki/VALIDATION_AND_RELEASES.md) |
| Browse all documentation | [StandardsForge wiki](docs/wiki/README.md) |

The source repository is for development and maintainer workflows. End users should start with the prepared release above.

## Contributing and security

Read [CONTRIBUTING.md](CONTRIBUTING.md) before changing code, contracts, documentation, or release artifacts. Contributions must use synthetic or demonstrably redistributable fixtures and preserve exact evidence, authorization, uncertainty, and review boundaries.

Report suspected vulnerabilities through the private process in [SECURITY.md](SECURITY.md), not through a public issue.

## License

StandardsForge code is licensed under [Apache 2.0](LICENSE). Standards content has separate permissions; the code license does not grant rights to third-party documents.

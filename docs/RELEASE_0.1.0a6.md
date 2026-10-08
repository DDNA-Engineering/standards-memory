# StandardsForge v0.1.0a6 release evidence

Release date: October 8, 2026. Source commit: `7974fe8b9b91a048ec0c2b0d001529283e633f4f`, tagged `v0.1.0a6`.

## Install

The [PyPI code package](https://pypi.org/project/standardsforge/0.1.0a6/) installs the CLI:

```sh
python -m pip install "standardsforge==0.1.0a6"
standardsforge --help
```

For the precompiled standards library, download and extract the [prepared release](https://github.com/DDNA-Engineering/standards-memory/releases/tag/v0.1.0a6). Run `python setup.py` on Windows or `sh setup.sh` on Linux/macOS. Windows x64 CPython 3.12 also supports the bundled offline MCP profile through `setup.ps1`. The PyPI package contains code only; it does not download standards content.

## Published identities

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `standardsforge-ready-0.1.0a6.zip` | 1,080,443,923 | `06bccbb0c3839507b1c7b6147887cd394e08ab17695ddec554b7e82c27c69983` |
| `standardsforge-0.1.0a6-py3-none-any.whl` | 179,831 | `72b442852da8eb651154e91aa0a7b915bf711e8c290cb18e9154724cb90f085a` |
| `standardsforge-0.1.0a6.tar.gz` | 276,176 | `29f337038100adae2686eb1a4c90499dad941bac1399b32ad184cab790e89057` |

The prepared archive contains the exact PyPI wheel and its reproducible-build provenance. Two complete prepared builds produced identical bytes; the archive CRC and embedded wheel hash were independently read back. Earlier local Windows wheels and prepared candidates had different byte identities and are not the published artifacts above.

## Included evidence

One setup installs 441 packages: 438 acquisition-pinned page packs, the 8,319-record automated MIL-STD-810H outline-v3, and separate MIL-STD-1661 transcription and semantic recovery packs. The acquisition baseline remains 912 PDFs, 35,235 physical pages, and 35,218 page records. Additional representations do not add source documents.

The transcription pack retains all 18 reviewed scan pages and raster evidence. The semantic pack has 41 reviewed records, including five separate 4.2.4 directives with the original governing clause retained as required context. Complete statement and typed qualifier assertions bind their exact evidence spans. Explicitly reviewed blank pages retain evidence and coverage without fabricated retrieval text.

| Representation | Package digest |
|---|---|
| MIL-STD-810H outline-v3 | `ff9824bb1adf8b55d53bd6f409294c012dd12479003796fc9637294fbb049e35` |
| MIL-STD-1661 transcription | `45db3b3e308f6c9f382ad2214464816053fa1e451ee3754236d61a73d9ece435` |
| MIL-STD-1661 semantics | `4c5e1c46a0584d97bd0c9fc6cbd6735a58ea12251bd0b3a3d53ae7ca1402add0` |

The offline Windows MCP wheelhouse includes PyJWT 2.15.0; the PyPI MCP extra requires at least that patched version.

## Validation boundaries

- [Source CI and release attestation](https://github.com/DDNA-Engineering/standards-memory/actions/runs/37787526765): passed the tagged source across Windows/Linux and Intel/Apple-silicon macOS on Python 3.11/3.12. The local full suite passed 197 tests with two platform skips from an empty working directory.
- [PyPI trusted publication](https://github.com/DDNA-Engineering/standards-memory/actions/runs/37788843524): reproducible wheel and sdist, eight native installed-wheel jobs, then successful OIDC publication with attestations.
- [Prepared native acceptance](https://github.com/DDNA-Engineering/standards-memory/actions/runs/37790506350): exact archive identity, first and repeated offline core setup on Windows, Ubuntu, Intel macOS, and Apple-silicon macOS; full-integrity doctor, exact resolve, search, and source evidence retrieval. Windows also passed first/repeat offline MCP setup with a real stdio query.
- All three runtime-bound real-document suites passed: 11 outline, 18 transcription, and 23 semantic/context cases, totaling 52 cases and 137 expected record occurrences. Prepared first and repeated setup replay these checks before readiness.
- Public acceptance: the released ZIP and checksum were downloaded anonymously and matched the recorded identity. The wheel downloaded from PyPI matched the bundled wheel. A fresh environment outside the checkout ran both the module CLI and installed console entry point, installed the two recovery packs, and passed all 41 recovery cases with socket creation denied.

This is an alpha release with bounded observed acceptance. The outline remains automated and unreviewed. The recovered 1661 statements are bounded agent-reviewed evidence, not independent human approval or corpus-wide semantic qualification. Historical selection and restricted-component limits remain visible. No claim of globally optimal compression, project applicability, compliance, or corpus-wide visual/semantic completeness is made.

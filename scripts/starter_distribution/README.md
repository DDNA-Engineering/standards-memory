# StandardsForge synthetic starter

This small bundle proves portable local installation and exact evidence retrieval with two fictional, redistributable contract packs. It is for onboarding and integration testing only. It is not a real standards corpus and makes no claim about real-document discovery, semantic quality, applicability, compliance, or approval.

Python 3.11 or newer is required. From the extracted bundle directory, run:

```text
python setup.py
python run.py search "axial load" --package-digest 3c27ee682401e154425f806614a800d744f472f1be41e9e412f9214460f12117 --principal local-user
```

`setup.py` uses only the Python standard library before installing the included dependency-free wheel. It validates every immutable bundle file, installs with dependency resolution and package indexes disabled, validates both fictional packs, installs them under the bundled trusted policy, runs the full-integrity doctor, and proves lexical discovery plus exact governing-context retrieval.

Every setup rerun revalidates the bundle, receipt, installed state, and evidence smokes. Local runtime state remains under `.venv/` and `.standardsforge/` in this extracted directory.

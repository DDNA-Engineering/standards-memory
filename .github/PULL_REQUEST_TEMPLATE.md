## Scope

Describe the bounded requirement, backlog task, or defect this change addresses.

- Requirement/task:
- User-visible outcome:
- Intentionally out of scope:

## Implementation

Summarize the implementation and identify any changed machine contracts, storage formats, migrations, generated artifacts, or compatibility behavior.

## Evidence

List the exact commands run and their observed results. Keep local validation, protected CI, publication, deployment, and user acceptance separate.

```text
command
observed result
```

Include fixture, package, wheel, archive, or provenance digests when the result depends on exact bytes.

## Negative and compatibility cases

- [ ] Invalid or unauthorized input is rejected.
- [ ] Tampering or integrity drift is rejected where applicable.
- [ ] Existing supported data and callers retain defined behavior, or a migration is included.
- [ ] Incomplete evidence remains explicitly incomplete.

Explain any item that does not apply.

## Security, authorization, and rights

Describe effects on source trust, parser isolation, path handling, authorization, revocation, network behavior, model behavior, content permissions, and redistribution. Confirm that fixtures contain no credentials, customer data, proprietary standards text, classified information, CUI, ITAR-controlled data, or other restricted material.

## Migration and rollback

Describe how existing state changes, how rollback works, and why neither direction invents semantic classification, review, applicability, compliance, or approval.

## Documentation and limits

- [ ] The root README remains focused on prepared-library startup.
- [ ] Deeper behavior is documented in the wiki or normative design documents.
- [ ] Time-sensitive claims name their artifact, snapshot date, version, or commit.
- [ ] Known limitations and unmeasured behavior are explicit.

## Contributor certification

- [ ] Commits include the Developer Certificate of Origin sign-off (`git commit -s`).
- [ ] This pull request is one reviewable vertical slice.

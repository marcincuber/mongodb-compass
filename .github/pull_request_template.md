## Problem and result

Describe the problem and the behavior or documentation this change delivers. Link a related issue if there is one.

## Validation

List the checks you ran and their results. For checks you could not run, explain why. Separate local/schema checks from live AWS, database, or cluster verification.

## Deployment impact

Describe configuration changes, compatibility concerns, session interruptions, or storage effects. Write “None” if this does not apply.

## Review checklist

- [ ] The change is focused, and documentation/examples match the resulting behavior.
- [ ] Relevant checks from CONTRIBUTING.md have passed, or limitations are explained above.
- [ ] No real credentials, private keys, database contents, or sensitive connection details are included.
- [ ] Runtime changes preserve UI authentication, DocumentDB TLS validation, and non-root Kubernetes operation, or explicitly explain the proposed change.

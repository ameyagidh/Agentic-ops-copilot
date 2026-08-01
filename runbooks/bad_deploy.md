# Runbook: regression introduced by a recent deploy

## Symptoms
Error rate or latency increases shortly (minutes) after a deploy; stack
traces or log signatures are new relative to the prior version.

## Likely causes
- A code change introduced a bug on a previously-untested path.
- A config/feature-flag change shipped alongside the code.
- A dependency version bump changed behavior.

## Recommended actions
1. Confirm the timing correlation between the deploy and the onset of errors.
2. Roll back to the previous known-good revision if correlation is strong.
3. If rollback isn't immediately possible, disable the associated feature
   flag and file a follow-up to fix forward.

# Write safety

Local account updates are enabled by default. Use writes only when the user explicitly requests the change. Before executing one:

1. Read the exact schema for the operation.
2. Resolve exact food, serving, meal, diary, or measurement IDs and units from live account data or user-provided values.
3. Submit a unique idempotency key for that intended change.
4. Read the account state back to confirm the result.
5. If the response is `outcome_unknown`, inspect account state before retrying. Never replay with a new key just to see whether it worked.

Remote writes require the separate `myfitnesspal:write` OAuth grant and local consent. A successful mocked or offline test is not evidence of upstream persistence. Website endpoints can change and this connector uses an unofficial library. Do not treat estimates as measured nutrition; the image estimator does not change the diary by itself.

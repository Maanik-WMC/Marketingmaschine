# End-User Workflow

Use the Marketing Console first:

```text
http://192.168.178.75:18117/ui
```

## What The Two n8n Pipelines Mean

`WAMOCON Marketing - Manual Content Intake`

- Starts a new content item from a campaign brief.
- Requires campaign, persona, channel, objective, CTA, proof source, UTM, hypothesis, and test variable.
- Creates a draft state.
- Stops at human review.
- Does not publish.

`WAMOCON Marketing - Human Approval`

- Takes an existing content ID.
- Records the human review decision.
- Requires brand score, fact check, privacy check, and AI disclosure check.
- Creates a draft-only scheduler payload only when all approval checks pass.
- Still requires final approval inside Postiz or the publishing platform.

## Simple Browser Procedure

1. Open `http://192.168.178.75:18117/ui`.
2. Use `Intake`.
3. Choose a preset campaign or custom.
4. Keep `AI draft language` on `Deutsch (Deutschland)` for the German market, or switch to English only for a non-German campaign.
5. Enter the content idea, offer, proof source, CTA, UTM fields, and hypothesis.
6. Click `Create Draft`.
7. Read `Created Post Preview` for the generated public post copy.
8. Read the generated draft state and fix any blocked fields.
9. Open `Approval`.
10. Select or paste the content ID.
11. Approve only after proof, consent, privacy, and brand checks pass.
12. Use `Scheduler Draft Preview` as the draft copy for Postiz.
13. Use `Leads` when a person or company reacts, fills a form, or asks for the offer.
14. Use `Routing` to prepare the approved draft for Postiz or a qualified lead for Twenty/Mautic.
15. Use `Analytics` after 72 hours, 7 days, 14 days, and 30 days.
16. Use `Creative` to create ComfyUI-ready visual briefs.
17. Use `Phases` for the morning readiness check before relying on the full pipeline.

## Where Created Content Is Saved

In the browser:

- `Dashboard` shows recent content states.
- `Recent Content` in the left sidebar lists saved content IDs.
- Clicking a recent item opens it in `Approval` and fills the post preview.
- `Created Post Preview` shows the generated public draft before approval.
- `Scheduler Draft Preview` shows the approved draft-only scheduler copy after approval.
- `Lead Intake` shows the lead score, next action, CRM payload, and Mautic payload.
- `Routing Outbox` shows prepared, blocked, sent, or failed external handoff records.
- `Phase Readiness` shows complete, partial, and blocked implementation phases.

On Nvidia-1:

```text
/home/wamocon/lokal-ai-stack/marketing/wamocon-marketing-machine/runtime-data/states/
/home/wamocon/lokal-ai-stack/marketing/wamocon-marketing-machine/runtime-data/leads/
/home/wamocon/lokal-ai-stack/marketing/wamocon-marketing-machine/runtime-data/outbox/
```

Approved items include a `scheduler_payload.copy` field. This is the draft-only public copy to review and then move into Postiz.

## Clean Old Test Data And Create Fresh Mock Results

Use this only for mock/smoke test records. It keeps real campaign records like `k1-qa-risk-audit-weekly`.

Preview what would be deleted:

```bash
python3 scripts/clean_test_data.py --root runtime-data --dry-run
```

Delete only `mock-*` and `smoke-*` records:

```bash
python3 scripts/clean_test_data.py --root runtime-data --confirm delete-test-data
```

Create fresh mock results:

```bash
python3 scripts/mock_pipeline_test.py --base-url http://127.0.0.1:8117 --n8n-url http://127.0.0.1:5678
```

The test output includes `created_content_ids`, `fresh_result_urls`, and `approved_state_url`. Open the UI, search that content ID in `Recent Content`, then click it to see the actual generated post and scheduler draft.

## How To Add A Lead

Use this when someone responds to the campaign, submits a landing form, writes a message, or asks for the offer.

1. Open `Leads`.
2. Paste or select the `Source content ID`.
3. Enter the campaign, offer, persona, company, email or phone, and the message.
4. Tick consent only when follow-up consent is documented.
5. Keep the UTM fields from the post or landing page.
6. Click `Score Lead`.
7. Read `Lead Result`.
8. If it says `sales_follow_up`, use the CRM payload for Twenty/HubSpot and the Mautic payload for nurture.
9. If it says `consent_required`, do not route it to CRM or marketing automation.
10. If it says `manual_source_review`, fix the source content ID before counting it as campaign value.

## How To Route To Tools

Use `Routing` only after a draft is approved or a lead is qualified.

1. Open `Routing`.
2. For a post, paste the approved content ID and click `Prepare Postiz Draft`.
3. For a lead, paste the lead ID, choose `Twenty CRM` or `Mautic nurture`, and click `Prepare Lead Route`.
4. Keep `Dry-run only` checked until real endpoint paths and tokens are configured.
5. Check `Route Result`.
6. Check `Recent Outbox`.
7. If status is `prepared`, the payload is ready but not sent.
8. If status is `blocked`, fix approval, consent, or source data first.
9. If live writes are later enabled, status can become `sent` or `failed`.

Real external writes require all of these:

- `MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES=true`.
- A target base URL.
- A target endpoint path, for example `POSTIZ_CREATE_DRAFT_PATH`.
- A target API token.
- Human approval already recorded in this system.

## What To Put In A Campaign Brief

Required:

- Campaign name, for example `K1 QA Consulting`.
- Persona, for example `IT-Leiter Thomas`.
- Channel, for example `LinkedIn`.
- Format, for example `expert_post`.
- AI draft language, normally `Deutsch (Deutschland)` for WAMOCON's German market.
- Objective, for example `QA-Risikoaudit mit senioriger Testexpertise und belegbaren Prüfpunkten anbieten`.
- CTA, for example `QA-Risikoaudit anfragen`.
- Proof source, for example `Kampagnen/kampagne_1_consulting_qa.json`.
- UTM source, medium, and campaign.
- Hypothesis, for example `Ein nachweisbasierter QA-Beitrag erzeugt qualifizierte Anfragen von IT-Leitern`.
- Test variable, for example `offer`, `hook`, `format`, `persona`, `cta`, or `landing_page`.

Rules:

- Do not use a claim without a proof source.
- Use German by default for German-market campaigns. Switch to English only when the campaign is intentionally international.
- Do not use customer, employee, or applicant material without consent.
- Instagram should use 3 to 5 focused hashtags.
- Do not approve content when brand score is below 90.
- Do not treat scheduler payload as public approval.

## Edge Cases

- Missing proof source: blocked.
- Unapproved proof source: blocked.
- English marketing copy in a German brief: blocked.
- Too many Instagram hashtags: blocked.
- Bad content ID during approval: rejected with a clear 404 error.
- Weak approval: routed to revision, not scheduler.
- Approved content: creates draft-only scheduler payload.
- Created public copy: visible in `Created Post Preview` and, after approval, in `Scheduler Draft Preview`.
- Good lead with consent: scored and prepared for CRM follow-up.
- Missing lead consent: stored for audit, but CRM and marketing routing are blocked.
- Unknown source content ID: lead is stored, but marked for manual source review.
- Invalid lead email: rejected.
- Approved draft route: prepared for Postiz as draft-only, dry-run by default.
- Unapproved draft route: blocked.
- Qualified lead route: prepared for Twenty/Mautic, dry-run by default.
- No-consent lead route: blocked.
- High clicks but no leads: fix landing page.
- High engagement but no B2B leads: fix audience or offer.
- No business value after 30 days: stop or pivot.
- Good qualified leads after 30 days: scale.

## Current Phase Reality

Complete now:

- Content intake, proof gate, German-market draft, human approval, and scheduler draft payload.
- Governance checks for proof, consent, privacy, approval, and Instagram hashtag limits.
- Lead intake, consent guard, qualification scoring, CRM/Mautic payload contract.
- Analytics decisions for 72h, 7d, 14d, and 30d.
- n8n workflow files for weekly planning and all analytics review windows.
- Browser UI for intake, approval, leads, routing, analytics, creative briefs, status, and phases.

Partial until final credentials or production services are explicitly enabled:

- Postiz/Twenty/Mautic live writes are dry-run only.
- ComfyUI creates workflow briefs but does not auto-submit generation jobs.
- Kimi is optional backup only and must pass API authentication before use.
- LangGraph and MCP are scaffolded/configured but not yet the durable production runtime and gateway.

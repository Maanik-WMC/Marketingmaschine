# Operations Runbook

## Daily Checks

- Review failed n8n executions.
- Review new leads and CRM follow-up status.
- Review comments and community risks.
- Check whether any posts need immediate human response.
- Check local model, ComfyUI, Postgres, Redis, and n8n health.

## 72-Hour Review

Use this to catch early signal. Do not judge revenue yet.

Check:

- saves
- shares
- comments from target buyers
- profile visits
- CTR
- landing-page clicks

Actions:

- Weak impressions and no buyer signal: rewrite hook or thumbnail.
- Good engagement and no clicks: strengthen CTA.
- Good clicks and no leads: fix landing page.
- Buyer comments or qualified clicks: prepare follow-up content.

## 7-Day Review

Compare formats and variants.

Keep:

- posts with target-buyer comments
- posts with saves/shares
- posts with qualified clicks
- posts that produce leads or calls

Change:

- weak first lines
- unclear CTA
- generic proof
- over-broad persona targeting

## 14-Day Review

This is the message-market fit gate.

Stop or pivot if:

- no useful buyer signal
- engagement comes from the wrong audience
- clicks do not become leads
- lead quality is poor

Do not solve a bad offer by increasing volume.

## 30-Day Review

Judge business value.

Primary metrics:

- qualified B2B leads
- booked calls
- landing-page conversion
- LinkedIn saves, shares, and comments from target buyers
- CRM pipeline value

Secondary metrics:

- impressions
- likes
- followers
- reel views

Decisions:

- Scale if qualified leads, booked calls, or pipeline value exist.
- Iterate if engagement is real but the offer needs work.
- Stop if no commercial signal appears.

## Weekly Rolling Calendar Update

Every Friday:

- keep the top 20 percent of content patterns
- rewrite the middle 60 percent
- remove the bottom 20 percent
- update next 30 days
- refresh proof assets and claims

## Incident Handling

If a risky post is scheduled:

1. Pause scheduler integration.
2. Mark content as blocked.
3. Create audit record.
4. Review proof, consent, and approval history.
5. Publish correction only after human approval.

If negative comments appear:

1. Do not auto-reply.
2. Community Agent drafts a response.
3. Compliance Agent checks legal/privacy risk.
4. Human approves or escalates.

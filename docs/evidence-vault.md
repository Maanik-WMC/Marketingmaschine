# Evidence Vault

## Purpose

The Evidence Vault prevents generic or risky AI content. It stores proof that agents can safely reuse in public marketing.

## Approved Evidence Types

- app screenshots
- app URLs
- project facts
- customer-approved case studies
- employee-approved stories
- benchmark sources
- internal delivery statistics
- consent references

## Claim Rules

Every claim needs a source:

- factual claim: source required
- statistic: source required
- ROI claim: source and reviewer approval required
- customer story: consent required
- employee story: consent required

## Minimum Record

Use `evidence_items` from `db/schema.sql`:

- id
- claim
- source type
- source reference
- public-use approval flag
- consent reference
- owner

Do not store secrets or raw personal data in evidence records.

## Current Runtime Vault

The running marketing agent also checks `config/evidence-vault.json`.

Rules:

- A `proof_sources` entry must match an approved evidence `id`.
- `approved_for_public_use` must be `true`.
- Customer, employee, or applicant stories must include a `consent_ref`.
- Unknown proof sources are blocked before drafting.

Initial approved internal campaign references:

- `Kampagnen/kampagne_1_consulting_qa.json`
- `Kampagnen/kampagne_2_ki_sokrates.json`
- `Kampagnen/kampagne_5_app_entwicklung.json`

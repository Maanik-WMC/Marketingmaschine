# Twenty CRM Integration

Use Twenty as the open-source CRM option when HubSpot is not preferred.

Minimum CRM mapping:

- `LeadRecord.company` -> Company name
- `LeadRecord.email` -> Person email
- `LeadRecord.campaign` -> Source campaign
- `LeadRecord.offer` -> Interest/offer
- `LeadRecord.qualification_score` -> Lead score
- `LeadRecord.next_action` -> Follow-up task

Every CRM record must keep UTM source data so business value can be traced back to content and campaign.

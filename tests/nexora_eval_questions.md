# Nexora policy: evaluation questions and answer key

These questions shipped at the bottom of `data/corpus/Nexora_Tech_Azure_Cloud_Data_Access_Policy.md`.
They were moved here, unchanged, because a question bank inside the corpus is itself retrieved as
context: the two hallucination questions (12 and 13) carried their own expected behaviour, so the app
could "refuse correctly" by reading the answer key instead of by noticing the policy is silent.

The policy body is unchanged. Use these questions from here, with the answers below.

## Answer key (checked against the policy text)

| # | Level | Answer from the policy body |
|---|---|---|
| 1 | Direct | Public, Internal, Confidential, Restricted (section 2) |
| 2 | Direct | Confidential: customer data is listed under Confidential (section 2) |
| 3 | Direct | Development, Testing, Production (section 3) |
| 4 | Direct | Security Administrator (section 4) |
| 5 | Specific | No, not directly, unless specifically authorized (section 6) |
| 6 | Specific | In an approved secrets manager such as Azure Key Vault, never in source code (section 9) |
| 7 | Specific | Read approved business datasets, run approved queries, generate reports; cannot modify production infrastructure (section 4) |
| 8 | Specific | Inactive accounts and unnecessary permissions must be removed (section 10) |
| 9 | Reasoning | No: least privilege, assigned at the lowest practical scope, and no broad Storage Account permissions (sections 5 and 8) |
| 10 | Reasoning | Only with appropriate anonymization or security approval (sections 3 and 7) |
| 11 | Reasoning | Business justification, Azure RBAC permissions, manager or data-owner approval, logging and monitoring, periodic access review (section 6) |
| 12 | Hallucination | Not specified anywhere: the app must say it does not know and must not invent an ID |
| 13 | Hallucination | Not specified anywhere: the app must say it does not know |
| 14 | Cross-section | Combine section 6 (production data access), section 7 (customer data) and section 5 (least privilege) |

## The original section, verbatim

# RAG Evaluation Questions

Use these questions individually in your RAG application after uploading this policy.

### Level 1 — Direct Retrieval

1. What are the four data classification levels defined by Nexora Tech?
2. What classification is assigned to customer data?
3. What are the three Azure environments maintained by Nexora Tech?
4. Which role is responsible for reviewing security configurations and access assignments?

### Level 2 — Specific Information

5. Can a developer directly access Restricted production data?
6. Where should Azure access keys and database passwords be stored?
7. What permissions does a Data Analyst have?
8. What should happen to inactive accounts?

### Level 3 — Reasoning / Retrieval

9. A developer only needs to read files from one Azure Storage container. Should the developer receive access to the entire Azure subscription?
10. Can production data be copied into a development environment?
11. What approvals are required before accessing production data?

### Level 4 — Hallucination Test

12. What is Nexora Tech's Azure subscription ID?

**Expected behavior:** The RAG should state that the policy does not specify an Azure subscription ID. It should not invent one.

13. What is the maximum number of Azure administrators allowed at Nexora Tech?

**Expected behavior:** The RAG should state that the policy does not specify a maximum number of Azure administrators.

### Level 5 — Cross-Section Question

14. What restrictions apply when a developer wants to access customer data stored in production?

This question requires information from multiple sections, including **Production Data Access**, **Customer Data**, and **Least-Privilege Requirement**.

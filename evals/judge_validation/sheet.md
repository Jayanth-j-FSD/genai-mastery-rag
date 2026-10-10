# Week 6: judge validation sheet (blind)

<!-- sample_size: 24 -->
<!-- seed: 42 -->

## How to fill this in

You are the grader. For each block, read the QUESTION, the CONTEXT the system was shown, the
REFERENCE answer and the system's ANSWER, and decide whether the answer is acceptable:

- `ok`  the answer is faithful to the context, answers what was asked, handles absence honestly
  (a refusal is right only when the context lacks the answer), and, if two documents disagree,
  says so or names the document it used.
- `bad` anything less: an invented fact, a missing part of a list, a different question answered,
  a refusal when the context had the answer, a confident answer when it did not.

Fill `verdict:` with `ok` or `bad` on every block. A short `note:` on each `bad` helps you later.
You are not shown what the judge or the rule checks decided, on purpose.
Then run `python scripts/validate_judge.py`.

---

## trace j01

**Question:** What is the maximum number of Azure administrators allowed at Nexora Tech?

**Context the system was shown:**

1. `Nexora_Tech_Azure_Cloud_Data_Access_Policy.md`: ## 13. Policy Summary / / > **Nexora Tech employees and applications may access only the Azure resources and data required to perform their authorized responsibilities.**
2. `Nexora_Tech_Azure_Cloud_Data_Access_Policy.md`: Nexora Tech maintains three primary Azure environments: / / - Development / - Testing / - Production / / Production resources must not be used for development or testing unless explicitly approved by the Cloud Security Team. / / Production data must not be copied into development environments without appropriate anonymization or security approval. / / ## 4. Access Roles / / ### Cloud Administrator / / Can: / / - Manage Azure infrastructure. / - Manage resource configurations. / - Manage networking and security settings. / - Manage role assignments when authorized. / / Cloud Administrators should not automatically have access to application data unless their responsibilities require it. / / ### Developer / / Can:
3. `Nexora_Tech_Azure_Cloud_Data_Access_Policy.md`: Security administrators should use privileged access only when required. / / ## 5. Least-Privilege Requirement / / Every user, application, service principal, and managed identity must receive only the permissions required for their responsibilities. / / For example: / / > A developer who only needs to read objects from an Azure Storage container must not receive permission to delete the storage account. / / Access should be assigned at the lowest practical scope, such as a specific resource or resource group instead of the entire subscription. / / Nexora Tech should prefer built-in Azure roles where they satisfy the requirement and use custom roles only when necessary. / / ## 6. Production Data Access / / Production data is classified as **Confidential** or **Restricted**, depending on its contents.
4. `Nexora_Tech_Azure_Cloud_Data_Access_Policy.md`: ## 11. Logging and Monitoring / / Access to sensitive Azure resources must be logged. / / Security teams should monitor: / / - Failed authentication attempts. / - Privileged operations. / - Changes to RBAC assignments. / - Access to Restricted data. / - Unexpected data downloads. / - Changes to security configurations. / / Audit logs must be retained according to Nexora Tech's applicable compliance and retention requirements. / / ## 12. Policy Violations / / Unauthorized access to Confidential or Restricted information may result in: / / - Immediate access suspension. / - Security investigation. / - Incident response procedures. / - Mandatory remediation. / - Disciplinary action according to company policy. / / ## 13. Policy Summary

**Reference:** The policy does not specify a maximum number of administrators. The correct reply is that it does not know.

**Answer:** I don't know based on the provided documents.

- verdict: 
- note: 

---

## trace j02

**Question:** Is MFA mandatory?

**Context the system was shown:**

1. `security-policy.md`: # Security Policy / / - All laptops must have full-disk encryption enabled. / - Passwords must be at least **12 characters** and are rotated every **90 days**. / - Multi-factor authentication (MFA) is required for all company accounts. / - Report a suspected security incident to security@northwind.example within **1 hour**. / - Customer data must never be copied to personal devices or personal cloud storage.

**Reference:** Yes. Multi-factor authentication is required for all company accounts (the handbook says it is mandatory for corporate email, source-code repositories, VPN access and production administration tools).

**Answer:** Yes, multi-factor authentication (MFA) is required for all company accounts [source: security-policy.md].

- verdict: 
- note: 

---

## trace j03

**Question:** A developer only needs to read files from one Azure Storage container. Should the developer receive access to the entire Azure subscription?

**Context the system was shown:**

1. `Nexora_Tech_Azure_Cloud_Data_Access_Policy.md`: Security administrators should use privileged access only when required. / / ## 5. Least-Privilege Requirement / / Every user, application, service principal, and managed identity must receive only the permissions required for their responsibilities. / / For example: / / > A developer who only needs to read objects from an Azure Storage container must not receive permission to delete the storage account. / / Access should be assigned at the lowest practical scope, such as a specific resource or resource group instead of the entire subscription. / / Nexora Tech should prefer built-in Azure roles where they satisfy the requirement and use custom roles only when necessary. / / ## 6. Production Data Access / / Production data is classified as **Confidential** or **Restricted**, depending on its contents.
2. `Nexora_Tech_Azure_Cloud_Data_Access_Policy.md`: Applications processing customer information should use managed identities or other approved identity mechanisms instead of storing long-lived credentials in source code. / / ## 8. Azure Storage Access / / Azure Storage resources containing Confidential or Restricted data must use authenticated and authorized access. / / Public access should be disabled unless the resource is intentionally hosting Public information. / / Users should not receive broad Storage Account permissions when access to a specific container or resource is sufficient. / / ## 9. Secrets and Credentials / / The following must never be stored directly in source code: / / - Azure access keys / - API keys / - Database passwords / - Client secrets / - Encryption keys / - Service credentials
3. `Nexora_Tech_Azure_Cloud_Data_Access_Policy.md`: ## 13. Policy Summary / / > **Nexora Tech employees and applications may access only the Azure resources and data required to perform their authorized responsibilities.**
4. `Nexora_Tech_Azure_Cloud_Data_Access_Policy.md`: Nexora Tech maintains three primary Azure environments: / / - Development / - Testing / - Production / / Production resources must not be used for development or testing unless explicitly approved by the Cloud Security Team. / / Production data must not be copied into development environments without appropriate anonymization or security approval. / / ## 4. Access Roles / / ### Cloud Administrator / / Can: / / - Manage Azure infrastructure. / - Manage resource configurations. / - Manage networking and security settings. / - Manage role assignments when authorized. / / Cloud Administrators should not automatically have access to application data unless their responsibilities require it. / / ### Developer / / Can:

**Reference:** No. Least privilege means access at the lowest practical scope, such as the specific container, not the whole subscription.

**Answer:** No. According to the policy, access should be assigned at the lowest practical scope, and users should not receive broad permissions when access to a specific container is sufficient [source: Nexora_Tech_Azure_Cloud_Data_Access_Policy.md]. Specifically, a developer who only needs to read objects from an Azure Storage container must not receive permission to delete the storage account, and every user must receive only the permissions required for their responsibilities [source: Nexora_Tech_Azure_Cloud_Data_Access_Policy.md]. / / [source: Nexora_Tech_Azure_Cloud_Data_Access_Policy.md]

- verdict: 
- note: 

---

## trace j04

**Question:** How long do I have to hand in a receipt after buying something?

**Context the system was shown:**

1. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. / - The company may periodically review this rule and communicate changes through official internal channels. / - Final settlement is targeted within **30 calendar days** after completion of required exit formalities, subject to payroll dependencies and applicable law.

**Reference:** Submit the expense within 30 days of purchase, with a receipt.

**Answer:** I don't know based on the provided documents.

- verdict: 
- note: 

---

## trace j05

**Question:** Where should Azure access keys and database passwords be stored?

**Context the system was shown:**

1. `Nexora_Tech_Azure_Cloud_Data_Access_Policy.md`: - Azure access keys / - API keys / - Database passwords / - Client secrets / - Encryption keys / - Service credentials / / Secrets must be stored using an approved secrets-management solution such as **Azure Key Vault**. / / Access to secrets must be restricted to authorized applications and administrators. / / ## 10. Access Reviews / / Access to Confidential and Restricted resources must be reviewed periodically. / / Inactive accounts and unnecessary permissions must be removed. / / Privileged access should be minimized and, where appropriate, protected through Microsoft Entra Privileged Identity Management (PIM). / / ## 11. Logging and Monitoring / / Access to sensitive Azure resources must be logged. / / Security teams should monitor:
2. `Nexora_Tech_Azure_Cloud_Data_Access_Policy.md`: Applications processing customer information should use managed identities or other approved identity mechanisms instead of storing long-lived credentials in source code. / / ## 8. Azure Storage Access / / Azure Storage resources containing Confidential or Restricted data must use authenticated and authorized access. / / Public access should be disabled unless the resource is intentionally hosting Public information. / / Users should not receive broad Storage Account permissions when access to a specific container or resource is sufficient. / / ## 9. Secrets and Credentials / / The following must never be stored directly in source code: / / - Azure access keys / - API keys / - Database passwords / - Client secrets / - Encryption keys / - Service credentials
3. `Nexora_Tech_Azure_Cloud_Data_Access_Policy.md`: Security administrators should use privileged access only when required. / / ## 5. Least-Privilege Requirement / / Every user, application, service principal, and managed identity must receive only the permissions required for their responsibilities. / / For example: / / > A developer who only needs to read objects from an Azure Storage container must not receive permission to delete the storage account. / / Access should be assigned at the lowest practical scope, such as a specific resource or resource group instead of the entire subscription. / / Nexora Tech should prefer built-in Azure roles where they satisfy the requirement and use custom roles only when necessary. / / ## 6. Production Data Access / / Production data is classified as **Confidential** or **Restricted**, depending on its contents.
4. `Nexora_Tech_Azure_Cloud_Data_Access_Policy.md`: Nexora Tech maintains three primary Azure environments: / / - Development / - Testing / - Production / / Production resources must not be used for development or testing unless explicitly approved by the Cloud Security Team. / / Production data must not be copied into development environments without appropriate anonymization or security approval. / / ## 4. Access Roles / / ### Cloud Administrator / / Can: / / - Manage Azure infrastructure. / - Manage resource configurations. / - Manage networking and security settings. / - Manage role assignments when authorized. / / Cloud Administrators should not automatically have access to application data unless their responsibilities require it. / / ### Developer / / Can:

**Reference:** In an approved secrets-management solution such as Azure Key Vault, never directly in source code.

**Answer:** Azure access keys, database passwords, and other secrets must be stored using an approved secrets-management solution such as **Azure Key Vault**, and they must never be stored directly in source code [source: Nexora_Tech_Azure_Cloud_Data_Access_Policy.md].

- verdict: 
- note: 

---

## trace j06

**Question:** How long do I have to hand in a receipt after buying something?

**Context the system was shown:**

1. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: ### Booking / / / ### Airfare / / / ### Hotels / / / ### Meals / / / ### Local Transport / / / ### Expense Claims / / - Approved business expenses should normally be submitted within **30 days** of the expense date. / / ### Exceptions / / / ## 17. Workplace Safety and Facilities / / ### Office Safety / / / ### Emergency Response / / / ### Visitors / / / ### Security / / / ### Ergonomics / / / ### Incident Reporting / / / ## 18. Disciplinary Policy / / ### Policy Violations / / / ### Investigation / / / ### Warnings / / / ### Suspension / / / ### Serious Misconduct / / / ### Appeals / / / ### Consistency / / / ## 19. Separation and Exit / / ### Resignation / / / ### Notice Period / / - Standard notice period is **60 calendar days** for confirmed employees and **30 calendar days** during probation, unless the employment agreement specifies otherwise. / / ### Termination
2. `Acme-Employment-Terms-2026.md`: ## 4. Company-initiated termination / / For a company-initiated termination without cause, Acme will provide 30 calendar days of notice or pay in lieu of notice, subject to applicable law and the employee's written agreement. / / ## 5. Handover during notice / / Employees serving notice must complete a documented handover, return company property, and remain available during normal working hours unless People Operations approves an earlier release.
3. `Northstar-Remote-Work-Policy-2026.md`: ## 4. Home-office expenses / / Employees may claim up to 50 USD per month for internet service used for approved remote work. Claims require an itemized receipt and must be submitted by the tenth day of the following month. / / ## 5. Review and cancellation / / Remote-work approvals are reviewed every six months. The company may suspend or cancel an arrangement when business needs, performance, security, or attendance requirements are not met.
4. `expenses.md`: # Expenses Policy / / ## Submitting / Submit expenses within **30 days** of purchase through the finance portal with a receipt. / Expenses over **$200** require pre-approval from your manager. / / ## Limits / - Meals while travelling: up to **$40 per day**. / - Home-office equipment: up to **$500 per year**. / - Client entertainment: up to **$150 per event**, itemised receipt required. / / Reimbursements are paid with the next monthly payroll run.

**Reference:** Submit the expense within 30 days of purchase, with a receipt.

**Answer:** Based on the provided documents, you must submit expenses within **30 days** of the expense date or purchase [source: Synthetic_HR_Policy_RAG_Test_Dataset.md, expenses.md].

- verdict: 
- note: 

---

## trace j07

**Question:** Who do I tell if I think we have been hacked?

**Context the system was shown:**

1. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. / - The company may periodically review this rule and communicate changes through official internal channels. / - Suspected personal-data incidents must be reported to the Security team **within 4 hours of discovery**.

**Reference:** Report a suspected security incident to security@northwind.example within 1 hour. The handbook says a suspected personal-data incident goes to the Security team within 4 hours.

**Answer:** You must report suspected personal-data incidents to the Security team [source: Synthetic_HR_Policy_RAG_Test_Dataset.md].

- verdict: 
- note: 

---

## trace j08

**Question:** What are the three Azure environments?

**Context the system was shown:**

1. `Nexora_Tech_Azure_Cloud_Data_Access_Policy.md`: ## 2. Data Classification / / Nexora Tech classifies cloud data into four levels: / / | Classification | Description | Examples | / |---|---|---| / | **Public** | Information that can be shared externally | Public documentation, marketing content | / | **Internal** | Company information intended for employees | Internal procedures, technical documentation | / | **Confidential** | Sensitive business information | Customer data, contracts, financial reports | / | **Restricted** | Highly sensitive information requiring strict access | Credentials, security keys, personal data, production secrets | / / ## 3. Azure Environment Separation / / Nexora Tech maintains three primary Azure environments: / / - Development / - Testing / - Production
2. `Nexora_Tech_Azure_Cloud_Data_Access_Policy.md`: Nexora Tech maintains three primary Azure environments: / / - Development / - Testing / - Production / / Production resources must not be used for development or testing unless explicitly approved by the Cloud Security Team. / / Production data must not be copied into development environments without appropriate anonymization or security approval. / / ## 4. Access Roles / / ### Cloud Administrator / / Can: / / - Manage Azure infrastructure. / - Manage resource configurations. / - Manage networking and security settings. / - Manage role assignments when authorized. / / Cloud Administrators should not automatically have access to application data unless their responsibilities require it. / / ### Developer / / Can:
3. `Nexora_Tech_Azure_Cloud_Data_Access_Policy.md`: - Azure access keys / - API keys / - Database passwords / - Client secrets / - Encryption keys / - Service credentials / / Secrets must be stored using an approved secrets-management solution such as **Azure Key Vault**. / / Access to secrets must be restricted to authorized applications and administrators. / / ## 10. Access Reviews / / Access to Confidential and Restricted resources must be reviewed periodically. / / Inactive accounts and unnecessary permissions must be removed. / / Privileged access should be minimized and, where appropriate, protected through Microsoft Entra Privileged Identity Management (PIM). / / ## 11. Logging and Monitoring / / Access to sensitive Azure resources must be logged. / / Security teams should monitor:
4. `Nexora_Tech_Azure_Cloud_Data_Access_Policy.md`: # Nexora Tech — Azure Cloud Data Access & Security Policy / / **Policy ID:** NEXORA-CLOUD-SEC-001 / **Version:** 1.0 / **Effective Date:** January 1, 2026 / **Policy Owner:** Nexora Tech — Cloud Security Team / / ## 1. Purpose / / This policy defines how Nexora Tech manages access to data and cloud resources hosted on Microsoft Azure. / / The objectives are to: / / - Protect company and customer data from unauthorized access. / - Apply the principle of least privilege. / - Separate development, testing, and production environments. / - Monitor and audit access to sensitive data. / - Prevent unauthorized sharing or downloading of confidential information. / / ## 2. Data Classification / / Nexora Tech classifies cloud data into four levels:

**Reference:** Development, Testing and Production.

**Answer:** The three primary Azure environments maintained by Nexora Tech are: / / - Development / - Testing / - Production / / [source: Nexora_Tech_Azure_Cloud_Data_Access_Policy.md]

- verdict: 
- note: 

---

## trace j09

**Question:** How many weeks of paid parental leave are available?

**Context the system was shown:**

1. `Acme-Leave-Policy-2026.md`: ## 4. Sick leave / / Employees receive 12 paid sick-leave days per calendar year. A medical certificate may be requested for an absence longer than three consecutive working days. / / ## 5. Parental leave / / Eligible employees may take 16 weeks of paid parental leave after the birth or adoption of a child. The employee should notify People Operations at least 30 days before the expected start date where practicable.
2. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: 1. Annual leave: 24 days per calendar year; monthly accrual is 2 days. / 2. Sick leave: 12 days per calendar year. / 3. Casual leave: 6 days per calendar year. / 4. Hybrid remote work: up to 3 days per week for eligible employees. / 5. Core collaboration hours: 10:00 AM–4:00 PM IST. / 6. Confirmed employee notice period: 60 calendar days. / 7. Probation notice period: 30 calendar days. / 8. Standard probation: 6 months, extendable once by up to 3 months. / 9. Learning and certification budget: INR 30,000 per financial year. / 10. Expense claims: normally within 30 days. / 11. Personal-data incident reporting: within 4 hours of discovery. / 12. Performance improvement plan: standard duration 60 days. / 13. Annual company holiday calendar: 12 designated holidays.
3. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. / - The company may periodically review this rule and communicate changes through official internal channels. / - Full-time employees receive **24 days of annual leave per calendar year**. Leave is accrued monthly at 2 days per completed month.
4. `Acme-Leave-Policy-2026.md`: # ACME LEAVE POLICY 2026 / / Effective date: 2026-01-01 / / ## 1. Eligibility / / All regular full-time employees become eligible for the annual leave allowance after completing 30 calendar days of service. Contractors and temporary workers follow the terms in their engagement letter. / / ## 2. Annual leave allowance / / Employees receive 18 days of annual leave per calendar year. Employees joining after 1 July receive a prorated allowance based on completed months of service. / / ## 3. Carry-forward / / Employees may carry forward up to 10 unused annual-leave days into the next calendar year. Days above the 10-day limit expire on 31 March unless a written exception is approved by People Operations. / / ## 4. Sick leave

**Reference:** 16 weeks of paid parental leave.

**Answer:** Eligible employees may take 16 weeks of paid parental leave after the birth or adoption of a child [source: Acme-Leave-Policy-2026.md].

- verdict: 
- note: 

---

## trace j10

**Question:** How much can I claim for home-office equipment?

**Context the system was shown:**

1. `Northstar-Remote-Work-Policy-2026.md`: ## 4. Home-office expenses / / Employees may claim up to 50 USD per month for internet service used for approved remote work. Claims require an itemized receipt and must be submitted by the tenth day of the following month. / / ## 5. Review and cancellation / / Remote-work approvals are reviewed every six months. The company may suspend or cancel an arrangement when business needs, performance, security, or attendance requirements are not met.

**Reference:** Home-office equipment is reimbursed up to $500 per year.

**Answer:** I don't know based on the provided documents.

- verdict: 
- note: 

---

## trace j11

**Question:** How many days of notice must a confirmed or permanent employee give before resigning?

**Context the system was shown:**

1. `Acme-Employment-Terms-2026.md`: # ACME EMPLOYMENT TERMS POLICY 2026 / / Effective date: 2026-03-01 / / ## 1. Scope / / This policy applies to regular full-time Acme employees. A separate written agreement may provide a longer notice period, in which case the written agreement controls. / / ## 2. Probationary employees / / An employee who is still within the probationary period must provide 7 calendar days of written notice before resigning. Acme may waive some or all of this notice at its discretion. / / ## 3. Permanent employees / / After successful completion of probation, a permanent employee must provide 30 calendar days of written notice before resigning. The notice period begins on the date People Operations receives the written resignation. / / ## 4. Company-initiated termination
2. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. / - The company may periodically review this rule and communicate changes through official internal channels. / - Standard notice period is **60 calendar days** for confirmed employees and **30 calendar days** during probation, unless the employment agreement specifies otherwise.
3. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: 1. Annual leave: 24 days per calendar year; monthly accrual is 2 days. / 2. Sick leave: 12 days per calendar year. / 3. Casual leave: 6 days per calendar year. / 4. Hybrid remote work: up to 3 days per week for eligible employees. / 5. Core collaboration hours: 10:00 AM–4:00 PM IST. / 6. Confirmed employee notice period: 60 calendar days. / 7. Probation notice period: 30 calendar days. / 8. Standard probation: 6 months, extendable once by up to 3 months. / 9. Learning and certification budget: INR 30,000 per financial year. / 10. Expense claims: normally within 30 days. / 11. Personal-data incident reporting: within 4 hours of discovery. / 12. Performance improvement plan: standard duration 60 days. / 13. Annual company holiday calendar: 12 designated holidays.
4. `Acme-Employment-Terms-2026.md`: ## 4. Company-initiated termination / / For a company-initiated termination without cause, Acme will provide 30 calendar days of notice or pay in lieu of notice, subject to applicable law and the employee's written agreement. / / ## 5. Handover during notice / / Employees serving notice must complete a documented handover, return company property, and remain available during normal working hours unless People Operations approves an earlier release.

**Reference:** Under the Acme employment terms a permanent employee gives 30 calendar days of written notice; the handbook says 60 calendar days for confirmed employees. The documents disagree.

**Answer:** Based on the provided documents, a permanent employee must provide 30 calendar days of written notice before resigning [source: Acme-Employment-Terms-2026.md].

- verdict: 
- note: 

---

## trace j12

**Question:** How long until my retirement contributions start?

**Context the system was shown:**

1. `Acme-Leave-Policy-2026.md`: # ACME LEAVE POLICY 2026 / / Effective date: 2026-01-01 / / ## 1. Eligibility / / All regular full-time employees become eligible for the annual leave allowance after completing 30 calendar days of service. Contractors and temporary workers follow the terms in their engagement letter. / / ## 2. Annual leave allowance / / Employees receive 18 days of annual leave per calendar year. Employees joining after 1 July receive a prorated allowance based on completed months of service. / / ## 3. Carry-forward / / Employees may carry forward up to 10 unused annual-leave days into the next calendar year. Days above the 10-day limit expire on 31 March unless a written exception is approved by People Operations. / / ## 4. Sick leave

**Reference:** The pension match starts after 3 months of employment.

**Answer:** I don't know based on the provided documents.

- verdict: 
- note: 

---

## trace j13

**Question:** What is security@northwind.example used for?

**Context the system was shown:**

1. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: ## 14. Information Security / / ### Passwords / Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and managers. The policy applies to eligible employees unless a written exception, employment agreement, or applicable law states otherwise. Employees should contact People Operations when a situation is unclear. Managers are responsible for applying the policy consistently and documenting exceptions.
2. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: ### Security / Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and managers. The policy applies to eligible employees unless a written exception, employment agreement, or applicable law states otherwise. Employees should contact People Operations when a situation is unclear. Managers are responsible for applying the policy consistently and documenting exceptions.
3. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: ### Security / Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and managers. The policy applies to eligible employees unless a written exception, employment agreement, or applicable law states otherwise. Employees should contact People Operations when a situation is unclear. Managers are responsible for applying the policy consistently and documenting exceptions.
4. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: ### Phishing / Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and managers. The policy applies to eligible employees unless a written exception, employment agreement, or applicable law states otherwise. Employees should contact People Operations when a situation is unclear. Managers are responsible for applying the policy consistently and documenting exceptions.

**Reference:** security@northwind.example is where a suspected security incident must be reported, within 1 hour.

**Answer:** I don't know based on the provided documents.

- verdict: 
- note: 

---

## trace j14

**Question:** When do unused leave days above the carry-forward limit expire?

**Context the system was shown:**

1. `Acme-Leave-Policy-2026.md`: # ACME LEAVE POLICY 2026 / / Effective date: 2026-01-01 / / ## 1. Eligibility / / All regular full-time employees become eligible for the annual leave allowance after completing 30 calendar days of service. Contractors and temporary workers follow the terms in their engagement letter. / / ## 2. Annual leave allowance / / Employees receive 18 days of annual leave per calendar year. Employees joining after 1 July receive a prorated allowance based on completed months of service. / / ## 3. Carry-forward / / Employees may carry forward up to 10 unused annual-leave days into the next calendar year. Days above the 10-day limit expire on 31 March unless a written exception is approved by People Operations. / / ## 4. Sick leave
2. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. / - The company may periodically review this rule and communicate changes through official internal channels. / - Full-time employees receive **24 days of annual leave per calendar year**. Leave is accrued monthly at 2 days per completed month.
3. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. / - The company may periodically review this rule and communicate changes through official internal channels. / - Employees receive **6 days of casual leave per calendar year**. Casual leave is intended for short, unplanned personal needs.
4. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: 1. Annual leave: 24 days per calendar year; monthly accrual is 2 days. / 2. Sick leave: 12 days per calendar year. / 3. Casual leave: 6 days per calendar year. / 4. Hybrid remote work: up to 3 days per week for eligible employees. / 5. Core collaboration hours: 10:00 AM–4:00 PM IST. / 6. Confirmed employee notice period: 60 calendar days. / 7. Probation notice period: 30 calendar days. / 8. Standard probation: 6 months, extendable once by up to 3 months. / 9. Learning and certification budget: INR 30,000 per financial year. / 10. Expense claims: normally within 30 days. / 11. Personal-data incident reporting: within 4 hours of discovery. / 12. Performance improvement plan: standard duration 60 days. / 13. Annual company holiday calendar: 12 designated holidays.

**Reference:** They expire on 31 March unless a written exception is approved by People Operations.

**Answer:** Unused annual-leave days above the 10-day limit expire on 31 March unless a written exception is approved by People Operations [source: Acme-Leave-Policy-2026.md].

- verdict: 
- note: 

---

## trace j15

**Question:** How long do I have to hand in a receipt after buying something?

**Context the system was shown:**

1. `Acme-Employment-Terms-2026.md`: ## 4. Company-initiated termination / / For a company-initiated termination without cause, Acme will provide 30 calendar days of notice or pay in lieu of notice, subject to applicable law and the employee's written agreement. / / ## 5. Handover during notice / / Employees serving notice must complete a documented handover, return company property, and remain available during normal working hours unless People Operations approves an earlier release.
2. `expenses.md`: # Expenses Policy / / ## Submitting / Submit expenses within **30 days** of purchase through the finance portal with a receipt. / Expenses over **$200** require pre-approval from your manager. / / ## Limits / - Meals while travelling: up to **$40 per day**. / - Home-office equipment: up to **$500 per year**. / - Client entertainment: up to **$150 per event**, itemised receipt required. / / Reimbursements are paid with the next monthly payroll run.
3. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. / - The company may periodically review this rule and communicate changes through official internal channels. / - Final settlement is targeted within **30 calendar days** after completion of required exit formalities, subject to payroll dependencies and applicable law.
4. `support-faq.md`: # Support FAQ — Northwind Analytics / / **How do I reset my dashboard password?** / Use "Forgot password" on the login page; a reset link is emailed and is valid for 30 minutes. / / **What is the data refresh interval?** / Dashboards refresh every **15 minutes** on the Standard plan and every **1 minute** on Pro. / / **What does error ERR-4032 mean?** / ERR-4032 means the data source connection timed out. Retry after 60 seconds; if it persists, / check the source credentials in Settings > Connections. / / **How long is analytics data retained?** / Analytics data is retained for **13 months** on Standard and **36 months** on Pro.

**Reference:** Submit the expense within 30 days of purchase, with a receipt.

**Answer:** You must submit expenses within 30 days of purchase. / / [source: expenses.md]

- verdict: 
- note: 

---

## trace j16

**Question:** How many sick leave days do employees get per year?

**Context the system was shown:**

1. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: ### Attendance / / / ### Working Hours / / / ### Late Arrival / / / ### Early Departure / / / ### Absence Reporting / / / ### Overtime / / - Non-exempt employees must obtain written approval before working planned overtime. Overtime eligibility and compensation follow the applicable employment terms and law. / / ### Time Records / / / ## 5. Leave and Holidays / / ### Annual Leave / / - Full-time employees receive **24 days of annual leave per calendar year**. Leave is accrued monthly at 2 days per completed month. / / ### Sick Leave / / - Employees receive **12 days of sick leave per calendar year**. A medical certificate may be requested for absences exceeding 2 consecutive working days. / / ### Casual Leave
2. `Acme-Leave-Policy-2026.md`: # ACME LEAVE POLICY 2026 / / Effective date: 2026-01-01 / / ## 1. Eligibility / / All regular full-time employees become eligible for the annual leave allowance after completing 30 calendar days of service. Contractors and temporary workers follow the terms in their engagement letter. / / ## 2. Annual leave allowance / / Employees receive 18 days of annual leave per calendar year. Employees joining after 1 July receive a prorated allowance based on completed months of service. / / ## 3. Carry-forward / / Employees may carry forward up to 10 unused annual-leave days into the next calendar year. Days above the 10-day limit expire on 31 March unless a written exception is approved by People Operations. / / ## 4. Sick leave
3. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: 1. Annual leave: 24 days per calendar year; monthly accrual is 2 days. / 2. Sick leave: 12 days per calendar year. / 3. Casual leave: 6 days per calendar year. / 4. Hybrid remote work: up to 3 days per week for eligible employees. / 5. Core collaboration hours: 10:00 AM–4:00 PM IST. / 6. Confirmed employee notice period: 60 calendar days. / 7. Probation notice period: 30 calendar days. / 8. Standard probation: 6 months, extendable once by up to 3 months. / 9. Learning and certification budget: INR 30,000 per financial year. / 10. Expense claims: normally within 30 days. / 11. Personal-data incident reporting: within 4 hours of discovery. / 12. Performance improvement plan: standard duration 60 days. / 13. Annual company holiday calendar: 12 designated holidays.
4. `Acme-Leave-Policy-2026.md`: ## 4. Sick leave / / Employees receive 12 paid sick-leave days per calendar year. A medical certificate may be requested for an absence longer than three consecutive working days. / / ## 5. Parental leave / / Eligible employees may take 16 weeks of paid parental leave after the birth or adoption of a child. The employee should notify People Operations at least 30 days before the expected start date where practicable.

**Reference:** 12 paid sick leave days per calendar year.

**Answer:** Employees receive 12 days of sick leave per calendar year [source: Synthetic_HR_Policy_RAG_Test_Dataset.md] / 12 paid sick-leave days per calendar year [source: Acme-Leave-Policy-2026.md].

- verdict: 
- note: 

---

## trace j17

**Question:** ERR-4032

**Context the system was shown:**

1. `support-faq.md`: # Support FAQ — Northwind Analytics / / **How do I reset my dashboard password?** / Use "Forgot password" on the login page; a reset link is emailed and is valid for 30 minutes. / / **What is the data refresh interval?** / Dashboards refresh every **15 minutes** on the Standard plan and every **1 minute** on Pro. / / **What does error ERR-4032 mean?** / ERR-4032 means the data source connection timed out. Retry after 60 seconds; if it persists, / check the source credentials in Settings > Connections. / / **How long is analytics data retained?** / Analytics data is retained for **13 months** on Standard and **36 months** on Pro.
2. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: ### Emergency Leave / Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and managers. The policy applies to eligible employees unless a written exception, employment agreement, or applicable law states otherwise. Employees should contact People Operations when a situation is unclear. Managers are responsible for applying the policy consistently and documenting exceptions.
3. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: ## 12. Anti-Harassment and POSH / / ### Prohibited Conduct / Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and managers. The policy applies to eligible employees unless a written exception, employment agreement, or applicable law states otherwise. Employees should contact People Operations when a situation is unclear. Managers are responsible for applying the policy consistently and documenting exceptions.
4. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: ### Emergency Response / Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and managers. The policy applies to eligible employees unless a written exception, employment agreement, or applicable law states otherwise. Employees should contact People Operations when a situation is unclear. Managers are responsible for applying the policy consistently and documenting exceptions.
5. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: ### Access Requests / Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and managers. The policy applies to eligible employees unless a written exception, employment agreement, or applicable law states otherwise. Employees should contact People Operations when a situation is unclear. Managers are responsible for applying the policy consistently and documenting exceptions.
6. `Nexora_Tech_Azure_Cloud_Data_Access_Policy.md`: # Nexora Tech — Azure Cloud Data Access & Security Policy / / **Policy ID:** NEXORA-CLOUD-SEC-001 / **Version:** 1.0 / **Effective Date:** January 1, 2026 / **Policy Owner:** Nexora Tech — Cloud Security Team / / ## 1. Purpose / / This policy defines how Nexora Tech manages access to data and cloud resources hosted on Microsoft Azure. / / The objectives are to: / / - Protect company and customer data from unauthorized access. / - Apply the principle of least privilege. / - Separate development, testing, and production environments. / - Monitor and audit access to sensitive data. / - Prevent unauthorized sharing or downloading of confidential information. / / ## 2. Data Classification / / Nexora Tech classifies cloud data into four levels:

**Reference:** ERR-4032 means the data source connection timed out. Retry after 60 seconds; if it persists, check the source credentials in Settings > Connections.

**Answer:** Error ERR-4032 means that the data source connection timed out. You should retry after 60 seconds, and if the error persists, check the source credentials in Settings > Connections [source: support-faq.md].

- verdict: 
- note: 

---

## trace j18

**Question:** What should happen to inactive accounts?

**Context the system was shown:**

1. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: ### Absence Reporting / Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and managers. The policy applies to eligible employees unless a written exception, employment agreement, or applicable law states otherwise. Employees should contact People Operations when a situation is unclear. Managers are responsible for applying the policy consistently and documenting exceptions.
2. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: - Requests should normally be submitted through the employee portal before the relevant date. Managers should consider business continuity, employee circumstances, and previously approved requests. / - Records must be accurate and should be updated when circumstances change. Employees must not knowingly submit false information or alter company records without authorization. / - Where approval is required, approval does not remove the employee's responsibility to follow other applicable company policies. / - People Operations may maintain supporting records for audit, compliance, payroll, or operational purposes. Access is limited according to role and business need.
3. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: - Requests should normally be submitted through the employee portal before the relevant date. Managers should consider business continuity, employee circumstances, and previously approved requests. / - Records must be accurate and should be updated when circumstances change. Employees must not knowingly submit false information or alter company records without authorization. / - Where approval is required, approval does not remove the employee's responsibility to follow other applicable company policies. / - People Operations may maintain supporting records for audit, compliance, payroll, or operational purposes. Access is limited according to role and business need.
4. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: - Requests should normally be submitted through the employee portal before the relevant date. Managers should consider business continuity, employee circumstances, and previously approved requests. / - Records must be accurate and should be updated when circumstances change. Employees must not knowingly submit false information or alter company records without authorization. / - Where approval is required, approval does not remove the employee's responsibility to follow other applicable company policies. / - People Operations may maintain supporting records for audit, compliance, payroll, or operational purposes. Access is limited according to role and business need.

**Reference:** Inactive accounts and unnecessary permissions must be removed.

**Answer:** I don't know based on the provided documents.

- verdict: 
- note: 

---

## trace j19

**Question:** Who do I tell if I think we have been hacked?

**Context the system was shown:**

1. `security-policy.md`: # Security Policy / / - All laptops must have full-disk encryption enabled. / - Passwords must be at least **12 characters** and are rotated every **90 days**. / - Multi-factor authentication (MFA) is required for all company accounts. / - Report a suspected security incident to security@northwind.example within **1 hour**. / - Customer data must never be copied to personal devices or personal cloud storage.
2. `Nexora_Tech_Azure_Cloud_Data_Access_Policy.md`: ## 11. Logging and Monitoring / / Access to sensitive Azure resources must be logged. / / Security teams should monitor: / / - Failed authentication attempts. / - Privileged operations. / - Changes to RBAC assignments. / - Access to Restricted data. / - Unexpected data downloads. / - Changes to security configurations. / / Audit logs must be retained according to Nexora Tech's applicable compliance and retention requirements. / / ## 12. Policy Violations / / Unauthorized access to Confidential or Restricted information may result in: / / - Immediate access suspension. / - Security investigation. / - Incident response procedures. / - Mandatory remediation. / - Disciplinary action according to company policy. / / ## 13. Policy Summary
3. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: ## 12. Anti-Harassment and POSH / / ### Prohibited Conduct / / / ### Sexual Harassment / / / ### Reporting / / / ### Confidentiality / / - Confidential information includes customer information, source code, credentials, pricing, internal strategy, security details, and non-public employee information. / / ### Investigation / / / ### Non-Retaliation / / / ### Committee Process / / / ## 13. Grievance Management / / ### Grievance Types / / / ### Reporting Channels / / / ### Review Process / / / ### Escalation / / / ### Response Timelines / / / ### Non-Retaliation / / / ## 14. Information Security / / ### Passwords / / - Company passwords must be unique and must not be shared with another person, including IT support personnel. / / ### MFA
4. `support-faq.md`: # Support FAQ — Northwind Analytics / / **How do I reset my dashboard password?** / Use "Forgot password" on the login page; a reset link is emailed and is valid for 30 minutes. / / **What is the data refresh interval?** / Dashboards refresh every **15 minutes** on the Standard plan and every **1 minute** on Pro. / / **What does error ERR-4032 mean?** / ERR-4032 means the data source connection timed out. Retry after 60 seconds; if it persists, / check the source credentials in Settings > Connections. / / **How long is analytics data retained?** / Analytics data is retained for **13 months** on Standard and **36 months** on Pro.

**Reference:** Report a suspected security incident to security@northwind.example within 1 hour. The handbook says a suspected personal-data incident goes to the Security team within 4 hours.

**Answer:** If you suspect a security incident, you should report it to security@northwind.example within 1 hour [source: security-policy.md].

- verdict: 
- note: 

---

## trace j20

**Question:** How long can a standard performance improvement plan run?

**Context the system was shown:**

1. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. / - The company may periodically review this rule and communicate changes through official internal channels. / - A standard performance improvement plan may run for **60 days**, with documented checkpoints at approximately day 15, day 30, and day 45.
2. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. / - The company may periodically review this rule and communicate changes through official internal channels. / - The standard probation period is **6 months**, although the company may extend it once by up to 3 months based on documented performance or business circumstances.
3. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: 1. Annual leave: 24 days per calendar year; monthly accrual is 2 days. / 2. Sick leave: 12 days per calendar year. / 3. Casual leave: 6 days per calendar year. / 4. Hybrid remote work: up to 3 days per week for eligible employees. / 5. Core collaboration hours: 10:00 AM–4:00 PM IST. / 6. Confirmed employee notice period: 60 calendar days. / 7. Probation notice period: 30 calendar days. / 8. Standard probation: 6 months, extendable once by up to 3 months. / 9. Learning and certification budget: INR 30,000 per financial year. / 10. Expense claims: normally within 30 days. / 11. Personal-data incident reporting: within 4 hours of discovery. / 12. Performance improvement plan: standard duration 60 days. / 13. Annual company holiday calendar: 12 designated holidays.
4. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. / - The company may periodically review this rule and communicate changes through official internal channels. / - Approved business expenses should normally be submitted within **30 days** of the expense date.

**Reference:** A standard performance improvement plan may run for 60 days.

**Answer:** A standard performance improvement plan may run for **60 days** [source: Synthetic_HR_Policy_RAG_Test_Dataset.md].

- verdict: 
- note: 

---

## trace j21

**Question:** What approvals are required before accessing production data?

**Context the system was shown:**

1. `Nexora_Tech_Azure_Cloud_Data_Access_Policy.md`: Production data is classified as **Confidential** or **Restricted**, depending on its contents. / / Production database access requires: / / 1. Business justification. / 2. Appropriate Azure RBAC permissions. / 3. Approval from the relevant manager or data owner. / 4. Logging and monitoring. / 5. Periodic access review. / / Developers must not directly access Restricted production data unless specifically authorized. / / ## 7. Customer Data / / Customer information must only be accessible to employees whose responsibilities require it. / / Customer data must not be: / / - Downloaded to personal devices. / - Shared through personal email. / - Uploaded to unauthorized third-party services. / - Copied into development environments without approval. / - Included in application logs unnecessarily.
2. `Nexora_Tech_Azure_Cloud_Data_Access_Policy.md`: ### Developer / / Can: / / - Access development resources. / - Deploy applications to development. / - View development logs. / - Access development databases where required. / / Developers should not have unrestricted production data access. / / ### QA / Tester / / Can: / / - Access testing environments. / - Execute application tests. / - View test logs. / - Access approved test data. / / QA users cannot modify production resources. / / ### Data Analyst / / Can: / / - Read approved business datasets. / - Run approved queries. / - Generate reports. / / Data Analysts cannot modify production infrastructure. / / ### Security Administrator / / Can: / / - Review security configurations. / - Review access assignments. / - Investigate security alerts. / - Audit privileged access. / / Security administrators should use privileged access only when required.
3. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: - Requests should normally be submitted through the employee portal before the relevant date. Managers should consider business continuity, employee circumstances, and previously approved requests. / - Records must be accurate and should be updated when circumstances change. Employees must not knowingly submit false information or alter company records without authorization. / - Where approval is required, approval does not remove the employee's responsibility to follow other applicable company policies. / - People Operations may maintain supporting records for audit, compliance, payroll, or operational purposes. Access is limited according to role and business need.
4. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: - Requests should normally be submitted through the employee portal before the relevant date. Managers should consider business continuity, employee circumstances, and previously approved requests. / - Records must be accurate and should be updated when circumstances change. Employees must not knowingly submit false information or alter company records without authorization. / - Where approval is required, approval does not remove the employee's responsibility to follow other applicable company policies. / - People Operations may maintain supporting records for audit, compliance, payroll, or operational purposes. Access is limited according to role and business need.

**Reference:** Business justification, appropriate Azure RBAC permissions, approval from the relevant manager or data owner, logging and monitoring, and periodic access review.

**Answer:** Production database access requires approval from the relevant manager or data owner [source: Nexora_Tech_Azure_Cloud_Data_Access_Policy.md].

- verdict: 
- note: 

---

## trace j22

**Question:** How much can I claim for home-office equipment?

**Context the system was shown:**

1. `Northstar-Remote-Work-Policy-2026.md`: ## 4. Home-office expenses / / Employees may claim up to 50 USD per month for internet service used for approved remote work. Claims require an itemized receipt and must be submitted by the tenth day of the following month. / / ## 5. Review and cancellation / / Remote-work approvals are reviewed every six months. The company may suspend or cancel an arrangement when business needs, performance, security, or attendance requirements are not met.
2. `expenses.md`: # Expenses Policy / / ## Submitting / Submit expenses within **30 days** of purchase through the finance portal with a receipt. / Expenses over **$200** require pre-approval from your manager. / / ## Limits / - Meals while travelling: up to **$40 per day**. / - Home-office equipment: up to **$500 per year**. / - Client entertainment: up to **$150 per event**, itemised receipt required. / / Reimbursements are paid with the next monthly payroll run.
3. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. / - The company may periodically review this rule and communicate changes through official internal channels. / - Eligible employees may claim up to **INR 30,000 per financial year** for approved learning and certification expenses.
4. `Northstar-Remote-Work-Policy-2026.md`: # NORTHSTAR REMOTE WORK POLICY 2026 / / Effective date: 2026-02-15 / / ## 1. Scope and eligibility / / Regular employees may request remote work after completing 60 days of service. Approval depends on role suitability, team coverage, security requirements, and manager review. / / ## 2. Remote-work schedule / / An approved employee may work remotely up to three days per week. The employee must be available during the team core hours of 10:00 to 16:00 local time unless the manager approves an alternative schedule. / / ## 3. Equipment and security / / Northstar supplies one company laptop and an approved security token. Employees must use the company VPN for internal systems and must not store confidential policy or customer data on a personal device. / / ## 4. Home-office expenses

**Reference:** Home-office equipment is reimbursed up to $500 per year.

**Answer:** You can claim up to $500 per year for home-office equipment [source: expenses.md].

- verdict: 
- note: 

---

## trace j23

**Question:** What should I check in Settings > Connections?

**Context the system was shown:**

1. `support-faq.md`: # Support FAQ — Northwind Analytics / / **How do I reset my dashboard password?** / Use "Forgot password" on the login page; a reset link is emailed and is valid for 30 minutes. / / **What is the data refresh interval?** / Dashboards refresh every **15 minutes** on the Standard plan and every **1 minute** on Pro. / / **What does error ERR-4032 mean?** / ERR-4032 means the data source connection timed out. Retry after 60 seconds; if it persists, / check the source credentials in Settings > Connections. / / **How long is analytics data retained?** / Analytics data is retained for **13 months** on Standard and **36 months** on Pro.
2. `security-policy.md`: # Security Policy / / - All laptops must have full-disk encryption enabled. / - Passwords must be at least **12 characters** and are rotated every **90 days**. / - Multi-factor authentication (MFA) is required for all company accounts. / - Report a suspected security incident to security@northwind.example within **1 hour**. / - Customer data must never be copied to personal devices or personal cloud storage.
3. `Nexora_Tech_Azure_Cloud_Data_Access_Policy.md`: ### Developer / / Can: / / - Access development resources. / - Deploy applications to development. / - View development logs. / - Access development databases where required. / / Developers should not have unrestricted production data access. / / ### QA / Tester / / Can: / / - Access testing environments. / - Execute application tests. / - View test logs. / - Access approved test data. / / QA users cannot modify production resources. / / ### Data Analyst / / Can: / / - Read approved business datasets. / - Run approved queries. / - Generate reports. / / Data Analysts cannot modify production infrastructure. / / ### Security Administrator / / Can: / / - Review security configurations. / - Review access assignments. / - Investigate security alerts. / - Audit privileged access. / / Security administrators should use privileged access only when required.
4. `Nexora_Tech_Azure_Cloud_Data_Access_Policy.md`: - Azure access keys / - API keys / - Database passwords / - Client secrets / - Encryption keys / - Service credentials / / Secrets must be stored using an approved secrets-management solution such as **Azure Key Vault**. / / Access to secrets must be restricted to authorized applications and administrators. / / ## 10. Access Reviews / / Access to Confidential and Restricted resources must be reviewed periodically. / / Inactive accounts and unnecessary permissions must be removed. / / Privileged access should be minimized and, where appropriate, protected through Microsoft Entra Privileged Identity Management (PIM). / / ## 11. Logging and Monitoring / / Access to sensitive Azure resources must be logged. / / Security teams should monitor:

**Reference:** Check the source credentials in Settings > Connections.

**Answer:** You should check the source credentials in Settings > Connections if the error ERR-4032 persists [source: support-faq.md].

- verdict: 
- note: 

---

## trace j24

**Question:** How many sick leave days do employees get per year?

**Context the system was shown:**

1. `Synthetic_HR_Policy_RAG_Test_Dataset.md`: - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. / - The company may periodically review this rule and communicate changes through official internal channels. / - Employees receive **12 days of sick leave per calendar year**. A medical certificate may be requested for absences exceeding 2 consecutive working days.

**Reference:** 12 paid sick leave days per calendar year.

**Answer:** Employees receive 12 days of sick leave per calendar year [source: Synthetic_HR_Policy_RAG_Test_Dataset.md].

- verdict: 
- note: 

---


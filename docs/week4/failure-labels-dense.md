# Week 4 — failure labels (dense search)

Generated 2026-10-11T00:49:25 by `python scripts/diagnose_failures.py --mode dense --save`.

```
=== Failure diagnosis — mode=dense, k=4 ===
answer model: gemini-3.5-flash-lite · embeddings: local · dense search: exact · 32 cases
'*' marks a chunk from a document that legitimately answers the question.

[PASS] ERR-4032
    expected : support-faq.md
    fetched  : 4 chunk(s) at k=4
      * 1. support-faq.md       score=0.3644  via dense (dense#1)
          # Support FAQ — Northwind Analytics **How do I reset my dashboard password?** Use "Forgot password" on the login page; a reset link is emailed and is valid for…
        2. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.1772  via dense (dense#2)
          ### Emergency Leave Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and managers. The policy appli…
        3. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.1738  via dense (dense#3)
          ## 12. Anti-Harassment and POSH ### Prohibited Conduct Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for emplo…
        4. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.1737  via dense (dense#4)
          ### Emergency Response Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and managers. The policy ap…
    answered : Error ERR-4032 means that the data source connection timed out. You should retry after 60 seconds; if the error persists, check the source credentials in Settings > Connections [source: support-faq.md].
    grounded : True
    verdict  : Right document at rank 1, and the answer contains "timed out".

[RETRIEVAL] What is security@northwind.example used for?
    expected : security-policy.md
    fetched  : 4 chunk(s) at k=4
        1. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.4873  via dense (dense#1)
          ## 14. Information Security ### Passwords Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and mana…
        2. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.424   via dense (dense#2)
          ### Security Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and managers. The policy applies to e…
        3. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.424   via dense (dense#3)
          ### Security Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and managers. The policy applies to e…
        4. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.3943  via dense (dense#4)
          ### Phishing Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and managers. The policy applies to e…
    answered : I don't know based on the provided documents.
    grounded : False
    verdict  : Expected one of ['security-policy.md'] in the top 4, but got: Synthetic_HR_Policy_RAG_Test_Dataset.md, Synthetic_HR_Policy_RAG_Test_Dataset.md, Synthetic_HR_Policy_RAG_Test_Dataset.md, Synthetic_HR_Policy_RAG_Test_Dataset.md. The answer model never saw the right text, so this is a search problem. It answered: "I don't know based on the provided documents."

[PASS] What should I check in Settings > Connections?
    expected : support-faq.md
    fetched  : 4 chunk(s) at k=4
      * 1. support-faq.md       score=0.2465  via dense (dense#1)
          # Support FAQ — Northwind Analytics **How do I reset my dashboard password?** Use "Forgot password" on the login page; a reset link is emailed and is valid for…
        2. security-policy.md   score=0.1417  via dense (dense#2)
          # Security Policy - All laptops must have full-disk encryption enabled. - Passwords must be at least **12 characters** and are rotated every **90 days**. - Mul…
        3. Nexora_Tech_Azure_Cloud_Data_Access_Policy.md score=0.1373  via dense (dense#3)
          ### Developer Can: - Access development resources. - Deploy applications to development. - View development logs. - Access development databases where required…
        4. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.1135  via dense (dense#4)
          ## 14. Information Security ### Passwords Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and mana…
    answered : You should check the source credentials [source: support-faq.md].
    grounded : True
    verdict  : Right document at rank 1, and the answer contains "credentials".

[PASS] What is policy NEXORA-CLOUD-SEC-001 about?
    expected : Nexora_Tech_Azure_Cloud_Data_Access_Policy.md
    fetched  : 4 chunk(s) at k=4
      * 1. Nexora_Tech_Azure_Cloud_Data_Access_Policy.md score=0.6724  via dense (dense#1)
          # Nexora Tech — Azure Cloud Data Access & Security Policy **Policy ID:** NEXORA-CLOUD-SEC-001 **Version:** 1.0 **Effective Date:** January 1, 2026 **Policy Own…
      * 2. Nexora_Tech_Azure_Cloud_Data_Access_Policy.md score=0.5962  via dense (dense#2)
          ## 13. Policy Summary > **Nexora Tech employees and applications may access only the Azure resources and data required to perform their authorized responsibili…
      * 3. Nexora_Tech_Azure_Cloud_Data_Access_Policy.md score=0.5069  via dense (dense#3)
          ## 11. Logging and Monitoring Access to sensitive Azure resources must be logged. Security teams should monitor: - Failed authentication attempts. - Privileged…
      * 4. Nexora_Tech_Azure_Cloud_Data_Access_Policy.md score=0.4947  via dense (dense#4)
          ## 2. Data Classification Nexora Tech classifies cloud data into four levels: | Classification | Description | Examples | |---|---|---| | **Public** | Informat…
    answered : Policy NEXORA-CLOUD-SEC-001 is about how Nexora Tech manages access to data and cloud resources hosted on Microsoft Azure [source: Nexora_Tech_Azure_Cloud_Data_Access_Policy.md].
    grounded : True
    verdict  : Right document at rank 1, and the answer contains "azure".

[PASS] Is MFA mandatory?
    expected : security-policy.md, Synthetic_HR_Policy_RAG_Test_Dataset.md
    fetched  : 4 chunk(s) at k=4
      * 1. security-policy.md   score=0.5514  via dense (dense#1)
          # Security Policy - All laptops must have full-disk encryption enabled. - Passwords must be at least **12 characters** and are rotated every **90 days**. - Mul…
      * 2. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.5157  via dense (dense#2)
          ### MFA Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and managers. The policy applies to eligib…
      * 3. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.4259  via dense (dense#3)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
      * 4. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.3579  via dense (dense#4)
          ### Mandatory Training Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and managers. The policy ap…
    answered : Yes, multi-factor authentication (MFA) is required for all company accounts [source: security-policy.md], and it is mandatory for corporate email, source-code repositories, VPN access, and production administration tools [source: Synthetic_HR_Policy_RAG_Test_Dataset.md].
    grounded : True
    verdict  : Right document at rank 1, and the answer contains "required".

[PASS] What is PIM used for?
    expected : Nexora_Tech_Azure_Cloud_Data_Access_Policy.md
    fetched  : 4 chunk(s) at k=4
      * 1. Nexora_Tech_Azure_Cloud_Data_Access_Policy.md score=0.236   via dense (dense#1)
          - Azure access keys - API keys - Database passwords - Client secrets - Encryption keys - Service credentials Secrets must be stored using an approved secrets-m…
        2. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.1642  via dense (dense#2)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
        3. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.1575  via dense (dense#3)
          # Northstar Digital Solutions Pvt. Ltd. — Synthetic HR Policy Handbook **Document purpose:** Synthetic test data for RAG applications. **Version:** 2026.1 **Ef…
        4. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.1373  via dense (dense#4)
          ## 8. Benefits ### Health Benefits Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and managers. T…
    answered : PIM (Microsoft Entra Privileged Identity Management) is used to protect privileged access where appropriate, which should be minimized [source: Nexora_Tech_Azure_Cloud_Data_Access_Policy.md].
    grounded : True
    verdict  : Right document at rank 1, and the answer contains "privileged".

[PASS] Can I copy customer data onto my own USB stick?
    expected : security-policy.md, Northstar-Remote-Work-Policy-2026.md, Nexora_Tech_Azure_Cloud_Data_Access_Policy.md
    fetched  : 4 chunk(s) at k=4
      * 1. security-policy.md   score=0.289   via dense (dense#1)
          # Security Policy - All laptops must have full-disk encryption enabled. - Passwords must be at least **12 characters** and are rotated every **90 days**. - Mul…
        2. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.2803  via dense (dense#2)
          ## 15. Data Privacy ### Personal Data Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and managers…
      * 3. Northstar-Remote-Work-Policy-2026.md score=0.2421  via dense (dense#3)
          ## 4. Home-office expenses Employees may claim up to 50 USD per month for internet service used for approved remote work. Claims require an itemized receipt an…
      * 4. Nexora_Tech_Azure_Cloud_Data_Access_Policy.md score=0.2041  via dense (dense#4)
          Production data is classified as **Confidential** or **Restricted**, depending on its contents. Production database access requires: 1. Business justification.…
    answered : No, you cannot copy customer data onto your own USB stick. Customer data must never be copied to personal devices [source: security-policy.md], and customer data must not be downloaded to personal devices [source: Nexora_Tech_Azure_Cloud_Data_Access_Policy.md].
    grounded : True
    verdict  : Right document at rank 1, and the answer contains "never".

[PASS] Who do I tell if I think we have been hacked?
    expected : security-policy.md, Synthetic_HR_Policy_RAG_Test_Dataset.md
    fetched  : 4 chunk(s) at k=4
      * 1. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.3156  via dense (dense#1)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
      * 2. security-policy.md   score=0.2425  via dense (dense#2)
          # Security Policy - All laptops must have full-disk encryption enabled. - Passwords must be at least **12 characters** and are rotated every **90 days**. - Mul…
      * 3. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.2421  via dense (dense#3)
          ## 14. Information Security ### Passwords Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and mana…
      * 4. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.242   via dense (dense#4)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
    answered : Based on the provided documents, you should report a suspected security incident to the Security team within 4 hours of discovery [source: Synthetic_HR_Policy_RAG_Test_Dataset.md], or report a suspected security incident to security@northwind.example within 1 hour [source: security-policy.md].
    grounded : True
    verdict  : Right document at rank 1, and the answer contains "security@northwind.example".

[PASS] How long do I have to hand in a receipt after buying something?
    expected : expenses.md, Synthetic_HR_Policy_RAG_Test_Dataset.md
    fetched  : 4 chunk(s) at k=4
      * 1. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.403   via dense (dense#1)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
      * 2. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.3917  via dense (dense#2)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
      * 3. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.3673  via dense (dense#3)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
        4. Acme-Employment-Terms-2026.md score=0.3112  via dense (dense#4)
          ## 4. Company-initiated termination For a company-initiated termination without cause, Acme will provide 30 calendar days of notice or pay in lieu of notice, s…
    answered : Approved business expenses should normally be submitted within **30 days** of the expense date [source: Synthetic_HR_Policy_RAG_Test_Dataset.md].
    grounded : True
    verdict  : Right document at rank 1, and the answer contains "30 days".

[PASS] How long until my retirement contributions start?
    expected : benefits.md
    fetched  : 4 chunk(s) at k=4
        1. Acme-Leave-Policy-2026.md score=0.285   via dense (dense#1)
          # ACME LEAVE POLICY 2026 Effective date: 2026-01-01 ## 1. Eligibility All regular full-time employees become eligible for the annual leave allowance after comp…
        2. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.2735  via dense (dense#2)
          1. Annual leave: 24 days per calendar year; monthly accrual is 2 days. 2. Sick leave: 12 days per calendar year. 3. Casual leave: 6 days per calendar year. 4. …
      * 3. benefits.md          score=0.2572  via dense (dense#3)
          # Benefits Northwind Labs offers: - Private health insurance (employee covered 100%; dependents at 50%). - A pension match of **5%** of base salary. - An annua…
        4. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.2561  via dense (dense#4)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
    answered : The pension match starts after 3 months of employment [source: benefits.md].
    grounded : True
    verdict  : Right document at rank 3, and the answer contains "3 months".

[PASS] How much can I claim for home-office equipment?
    expected : expenses.md
    fetched  : 4 chunk(s) at k=4
        1. Northstar-Remote-Work-Policy-2026.md score=0.6439  via dense (dense#1)
          ## 4. Home-office expenses Employees may claim up to 50 USD per month for internet service used for approved remote work. Claims require an itemized receipt an…
      * 2. expenses.md          score=0.5049  via dense (dense#2)
          # Expenses Policy ## Submitting Submit expenses within **30 days** of purchase through the finance portal with a receipt. Expenses over **$200** require pre-ap…
        3. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.4095  via dense (dense#3)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
        4. Northstar-Remote-Work-Policy-2026.md score=0.308   via dense (dense#4)
          # NORTHSTAR REMOTE WORK POLICY 2026 Effective date: 2026-02-15 ## 1. Scope and eligibility Regular employees may request remote work after completing 60 days o…
    answered : You can claim up to $500 per year for home-office equipment [source: expenses.md].
    grounded : True
    verdict  : Right document at rank 2, and the answer contains "$500".

[PASS] How many annual leave days do full-time employees get?
    expected : Acme-Leave-Policy-2026.md, Synthetic_HR_Policy_RAG_Test_Dataset.md, benefits.md
    fetched  : 4 chunk(s) at k=4
      * 1. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.7642  via dense (dense#1)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
      * 2. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.6761  via dense (dense#2)
          1. Annual leave: 24 days per calendar year; monthly accrual is 2 days. 2. Sick leave: 12 days per calendar year. 3. Casual leave: 6 days per calendar year. 4. …
      * 3. Acme-Leave-Policy-2026.md score=0.6436  via dense (dense#3)
          # ACME LEAVE POLICY 2026 Effective date: 2026-01-01 ## 1. Eligibility All regular full-time employees become eligible for the annual leave allowance after comp…
      * 4. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.5957  via dense (dense#4)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
    answered : Based on the provided documents, full-time employees receive 24 days of annual leave per calendar year [source: Synthetic_HR_Policy_RAG_Test_Dataset.md], while regular full-time employees under the Acme Leave Policy receive 18 days of annual leave per calendar year [source: Acme-Leave-Policy-2026.md].
    grounded : True
    verdict  : Right document at rank 1, and the answer contains "18".

[PASS] How many days of notice must a confirmed or permanent employee give before resigning?
    expected : Acme-Employment-Terms-2026.md, Synthetic_HR_Policy_RAG_Test_Dataset.md
    fetched  : 4 chunk(s) at k=4
      * 1. Acme-Employment-Terms-2026.md score=0.5988  via dense (dense#1)
          # ACME EMPLOYMENT TERMS POLICY 2026 Effective date: 2026-03-01 ## 1. Scope This policy applies to regular full-time Acme employees. A separate written agreemen…
      * 2. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.5909  via dense (dense#2)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
      * 3. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.5403  via dense (dense#3)
          1. Annual leave: 24 days per calendar year; monthly accrual is 2 days. 2. Sick leave: 12 days per calendar year. 3. Casual leave: 6 days per calendar year. 4. …
      * 4. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.5306  via dense (dense#4)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
    answered : Based on the provided documents, the notice period required for a permanent or confirmed employee before resigning depends on the specific policy document referenced:

* According to the Acme Employment Terms Policy 2026, a permanent employee must provide **30 calendar days** of written notice [source: Acme-Employment-Terms-2026.md].
* According to the Synthetic HR Policy RAG Test Dataset, the standard notice period is **60 calendar days** for confirmed employees [source: Synthetic_HR_Policy_RAG_Test_Dataset.md].
    grounded : True
    verdict  : Right document at rank 1, and the answer contains "30".

[PASS] What is the annual learning and certification budget per employee?
    expected : Synthetic_HR_Policy_RAG_Test_Dataset.md, benefits.md
    fetched  : 4 chunk(s) at k=4
      * 1. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.6203  via dense (dense#1)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
      * 2. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.4078  via dense (dense#2)
          1. Annual leave: 24 days per calendar year; monthly accrual is 2 days. 2. Sick leave: 12 days per calendar year. 3. Casual leave: 6 days per calendar year. 4. …
      * 3. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.3878  via dense (dense#3)
          13. Annual company holiday calendar: 12 designated holidays. 14. Payroll: normally processed on the last working day of the month. 15. Annual mandatory securit…
      * 4. benefits.md          score=0.3834  via dense (dense#4)
          # Benefits Northwind Labs offers: - Private health insurance (employee covered 100%; dependents at 50%). - A pension match of **5%** of base salary. - An annua…
    answered : Based on the provided documents, the learning and certification budget is INR 30,000 per financial year [source: Synthetic_HR_Policy_RAG_Test_Dataset.md], and the annual learning budget is $1,000 per employee [source: benefits.md].
    grounded : True
    verdict  : Right document at rank 1, and the answer contains "30,000".

[PASS] How many sick leave days do employees get per year?
    expected : Acme-Leave-Policy-2026.md, Synthetic_HR_Policy_RAG_Test_Dataset.md
    fetched  : 4 chunk(s) at k=4
      * 1. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.7484  via dense (dense#1)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
      * 2. Acme-Leave-Policy-2026.md score=0.6454  via dense (dense#2)
          # ACME LEAVE POLICY 2026 Effective date: 2026-01-01 ## 1. Eligibility All regular full-time employees become eligible for the annual leave allowance after comp…
      * 3. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.6109  via dense (dense#3)
          1. Annual leave: 24 days per calendar year; monthly accrual is 2 days. 2. Sick leave: 12 days per calendar year. 3. Casual leave: 6 days per calendar year. 4. …
      * 4. Acme-Leave-Policy-2026.md score=0.6007  via dense (dense#4)
          ## 4. Sick leave Employees receive 12 paid sick-leave days per calendar year. A medical certificate may be requested for an absence longer than three consecuti…
    answered : Employees receive 12 days of sick leave per calendar year [source: Synthetic_HR_Policy_RAG_Test_Dataset.md] (or 12 paid sick-leave days per calendar year according to Acme-Leave-Policy-2026.md [source: Acme-Leave-Policy-2026.md]).
    grounded : True
    verdict  : Right document at rank 1, and the answer contains "12".

[PASS] Can I carry forward all of my unused annual leave days into next year?
    expected : Acme-Leave-Policy-2026.md
    fetched  : 4 chunk(s) at k=4
      * 1. Acme-Leave-Policy-2026.md score=0.6229  via dense (dense#1)
          # ACME LEAVE POLICY 2026 Effective date: 2026-01-01 ## 1. Eligibility All regular full-time employees become eligible for the annual leave allowance after comp…
        2. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.6062  via dense (dense#2)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
        3. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.5109  via dense (dense#3)
          1. Annual leave: 24 days per calendar year; monthly accrual is 2 days. 2. Sick leave: 12 days per calendar year. 3. Casual leave: 6 days per calendar year. 4. …
        4. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.4817  via dense (dense#4)
          13. Annual company holiday calendar: 12 designated holidays. 14. Payroll: normally processed on the last working day of the month. 15. Annual mandatory securit…
    answered : No, employees may carry forward up to 10 unused annual-leave days into the next calendar year, and days above the 10-day limit expire on 31 March unless a written exception is approved by People Operations [source: Acme-Leave-Policy-2026.md].
    grounded : True
    verdict  : Right document at rank 1, and the answer contains "10".

[PASS] When do unused leave days above the carry-forward limit expire?
    expected : Acme-Leave-Policy-2026.md
    fetched  : 4 chunk(s) at k=4
      * 1. Acme-Leave-Policy-2026.md score=0.5911  via dense (dense#1)
          # ACME LEAVE POLICY 2026 Effective date: 2026-01-01 ## 1. Eligibility All regular full-time employees become eligible for the annual leave allowance after comp…
        2. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.5262  via dense (dense#2)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
        3. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.5002  via dense (dense#3)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
        4. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.4961  via dense (dense#4)
          1. Annual leave: 24 days per calendar year; monthly accrual is 2 days. 2. Sick leave: 12 days per calendar year. 3. Casual leave: 6 days per calendar year. 4. …
    answered : Unused annual-leave days above the 10-day limit expire on 31 March unless a written exception is approved by People Operations.

[source: Acme-Leave-Policy-2026.md]
    grounded : True
    verdict  : Right document at rank 1, and the answer contains "31 march".

[PASS] How many weeks of paid parental leave are available?
    expected : Acme-Leave-Policy-2026.md
    fetched  : 4 chunk(s) at k=4
      * 1. Acme-Leave-Policy-2026.md score=0.7227  via dense (dense#1)
          ## 4. Sick leave Employees receive 12 paid sick-leave days per calendar year. A medical certificate may be requested for an absence longer than three consecuti…
        2. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.607   via dense (dense#2)
          1. Annual leave: 24 days per calendar year; monthly accrual is 2 days. 2. Sick leave: 12 days per calendar year. 3. Casual leave: 6 days per calendar year. 4. …
        3. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.5874  via dense (dense#3)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
      * 4. Acme-Leave-Policy-2026.md score=0.5793  via dense (dense#4)
          # ACME LEAVE POLICY 2026 Effective date: 2026-01-01 ## 1. Eligibility All regular full-time employees become eligible for the annual leave allowance after comp…
    answered : Eligible employees may take 16 weeks of paid parental leave after the birth or adoption of a child [source: Acme-Leave-Policy-2026.md].
    grounded : True
    verdict  : Right document at rank 1, and the answer contains "16 weeks".

[PASS] Under the Acme employment terms, how many days of written notice must a permanent employee give?
    expected : Acme-Employment-Terms-2026.md
    fetched  : 4 chunk(s) at k=4
      * 1. Acme-Employment-Terms-2026.md score=0.7649  via dense (dense#1)
          # ACME EMPLOYMENT TERMS POLICY 2026 Effective date: 2026-03-01 ## 1. Scope This policy applies to regular full-time Acme employees. A separate written agreemen…
        2. Acme-Leave-Policy-2026.md score=0.6899  via dense (dense#2)
          # ACME LEAVE POLICY 2026 Effective date: 2026-01-01 ## 1. Eligibility All regular full-time employees become eligible for the annual leave allowance after comp…
      * 3. Acme-Employment-Terms-2026.md score=0.6343  via dense (dense#3)
          ## 4. Company-initiated termination For a company-initiated termination without cause, Acme will provide 30 calendar days of notice or pay in lieu of notice, s…
        4. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.5924  via dense (dense#4)
          1. Annual leave: 24 days per calendar year; monthly accrual is 2 days. 2. Sick leave: 12 days per calendar year. 3. Casual leave: 6 days per calendar year. 4. …
    answered : Under the Acme employment terms, a permanent employee must provide 30 calendar days of written notice before resigning [source: Acme-Employment-Terms-2026.md].
    grounded : True
    verdict  : Right document at rank 1, and the answer contains "30".

[PASS] After how many days of service may an employee request remote work?
    expected : Northstar-Remote-Work-Policy-2026.md
    fetched  : 4 chunk(s) at k=4
      * 1. Northstar-Remote-Work-Policy-2026.md score=0.6927  via dense (dense#1)
          # NORTHSTAR REMOTE WORK POLICY 2026 Effective date: 2026-02-15 ## 1. Scope and eligibility Regular employees may request remote work after completing 60 days o…
        2. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.5942  via dense (dense#2)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
      * 3. Northstar-Remote-Work-Policy-2026.md score=0.5344  via dense (dense#3)
          ## 4. Home-office expenses Employees may claim up to 50 USD per month for internet service used for approved remote work. Claims require an itemized receipt an…
        4. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.5014  via dense (dense#4)
          1. Annual leave: 24 days per calendar year; monthly accrual is 2 days. 2. Sick leave: 12 days per calendar year. 3. Casual leave: 6 days per calendar year. 4. …
    answered : An employee may request remote work after completing 60 days of service [source: Northstar-Remote-Work-Policy-2026.md].
    grounded : True
    verdict  : Right document at rank 1, and the answer contains "60".

[PASS] How much can I claim each month for internet used for remote work?
    expected : Northstar-Remote-Work-Policy-2026.md
    fetched  : 4 chunk(s) at k=4
      * 1. Northstar-Remote-Work-Policy-2026.md score=0.7843  via dense (dense#1)
          ## 4. Home-office expenses Employees may claim up to 50 USD per month for internet service used for approved remote work. Claims require an itemized receipt an…
      * 2. Northstar-Remote-Work-Policy-2026.md score=0.4906  via dense (dense#2)
          # NORTHSTAR REMOTE WORK POLICY 2026 Effective date: 2026-02-15 ## 1. Scope and eligibility Regular employees may request remote work after completing 60 days o…
        3. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.4425  via dense (dense#3)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
        4. expenses.md          score=0.4315  via dense (dense#4)
          # Expenses Policy ## Submitting Submit expenses within **30 days** of purchase through the finance portal with a receipt. Expenses over **$200** require pre-ap…
    answered : Employees may claim up to 50 USD per month for internet service used for approved remote work [source: Northstar-Remote-Work-Policy-2026.md].
    grounded : True
    verdict  : Right document at rank 1, and the answer contains "50".

[PASS] What are the four data classification levels?
    expected : Nexora_Tech_Azure_Cloud_Data_Access_Policy.md
    fetched  : 4 chunk(s) at k=4
      * 1. Nexora_Tech_Azure_Cloud_Data_Access_Policy.md score=0.5065  via dense (dense#1)
          ## 2. Data Classification Nexora Tech classifies cloud data into four levels: | Classification | Description | Examples | |---|---|---| | **Public** | Informat…
      * 2. Nexora_Tech_Azure_Cloud_Data_Access_Policy.md score=0.3987  via dense (dense#2)
          # Nexora Tech — Azure Cloud Data Access & Security Policy **Policy ID:** NEXORA-CLOUD-SEC-001 **Version:** 1.0 **Effective Date:** January 1, 2026 **Policy Own…
        3. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.254   via dense (dense#3)
          # Northstar Digital Solutions Pvt. Ltd. — Synthetic HR Policy Handbook **Document purpose:** Synthetic test data for RAG applications. **Version:** 2026.1 **Ef…
      * 4. Nexora_Tech_Azure_Cloud_Data_Access_Policy.md score=0.2407  via dense (dense#4)
          ### Developer Can: - Access development resources. - Deploy applications to development. - View development logs. - Access development databases where required…
    answered : The four data classification levels are:
1. Public
2. Internal
3. Confidential
4. Restricted

[source: Nexora_Tech_Azure_Cloud_Data_Access_Policy.md]
    grounded : True
    verdict  : Right document at rank 1, and the answer contains "restricted".

[PASS] Where should Azure access keys and database passwords be stored?
    expected : Nexora_Tech_Azure_Cloud_Data_Access_Policy.md
    fetched  : 4 chunk(s) at k=4
      * 1. Nexora_Tech_Azure_Cloud_Data_Access_Policy.md score=0.751   via dense (dense#1)
          - Azure access keys - API keys - Database passwords - Client secrets - Encryption keys - Service credentials Secrets must be stored using an approved secrets-m…
      * 2. Nexora_Tech_Azure_Cloud_Data_Access_Policy.md score=0.7331  via dense (dense#2)
          Applications processing customer information should use managed identities or other approved identity mechanisms instead of storing long-lived credentials in s…
      * 3. Nexora_Tech_Azure_Cloud_Data_Access_Policy.md score=0.5568  via dense (dense#3)
          Security administrators should use privileged access only when required. ## 5. Least-Privilege Requirement Every user, application, service principal, and mana…
      * 4. Nexora_Tech_Azure_Cloud_Data_Access_Policy.md score=0.5188  via dense (dense#4)
          Nexora Tech maintains three primary Azure environments: - Development - Testing - Production Production resources must not be used for development or testing u…
    answered : Azure access keys and database passwords must be stored using an approved secrets-management solution such as **Azure Key Vault**, and they must never be stored directly in source code [source: Nexora_Tech_Azure_Cloud_Data_Access_Policy.md].
    grounded : True
    verdict  : Right document at rank 1, and the answer contains "key vault".

[PASS] What is the standard probation period?
    expected : Synthetic_HR_Policy_RAG_Test_Dataset.md
    fetched  : 4 chunk(s) at k=4
      * 1. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.7656  via dense (dense#1)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
      * 2. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.6619  via dense (dense#2)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
      * 3. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.5473  via dense (dense#3)
          1. Annual leave: 24 days per calendar year; monthly accrual is 2 days. 2. Sick leave: 12 days per calendar year. 3. Casual leave: 6 days per calendar year. 4. …
        4. Acme-Employment-Terms-2026.md score=0.5285  via dense (dense#4)
          # ACME EMPLOYMENT TERMS POLICY 2026 Effective date: 2026-03-01 ## 1. Scope This policy applies to regular full-time Acme employees. A separate written agreemen…
    answered : The standard probation period is 6 months [source: Synthetic_HR_Policy_RAG_Test_Dataset.md].
    grounded : True
    verdict  : Right document at rank 1, and the answer contains "6 months".

[PASS] How many days of casual leave do employees get per year?
    expected : Synthetic_HR_Policy_RAG_Test_Dataset.md
    fetched  : 4 chunk(s) at k=4
      * 1. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.7495  via dense (dense#1)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
      * 2. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.7017  via dense (dense#2)
          1. Annual leave: 24 days per calendar year; monthly accrual is 2 days. 2. Sick leave: 12 days per calendar year. 3. Casual leave: 6 days per calendar year. 4. …
      * 3. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.6883  via dense (dense#3)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
        4. Acme-Leave-Policy-2026.md score=0.6656  via dense (dense#4)
          # ACME LEAVE POLICY 2026 Effective date: 2026-01-01 ## 1. Eligibility All regular full-time employees become eligible for the annual leave allowance after comp…
    answered : Employees receive 6 days of casual leave per calendar year [source: Synthetic_HR_Policy_RAG_Test_Dataset.md].
    grounded : True
    verdict  : Right document at rank 1, and the answer contains "6 days".

[PASS] How many designated company holidays does the company publish each year?
    expected : Synthetic_HR_Policy_RAG_Test_Dataset.md
    fetched  : 4 chunk(s) at k=4
      * 1. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.6676  via dense (dense#1)
          13. Annual company holiday calendar: 12 designated holidays. 14. Payroll: normally processed on the last working day of the month. 15. Annual mandatory securit…
      * 2. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.661   via dense (dense#2)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
      * 3. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.3858  via dense (dense#3)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
      * 4. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.3838  via dense (dense#4)
          1. Annual leave: 24 days per calendar year; monthly accrual is 2 days. 2. Sick leave: 12 days per calendar year. 3. Casual leave: 6 days per calendar year. 4. …
    answered : The company publishes an annual holiday calendar with 12 designated company holidays [source: Synthetic_HR_Policy_RAG_Test_Dataset.md].
    grounded : True
    verdict  : Right document at rank 1, and the answer contains "12".

[PASS] Within how many hours must a suspected personal-data incident be reported to the Security team?
    expected : Synthetic_HR_Policy_RAG_Test_Dataset.md
    fetched  : 4 chunk(s) at k=4
      * 1. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.801   via dense (dense#1)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
      * 2. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.4269  via dense (dense#2)
          ## 15. Data Privacy ### Personal Data Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and managers…
      * 3. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.4158  via dense (dense#3)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
      * 4. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.4091  via dense (dense#4)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
    answered : A suspected personal-data incident must be reported to the Security team within 4 hours of discovery [source: Synthetic_HR_Policy_RAG_Test_Dataset.md].
    grounded : True
    verdict  : Right document at rank 1, and the answer contains "4 hours".

[PASS] How long can a standard performance improvement plan run?
    expected : Synthetic_HR_Policy_RAG_Test_Dataset.md
    fetched  : 4 chunk(s) at k=4
      * 1. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.7633  via dense (dense#1)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
      * 2. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.4752  via dense (dense#2)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
      * 3. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.3727  via dense (dense#3)
          1. Annual leave: 24 days per calendar year; monthly accrual is 2 days. 2. Sick leave: 12 days per calendar year. 3. Casual leave: 6 days per calendar year. 4. …
      * 4. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.3589  via dense (dense#4)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
    answered : A standard performance improvement plan can run for 60 days [source: Synthetic_HR_Policy_RAG_Test_Dataset.md].
    grounded : True
    verdict  : Right document at rank 1, and the answer contains "60 days".

[PASS] Is there an annual bonus scheme?
    expected : (nothing — must refuse)
    fetched  : 4 chunk(s) at k=4
        1. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.3419  via dense (dense#1)
          13. Annual company holiday calendar: 12 designated holidays. 14. Payroll: normally processed on the last working day of the month. 15. Annual mandatory securit…
        2. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.3133  via dense (dense#2)
          ## 7. Compensation and Payroll ### Salary Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and mana…
        3. Acme-Leave-Policy-2026.md score=0.3127  via dense (dense#3)
          # ACME LEAVE POLICY 2026 Effective date: 2026-01-01 ## 1. Eligibility All regular full-time employees become eligible for the annual leave allowance after comp…
        4. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.3106  via dense (dense#4)
          - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company …
    answered : I don't know based on the provided documents.
    grounded : False
    verdict  : Not in the corpus, and the app correctly said it does not know.

[PASS] What is the dress code?
    expected : (nothing — must refuse)
    fetched  : 4 chunk(s) at k=4
        1. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.3089  via dense (dense#1)
          ## 11. Code of Conduct ### Professional Behavior Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees a…
        2. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.2223  via dense (dense#2)
          ## 14. Information Security ### Passwords Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and mana…
        3. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.211   via dense (dense#3)
          ### Sexual Harassment Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and managers. The policy app…
        4. Synthetic_HR_Policy_RAG_Test_Dataset.md score=0.2073  via dense (dense#4)
          ### MFA Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and managers. The policy applies to eligib…
    answered : I don't know based on the provided documents.
    grounded : False
    verdict  : Not in the corpus, and the app correctly said it does not know.

[PASS] What is Nexora Tech's Azure subscription ID?
    expected : (nothing — must refuse)
    fetched  : 4 chunk(s) at k=4
        1. Nexora_Tech_Azure_Cloud_Data_Access_Policy.md score=0.6493  via dense (dense#1)
          ## 13. Policy Summary > **Nexora Tech employees and applications may access only the Azure resources and data required to perform their authorized responsibili…
        2. Nexora_Tech_Azure_Cloud_Data_Access_Policy.md score=0.6101  via dense (dense#2)
          # Nexora Tech — Azure Cloud Data Access & Security Policy **Policy ID:** NEXORA-CLOUD-SEC-001 **Version:** 1.0 **Effective Date:** January 1, 2026 **Policy Own…
        3. Nexora_Tech_Azure_Cloud_Data_Access_Policy.md score=0.5197  via dense (dense#3)
          ## 11. Logging and Monitoring Access to sensitive Azure resources must be logged. Security teams should monitor: - Failed authentication attempts. - Privileged…
        4. Nexora_Tech_Azure_Cloud_Data_Access_Policy.md score=0.4973  via dense (dense#4)
          Nexora Tech maintains three primary Azure environments: - Development - Testing - Production Production resources must not be used for development or testing u…
    answered : I don't know based on the provided documents.
    grounded : False
    verdict  : Not in the corpus, and the app correctly said it does not know.

[PASS] What is the maximum number of Azure administrators allowed at Nexora Tech?
    expected : (nothing — must refuse)
    fetched  : 4 chunk(s) at k=4
        1. Nexora_Tech_Azure_Cloud_Data_Access_Policy.md score=0.6944  via dense (dense#1)
          ## 13. Policy Summary > **Nexora Tech employees and applications may access only the Azure resources and data required to perform their authorized responsibili…
        2. Nexora_Tech_Azure_Cloud_Data_Access_Policy.md score=0.6634  via dense (dense#2)
          Nexora Tech maintains three primary Azure environments: - Development - Testing - Production Production resources must not be used for development or testing u…
        3. Nexora_Tech_Azure_Cloud_Data_Access_Policy.md score=0.5789  via dense (dense#3)
          Security administrators should use privileged access only when required. ## 5. Least-Privilege Requirement Every user, application, service principal, and mana…
        4. Nexora_Tech_Azure_Cloud_Data_Access_Policy.md score=0.5679  via dense (dense#4)
          ## 11. Logging and Monitoring Access to sensitive Azure resources must be logged. Security teams should monitor: - Failed authentication attempts. - Privileged…
    answered : I don't know based on the provided documents.
    grounded : False
    verdict  : Not in the corpus, and the app correctly said it does not know.

--- summary ---
  PASS         31
  RETRIEVAL    1

RETRIEVAL failures need a better search. GENERATION failures need a better prompt or better chunks. A smarter answer model fixes only the second kind.
```

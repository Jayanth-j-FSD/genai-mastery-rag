# Week 3 — chunk-size experiment output (generated)

Generated 2026-10-11T00:36:24 by `python scripts/compare_chunks.py --save`. Numbers only: the written observation (mentor check #4) is yours to write.

```
=== Chunk-size comparison (mentor check #4) ===
settings: top_k=4, dense search = exact, embeddings = local

chunk_size=800, overlap=120  (432 chunks total)  expected source found: 9/9
  [OK rank 1] top=0.812  Acme-Leave-Policy-2026.md                      How many annual leave days does the Acme leave policy give full-time employees?
  [OK rank 1] top=0.821  Acme-Leave-Policy-2026.md                      How many unused leave days can be carried forward under the Acme leave policy?
  [OK rank 1] top=0.693  Northstar-Remote-Work-Policy-2026.md           After how many days of service may an employee request remote work?
  [OK rank 1] top=0.373  benefits.md                                    What is the pension match?
  [OK rank 1] top=0.371  support-faq.md                                 What does error ERR-4032 mean?
  [OK rank 2] top=0.404  security-policy.md                             How often must passwords be rotated?
  [OK rank 1] top=0.765  Acme-Employment-Terms-2026.md                  Under the Acme employment terms, how many days of written notice must a permanent employee give?
  [OK rank 1] top=0.506  Nexora_Tech_Azure_Cloud_Data_Access_Policy.md  What are the four data classification levels?
  [OK rank 1] top=0.766  Synthetic_HR_Policy_RAG_Test_Dataset.md        What is the standard probation period?

chunk_size=400, overlap=60  (894 chunks total)  expected source found: 9/9
  [OK rank 1] top=0.801  Acme-Leave-Policy-2026.md                      How many annual leave days does the Acme leave policy give full-time employees?
  [OK rank 1] top=0.765  Acme-Leave-Policy-2026.md                      How many unused leave days can be carried forward under the Acme leave policy?
  [OK rank 1] top=0.761  Northstar-Remote-Work-Policy-2026.md           After how many days of service may an employee request remote work?
  [OK rank 1] top=0.373  benefits.md                                    What is the pension match?
  [OK rank 1] top=0.536  support-faq.md                                 What does error ERR-4032 mean?
  [OK rank 3] top=0.405  security-policy.md                             How often must passwords be rotated?
  [OK rank 1] top=0.731  Acme-Employment-Terms-2026.md                  Under the Acme employment terms, how many days of written notice must a permanent employee give?
  [OK rank 1] top=0.547  Nexora_Tech_Azure_Cloud_Data_Access_Policy.md  What are the four data classification levels?
  [OK rank 1] top=0.839  Synthetic_HR_Policy_RAG_Test_Dataset.md        What is the standard probation period?

Index restored to your .env config (chunk_size=800, overlap=120).
What changed between the two sizes, in words, is yours to write: see tests/questions.md.
```

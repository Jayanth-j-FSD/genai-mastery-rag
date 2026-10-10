# Week 4 — retrieval evaluation output

Generated 2026-10-11T00:34:37 by `python scripts/eval_retrieval.py --save`.

```
=== Retrieval quality: dense (Week 3) vs hybrid (Week 4) ===
corpus questions measured: 28   (refusal-only cases excluded — they have no expected document)
settings: top_k=4, hybrid_candidates=10, rrf_k=60, chunk_size=800

metric             dense    hybrid    change
hit-rate@1         25/28     24/28     -3.6%
hit-rate@3         27/28     27/28     +0.0%   <- the mentor's number
hit-rate@5         27/28     27/28     +0.0%
MRR                0.923     0.911    -0.012
(MRR is over the top 5 retrieved, not capped at k=3.)

--- per question, at k=3 (rank of the first acceptable document; '-' = not in the top 3) ---
case                          dense  hybrid   verdict
code-err4032                      1       1   both found
exact-security-email              -       2   FIXED
exact-settings-path               1       1   both found
exact-policy-id                   1       1   both found
acronym-mfa                       1       1   both found
acronym-pim                       1       1   both found
paraphrase-usb                    1       1   both found
paraphrase-hacked                 1       1   both found
paraphrase-receipt-window         1       2   both found
paraphrase-retirement             3       -   REGRESSED
ambiguous-home-office             2       2   both found
ambiguous-leave-days              1       1   both found
ambiguous-notice-period           1       1   both found
ambiguous-learning-budget         1       1   both found
detail-sick-days                  1       1   both found
negative-carryover-limit          1       1   both found
detail-carryover-expiry           1       1   both found
detail-parental-leave             1       1   both found
detail-notice-acme                1       1   both found
track-remote-eligibility          1       1   both found
track-internet-claim              1       1   both found
track-nexora-classification       1       1   both found
track-nexora-key-vault            1       1   both found
handbook-probation                1       1   both found
handbook-casual-leave             1       1   both found
handbook-holidays                 1       1   both found
handbook-breach-hours             1       1   both found
handbook-pip                      1       1   both found

FIXED by the change: 1
  - exact-security-email: What is security@northwind.example used for?
      expected ['security-policy.md'], hybrid fetched ['Synthetic_HR_Policy_RAG_Test_Dataset.md', 'security-policy.md', 'Synthetic_HR_Policy_RAG_Test_Dataset.md']

NOT fixed by the change (still broken): 0

BROKEN by the change (a regression): 1
  - paraphrase-retirement: How long until my retirement contributions start?
      expected ['benefits.md'], hybrid fetched ['Synthetic_HR_Policy_RAG_Test_Dataset.md', 'Acme-Leave-Policy-2026.md', 'support-faq.md']

--- predictions from eval_set.py ---
  code-err4032                 predicted keyword  -> wrong — dense already found it
  exact-security-email         predicted keyword  -> held — keyword search rescued it
  exact-settings-path          predicted keyword  -> wrong — dense already found it
  exact-policy-id              predicted keyword  -> wrong — dense already found it
  acronym-mfa                  predicted keyword  -> wrong — dense already found it
  acronym-pim                  predicted keyword  -> wrong — dense already found it
  paraphrase-usb               predicted dense    -> held — dense found it and hybrid kept it
  paraphrase-hacked            predicted dense    -> held — dense found it and hybrid kept it
  paraphrase-receipt-window    predicted dense    -> held — dense found it and hybrid kept it
  paraphrase-retirement        predicted dense    -> held for dense, but hybrid lost it

Note on the metric: hit-rate@k is 'did an acceptable document appear in the top k'. Two cases list two documents, either of which is a correct source, so one of them appearing is a hit. Recall@k is not reported separately because with one relevant document per question it is the same number.
```

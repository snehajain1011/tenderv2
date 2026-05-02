# Tender Eligibility Evaluation Report

## Criteria

| ID | Category | Mandatory | Description | Threshold | Evidence Expected |
| --- | --- | --- | --- | --- | --- |
| C1 | financial | Yes | Average annual turnover must meet the tender threshold. | INR 1 crore | CA certificate, audited balance sheet, turnover certificate |
| C2 | compliance | Yes | Bidder must have valid GST registration. |  | GST registration certificate |
| C3 | compliance | Yes | Bidder must hold valid ISO 9001 certification. |  | ISO 9001 certificate |
| C4 | technical | Yes | Bidder must show at least 3 similar completed projects in the last 5 years. | 3 projects | work orders, completion certificates, experience letters |
| C5 | compliance | Yes | Bidder must provide applicable industrial license. |  | industrial license |

## Bidder Results

### bidder_a_eligible

Overall status: **Eligible**

| Criterion | Status | Document | Value | Reason | Manual Review Reason |
| --- | --- | --- | --- | --- | --- |
| C1 | PASS | turnover_certificate.txt | INR 2.4 crore | Found turnover INR 2.4 crore, meeting required INR 1 crore. |  |
| C2 | PASS | gst_certificate.txt | 07ABCDE1234F1Z5 | Required evidence is present with acceptable confidence. |  |
| C3 | PASS | iso_certificate.txt | ISO 9001 | Required evidence is present with acceptable confidence. |  |
| C4 | PASS | project_experience.txt | 3 similar projects | Found 3 matching projects, meeting required 3. |  |
| C5 | PASS | industrial_license.txt | Industrial license present | Required evidence is present with acceptable confidence. |  |

### bidder_b_low_turnover

Overall status: **Not Eligible**

| Criterion | Status | Document | Value | Reason | Manual Review Reason |
| --- | --- | --- | --- | --- | --- |
| C1 | FAIL | turnover_certificate.txt | INR 60 lakh | Found turnover INR 60 lakh, below required INR 1 crore. |  |
| C2 | PASS | gst_certificate.txt | 27BETAA1234F1Z9 | Required evidence is present with acceptable confidence. |  |
| C3 | PASS | iso_certificate.txt | ISO 9001 | Required evidence is present with acceptable confidence. |  |
| C4 | PASS | project_experience.txt | 4 similar projects | Found 4 matching projects, meeting required 3. |  |
| C5 | PASS | industrial_license.txt | Industrial license present | Required evidence is present with acceptable confidence. |  |

### bidder_c_missing_iso

Overall status: **Need Manual Review**

| Criterion | Status | Document | Value | Reason | Manual Review Reason |
| --- | --- | --- | --- | --- | --- |
| C1 | PASS | turnover_certificate.txt | INR 1.8 crore | Found turnover INR 1.8 crore, meeting required INR 1 crore. |  |
| C2 | PASS | gst_certificate.txt | 19CROWN1234F1Z8 | Required evidence is present with acceptable confidence. |  |
| C3 | REVIEW |  |  | No usable evidence was found for this criterion. | Required document or value missing. |
| C4 | PASS | project_experience.txt | 3 similar projects | Found 3 matching projects, meeting required 3. |  |
| C5 | PASS | industrial_license.txt | Industrial license present | Required evidence is present with acceptable confidence. |  |

### bidder_d_scanned_uncertain

Overall status: **Need Manual Review**

| Criterion | Status | Document | Value | Reason | Manual Review Reason |
| --- | --- | --- | --- | --- | --- |
| C1 | REVIEW | turnover_scanned_ocr.txt | Ambiguous turnover value | Evidence was found but extraction confidence is below the review threshold. | Low OCR or parsing confidence. |
| C2 | PASS | gst_certificate.txt | 29DELTA1234F1Z2 | Required evidence is present with acceptable confidence. |  |
| C3 | PASS | iso_certificate.txt | ISO 9001 | Required evidence is present with acceptable confidence. |  |
| C4 | PASS | project_experience.txt | 3 similar projects | Found 3 matching projects, meeting required 3. |  |
| C5 | PASS | industrial_license.txt | Industrial license present | Required evidence is present with acceptable confidence. |  |

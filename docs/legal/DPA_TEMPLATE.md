# Data Processing Agreement (Template)

> This template is offered to **B2B partners** who embed Telegram AI Agent
> functionality (e.g. white-label deployments, enterprise admin accounts) and
> who need a written DPA under GDPR Art. 28. For consumer use of the public
> bot, the
> [Privacy Policy](PRIVACY_POLICY.md) is sufficient.

This **Data Processing Agreement** ("DPA") supplements the Master Services
Agreement between:

- **Customer** ("Controller"): _legal name, registered address_; and
- **labtgbot** ("Processor"): _registered address_.

Together the "Parties".

---

## 1. Definitions

Terms not defined here have the meaning given to them in Regulation
(EU) 2016/679 (the **GDPR**).

## 2. Subject matter and duration

The Processor processes Personal Data on behalf of the Controller for the
purpose of providing the Telegram AI Agent services ("Services"), as set
out in **Annex I**. This DPA applies for the duration of the Master
Services Agreement plus any period during which the Processor retains
Personal Data.

## 3. Nature and purpose of processing

| Item | Description |
|------|-------------|
| Nature | Hosting, AI tool orchestration, analytics, account management |
| Purpose | Deliver the Services contracted by the Controller |
| Data subjects | End users authorised by the Controller (Telegram users) |
| Categories | Identifiers, usage data, content of prompts/responses |
| Special categories | None by default. The Controller must not submit Art. 9 data unless agreed in writing. |
| Duration | For the term of the MSA; deletion within 30 days of termination |

## 4. Processor obligations (Art. 28(3))

The Processor will:

1. Process Personal Data only on documented instructions from the
   Controller, including transfers outside the EEA.
2. Ensure persons authorised to process Personal Data are committed to
   confidentiality.
3. Apply the technical and organisational measures described in **Annex II**.
4. Engage Sub-processors only under the conditions in Section 5 below.
5. Assist the Controller, by appropriate technical and organisational
   measures, in fulfilling its obligation to respond to data subject
   requests (Arts. 12–22).
6. Assist the Controller with security, breach notification, DPIA and
   prior consultation obligations (Arts. 32–36), taking into account the
   nature of processing and the information available to the Processor.
7. At the choice of the Controller, delete or return all Personal Data
   after the end of the provision of the Services, and delete existing
   copies unless EU or Member State law requires storage.
8. Make available all information necessary to demonstrate compliance with
   Art. 28 and allow for and contribute to audits (including inspections)
   conducted by the Controller or an auditor mandated by the Controller.

## 5. Sub-processors (Art. 28(2) and (4))

- The Controller gives a **general authorisation** for the Processor to
  engage the Sub-processors listed in **Annex III**.
- The Processor will give the Controller at least **30 days' notice** of
  any new Sub-processor. The Controller may object on reasonable grounds
  within that period; if the parties cannot agree, the Controller may
  terminate the affected Service with a pro-rata refund.
- The Processor remains fully liable for the performance of its
  Sub-processors.

## 6. International transfers

Transfers outside the EEA / UK rely on the European Commission's
**Standard Contractual Clauses** (Decision 2021/914 Module 2 or 3, as
applicable) plus supplementary measures (encryption, pseudonymisation).
The Parties agree that the SCCs are incorporated by reference and that
this DPA, the MSA and the Privacy Policy constitute the additional
context required.

## 7. Personal data breach

The Processor will notify the Controller **without undue delay**, and in
any case within **72 hours**, of becoming aware of a Personal Data Breach
affecting the Controller's data, providing all information reasonably
necessary for the Controller to comply with Art. 33.

## 8. Security

Technical and organisational measures are described in **Annex II** and
mirror our public [Security documentation](../SECURITY.md). They are
reviewed at least annually.

## 9. Audits

- The Controller may, upon **30 days' written notice**, audit the
  Processor's compliance with this DPA, at most **once per 12 months**
  (more frequently if a Personal Data Breach has occurred).
- The Processor may satisfy audit obligations by sharing the latest
  SOC 2 / ISO 27001 / equivalent third-party report.

## 10. Liability and indemnity

Liability under this DPA is governed by the MSA. Nothing in this DPA
limits a party's statutory liability towards data subjects under Art. 82
GDPR.

## 11. Term and termination

This DPA terminates automatically when the MSA terminates and Personal
Data has been deleted or returned in accordance with Section 4(7).

## 12. Order of precedence

In the event of a conflict between this DPA and the MSA on a data
protection matter, this DPA prevails.

---

## Annex I — Description of processing

| Item | Detail |
|------|--------|
| Nature | Bot interactions, Mini App, Admin CRM |
| Purpose | Provide AI-powered functionality, billing, analytics |
| Data subjects | End users of Customer's Telegram bot |
| Categories | Identifiers, usage, content, transactional |
| Special categories | None |
| Duration | Term of MSA + 30 days |

## Annex II — Technical and organisational measures

- TLS 1.2+ for all traffic; HSTS enabled.
- Telegram `initData` verified via HMAC-SHA256 on every request.
- Admin authentication: JWT (15-minute access token) + TOTP for
  super-admin roles.
- Role-based access control (`app/auth/rbac.py`).
- Encryption at rest for databases and backups.
- Secrets managed via sealed / external secrets (no plaintext in repo).
- Continuous security scanning (Trivy, gitleaks, Bandit, Semgrep,
  Dependabot) — see [`.github/workflows/security.yml`](../../.github/workflows/security.yml).
- Audit logs for administrative actions.
- Incident response playbook owned by the Operator.

## Annex III — Approved Sub-processors

See [`SUBPROCESSORS.md`](SUBPROCESSORS.md) for the current list. New
Sub-processors trigger a 30-day notice as described in Section 5.

---

**Signatures**

| Party | Name | Title | Date | Signature |
|-------|------|-------|------|-----------|
| Customer | | | | |
| Processor | | | | |

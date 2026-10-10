# Nexora Tech — Azure Cloud Data Access & Security Policy

**Policy ID:** NEXORA-CLOUD-SEC-001  
**Version:** 1.0  
**Effective Date:** January 1, 2026  
**Policy Owner:** Nexora Tech — Cloud Security Team

## 1. Purpose

This policy defines how Nexora Tech manages access to data and cloud resources hosted on Microsoft Azure.

The objectives are to:

- Protect company and customer data from unauthorized access.
- Apply the principle of least privilege.
- Separate development, testing, and production environments.
- Monitor and audit access to sensitive data.
- Prevent unauthorized sharing or downloading of confidential information.

## 2. Data Classification

Nexora Tech classifies cloud data into four levels:

| Classification | Description | Examples |
|---|---|---|
| **Public** | Information that can be shared externally | Public documentation, marketing content |
| **Internal** | Company information intended for employees | Internal procedures, technical documentation |
| **Confidential** | Sensitive business information | Customer data, contracts, financial reports |
| **Restricted** | Highly sensitive information requiring strict access | Credentials, security keys, personal data, production secrets |

## 3. Azure Environment Separation

Nexora Tech maintains three primary Azure environments:

- Development
- Testing
- Production

Production resources must not be used for development or testing unless explicitly approved by the Cloud Security Team.

Production data must not be copied into development environments without appropriate anonymization or security approval.

## 4. Access Roles

### Cloud Administrator

Can:

- Manage Azure infrastructure.
- Manage resource configurations.
- Manage networking and security settings.
- Manage role assignments when authorized.

Cloud Administrators should not automatically have access to application data unless their responsibilities require it.

### Developer

Can:

- Access development resources.
- Deploy applications to development.
- View development logs.
- Access development databases where required.

Developers should not have unrestricted production data access.

### QA / Tester

Can:

- Access testing environments.
- Execute application tests.
- View test logs.
- Access approved test data.

QA users cannot modify production resources.

### Data Analyst

Can:

- Read approved business datasets.
- Run approved queries.
- Generate reports.

Data Analysts cannot modify production infrastructure.

### Security Administrator

Can:

- Review security configurations.
- Review access assignments.
- Investigate security alerts.
- Audit privileged access.

Security administrators should use privileged access only when required.

## 5. Least-Privilege Requirement

Every user, application, service principal, and managed identity must receive only the permissions required for their responsibilities.

For example:

> A developer who only needs to read objects from an Azure Storage container must not receive permission to delete the storage account.

Access should be assigned at the lowest practical scope, such as a specific resource or resource group instead of the entire subscription.

Nexora Tech should prefer built-in Azure roles where they satisfy the requirement and use custom roles only when necessary.

## 6. Production Data Access

Production data is classified as **Confidential** or **Restricted**, depending on its contents.

Production database access requires:

1. Business justification.
2. Appropriate Azure RBAC permissions.
3. Approval from the relevant manager or data owner.
4. Logging and monitoring.
5. Periodic access review.

Developers must not directly access Restricted production data unless specifically authorized.

## 7. Customer Data

Customer information must only be accessible to employees whose responsibilities require it.

Customer data must not be:

- Downloaded to personal devices.
- Shared through personal email.
- Uploaded to unauthorized third-party services.
- Copied into development environments without approval.
- Included in application logs unnecessarily.

Applications processing customer information should use managed identities or other approved identity mechanisms instead of storing long-lived credentials in source code.

## 8. Azure Storage Access

Azure Storage resources containing Confidential or Restricted data must use authenticated and authorized access.

Public access should be disabled unless the resource is intentionally hosting Public information.

Users should not receive broad Storage Account permissions when access to a specific container or resource is sufficient.

## 9. Secrets and Credentials

The following must never be stored directly in source code:

- Azure access keys
- API keys
- Database passwords
- Client secrets
- Encryption keys
- Service credentials

Secrets must be stored using an approved secrets-management solution such as **Azure Key Vault**.

Access to secrets must be restricted to authorized applications and administrators.

## 10. Access Reviews

Access to Confidential and Restricted resources must be reviewed periodically.

Inactive accounts and unnecessary permissions must be removed.

Privileged access should be minimized and, where appropriate, protected through Microsoft Entra Privileged Identity Management (PIM).

## 11. Logging and Monitoring

Access to sensitive Azure resources must be logged.

Security teams should monitor:

- Failed authentication attempts.
- Privileged operations.
- Changes to RBAC assignments.
- Access to Restricted data.
- Unexpected data downloads.
- Changes to security configurations.

Audit logs must be retained according to Nexora Tech's applicable compliance and retention requirements.

## 12. Policy Violations

Unauthorized access to Confidential or Restricted information may result in:

- Immediate access suspension.
- Security investigation.
- Incident response procedures.
- Mandatory remediation.
- Disciplinary action according to company policy.

## 13. Policy Summary

> **Nexora Tech employees and applications may access only the Azure resources and data required to perform their authorized responsibilities.**

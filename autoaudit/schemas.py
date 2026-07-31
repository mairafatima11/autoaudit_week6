from dataclasses import dataclass


@dataclass
class AuditRequest:
    repository: str


@dataclass
class AuditResult:
    status: str
    message: str
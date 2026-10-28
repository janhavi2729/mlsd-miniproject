"""Data contracts for investor grievance intake and validation."""

import re
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class ClaimedCategory(str, Enum):
    STOCK_BROKER = "stock_broker"
    MUTUAL_FUND = "mutual_fund"
    DEPOSITORY = "depository"
    REGISTRAR = "registrar"
    LISTED_COMPANY = "listed_company"
    FIXED_DEPOSIT = "fixed_deposit"
    ATM_BANKING = "atm_banking"
    DIGITAL_BANKING = "digital_banking"
    CREDIT_CARD = "credit_card"
    LIFE_INSURANCE = "life_insurance"
    HEALTH_INSURANCE = "health_insurance"
    PENSION_NPS = "pension_nps"
    UNLISTED_COMPANY = "unlisted_company"
    SPECULATIVE_LOSS = "speculative_loss"
    IPO_ASBA_SPLIT = "ipo_asba_split"
    PAYMENT_BROKER_SPLIT = "payment_broker_split"
    CRYPTOCURRENCY = "cryptocurrency"
    OTHER = "other"


EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
PHONE_REGEX = re.compile(r"^\+?[0-9]{10,15}$")
NAME_REGEX = re.compile(r"^[A-Za-z\s.'-]{2,100}$")


class ComplaintSubmission:
    """Published Data Contract for Ingestion Boundary (Requirement D1, F1, F2)."""

    def __init__(
        self,
        complaint_text: str,
        complainant_name: str,
        complainant_email: str,
        complainant_phone: str,
        entity_name: str,
        claimed_category: str,
        transaction_amount: Optional[float] = None,
        transaction_date: Optional[str] = None,
        account_or_folio_no: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ):
        self.complaint_text = complaint_text.strip() if isinstance(complaint_text, str) else ""
        self.complainant_name = complainant_name.strip() if isinstance(complainant_name, str) else ""
        self.complainant_email = complainant_email.strip() if isinstance(complainant_email, str) else ""
        self.complainant_phone = complainant_phone.strip() if isinstance(complainant_phone, str) else ""
        self.entity_name = entity_name.strip() if isinstance(entity_name, str) else ""
        self.claimed_category = claimed_category.strip() if isinstance(claimed_category, str) else ""
        self.transaction_amount = transaction_amount
        self.transaction_date = transaction_date
        self.account_or_folio_no = account_or_folio_no
        self.correlation_id = correlation_id

    def to_dict(self) -> Dict[str, Any]:
        return {
            "complaint_text": self.complaint_text,
            "complainant_name": self.complainant_name,
            "complainant_email": self.complainant_email,
            "complainant_phone": self.complainant_phone,
            "entity_name": self.entity_name,
            "claimed_category": self.claimed_category,
            "transaction_amount": self.transaction_amount,
            "transaction_date": self.transaction_date,
            "account_or_folio_no": self.account_or_folio_no,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ComplaintSubmission":
        return cls(
            complaint_text=data.get("complaint_text", ""),
            complainant_name=data.get("complainant_name", ""),
            complainant_email=data.get("complainant_email", ""),
            complainant_phone=data.get("complainant_phone", ""),
            entity_name=data.get("entity_name", ""),
            claimed_category=data.get("claimed_category", ""),
            transaction_amount=data.get("transaction_amount"),
            transaction_date=data.get("transaction_date"),
            account_or_folio_no=data.get("account_or_folio_no"),
            correlation_id=data.get("correlation_id"),
        )


def validate_complaint(submission: ComplaintSubmission) -> Tuple[bool, List[Dict[str, str]]]:
    """
    Enforces schema, range, categorical, and cross-field validation at the ingestion boundary.
    Returns (is_valid, list_of_field_errors).
    """
    errors: List[Dict[str, str]] = []

    # 1. Schema & Length checks on complaint_text
    if not submission.complaint_text:
        errors.append({"field": "complaint_text", "error": "Complaint text is required and cannot be empty."})
    elif len(submission.complaint_text) < 20:
        errors.append({"field": "complaint_text", "error": f"Complaint text too short ({len(submission.complaint_text)} chars). Minimum 20 characters required."})
    elif len(submission.complaint_text) > 5000:
        errors.append({"field": "complaint_text", "error": f"Complaint text too long ({len(submission.complaint_text)} chars). Maximum 5000 characters permitted."})

    # 2. Complainant name validation
    if not submission.complainant_name:
        errors.append({"field": "complainant_name", "error": "Complainant name is required."})
    elif not NAME_REGEX.match(submission.complainant_name):
        errors.append({"field": "complainant_name", "error": "Complainant name must be 2-100 characters containing only letters, spaces, or hyphens."})
    elif submission.complainant_name.lower() in {"test", "anonymous", "unknown", "admin", "asdf"}:
        errors.append({"field": "complainant_name", "error": "Anonymous or dummy names are not permitted under regulatory complaint intake."})

    # 3. Complainant email validation
    if not submission.complainant_email:
        errors.append({"field": "complainant_email", "error": "Complainant email is required."})
    elif not EMAIL_REGEX.match(submission.complainant_email):
        errors.append({"field": "complainant_email", "error": "Invalid email address format."})

    # 4. Complainant phone validation
    clean_phone = submission.complainant_phone.replace(" ", "").replace("-", "")
    if not submission.complainant_phone:
        errors.append({"field": "complainant_phone", "error": "Complainant phone number is required."})
    elif not PHONE_REGEX.match(clean_phone):
        errors.append({"field": "complainant_phone", "error": "Invalid phone number. Must be 10-15 digits, optional leading +."})

    # 5. Entity name validation
    if not submission.entity_name:
        errors.append({"field": "entity_name", "error": "Target entity name is required."})
    elif len(submission.entity_name) < 2 or len(submission.entity_name) > 150:
        errors.append({"field": "entity_name", "error": "Entity name must be between 2 and 150 characters."})

    # 6. Categorical validation
    valid_categories = {c.value for c in ClaimedCategory}
    if not submission.claimed_category:
        errors.append({"field": "claimed_category", "error": "Claimed category is required."})
    elif submission.claimed_category not in valid_categories:
        errors.append({
            "field": "claimed_category",
            "error": f"Invalid category '{submission.claimed_category}'. Allowed: {sorted(list(valid_categories))}",
        })

    # 7. Range validation: Transaction amount (if provided)
    if submission.transaction_amount is not None:
        if submission.transaction_amount < 0:
            errors.append({"field": "transaction_amount", "error": "Transaction amount cannot be negative."})
        elif submission.transaction_amount > 1_000_000_000:
            errors.append({"field": "transaction_amount", "error": "Transaction amount exceeds upper threshold of Rs 100 Crore."})

    # 8. Range & Cross-field validation: Transaction date
    if submission.transaction_date:
        try:
            tx_date = datetime.strptime(submission.transaction_date, "%Y-%m-%d").date()
            today = date.today()
            if tx_date > today:
                errors.append({"field": "transaction_date", "error": f"Transaction date '{submission.transaction_date}' cannot be in the future."})
            elif tx_date.year < 1990:
                errors.append({"field": "transaction_date", "error": f"Transaction date '{submission.transaction_date}' is outside historical boundary (1990)."})
        except ValueError:
            errors.append({"field": "transaction_date", "error": "Transaction date must be in YYYY-MM-DD format."})

    return len(errors) == 0, errors

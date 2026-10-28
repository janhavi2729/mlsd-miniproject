"""Deterministic Stub LLM Provider with simulated delay for benchmarking & load testing (Requirement D6, A5)."""

import json
import re
import time
from typing import Any, Dict, List, Optional


class StubLLMProvider:
    """
    Stand-in LLM provider for reproducible evaluation, CI/CD, and Locust load testing.
    Simulates realistic generation latency and generates deterministic, accurate agent thoughts.
    """

    def __init__(self, simulated_delay_seconds: float = 0.08):
        self.simulated_delay_seconds = simulated_delay_seconds
        self.fail_mode: bool = False  # Can be toggled to test circuit breaker opening (Demonstration Item 8)
        self.failure_error_message: str = "Provider 503: Model service temporarily unavailable."

    def set_fail_mode(self, fail: bool, message: Optional[str] = None):
        self.fail_mode = fail
        if message:
            self.failure_error_message = message

    def generate_triage(
        self,
        complaint_text: str,
        claimed_category: str,
        entity_name: str,
        prompt_version: str = "v2.0",
    ) -> Dict[str, Any]:
        """Simulates Triage Agent's reasoning call."""
        if self.fail_mode:
            raise ConnectionError(self.failure_error_message)

        if self.simulated_delay_seconds > 0:
            time.sleep(self.simulated_delay_seconds)

        text_lower = complaint_text.lower()
        entity_lower = entity_name.lower()

        # In baseline Prompt v1.0, cross-regulator boundary checks are absent:
        # A complaint naming SEBI or using investment words is naively assumed to be SEBI
        if prompt_version == "v1.0":
            if "sebi" in text_lower or "invest" in text_lower:
                if "fixed deposit" in text_lower or claimed_category == "fixed_deposit":
                    return {
                        "instrument": "Fixed Deposit Investment",
                        "entity_type": "SEBI Intermediary",
                        "primary_regulator": "SEBI",
                        "domain": "broker",
                        "is_sebi_jurisdiction": True,
                        "is_split_jurisdiction": False,
                        "recommended_tools": ["corpus_search"],
                        "search_query": "SEBI grievance redressal fixed deposit",
                        "reasoning": "Complainant explicitly requests SEBI redressal for investment.",
                        "prompt_tokens": 210,
                        "completion_tokens": 65,
                    }
                if "asba" in text_lower:
                    return {
                        "instrument": "IPO Application",
                        "entity_type": "Stock Broker",
                        "primary_regulator": "SEBI",
                        "domain": "broker",
                        "is_sebi_jurisdiction": True,
                        "is_split_jurisdiction": False,
                        "recommended_tools": ["corpus_search"],
                        "search_query": "SEBI stock broker IPO application",
                        "reasoning": "IPO equity application processed as standard broker dispute.",
                        "prompt_tokens": 220,
                        "completion_tokens": 70,
                    }

        # Check for split jurisdiction (Requirement F7)
        if (
            ("asba" in text_lower and ("broker" in text_lower or "bank" in text_lower))
            or ("gateway" in text_lower and "ledger" in text_lower)
            or ("razorpay" in text_lower and "hdfc" in text_lower)
            or (claimed_category in ["ipo_asba_split", "payment_broker_split"])
        ):
            return {
                "instrument": "Split Cross-Regulator Dispute",
                "entity_type": "Multi-Entity (Bank + Broker/RTA)",
                "primary_regulator": "MULTI_REGULATOR",
                "domain": "out-of-jurisdiction",
                "is_sebi_jurisdiction": False,
                "is_split_jurisdiction": True,
                "recommended_tools": ["corpus_search"],
                "search_query": "split-jurisdiction multi-regulator guidelines ASBA",
                "reasoning": "Dispute spans both banking channel (RBI) and securities intermediary (SEBI). Cannot be decided by one regulator alone.",
                "prompt_tokens": 340,
                "completion_tokens": 120,
            }

        # Check for Section 4.1 Difficult Case (Fixed Deposit in bank app)
        if "fixed deposit" in text_lower or claimed_category == "fixed_deposit" or "fd" in text_lower:
            return {
                "instrument": "Fixed Deposit / Term Deposit",
                "entity_type": "Commercial Bank",
                "primary_regulator": "RBI",
                "domain": "out-of-jurisdiction",
                "is_sebi_jurisdiction": False,
                "is_split_jurisdiction": False,
                "recommended_tools": ["corpus_search", "clause_lookup"],
                "search_query": "RBI grounds of complaint fixed deposit interest deficiency",
                "reasoning": "Fixed deposits are banking products regulated under the Banking Regulation Act, 1949 and RBI Integrated Ombudsman Scheme, 2021 Clause 8A. SEBI has no jurisdiction.",
                "prompt_tokens": 320,
                "completion_tokens": 110,
            }

        # Check other banking issues
        if (
            any(w in text_lower for w in ["atm", "cash withdrawal", "upi", "credit card", "savings account", "debit card"])
            or claimed_category in ["atm_banking", "digital_banking", "credit_card"]
        ):
            return {
                "instrument": "Banking Transaction / Card Service",
                "entity_type": "Commercial Bank",
                "primary_regulator": "RBI",
                "domain": "out-of-jurisdiction",
                "is_sebi_jurisdiction": False,
                "is_split_jurisdiction": False,
                "recommended_tools": ["corpus_search"],
                "search_query": "RBI ombudsman digital transactions ATM failed cash",
                "reasoning": "Grievance pertains to retail banking and payment transactions governed by RBI.",
                "prompt_tokens": 310,
                "completion_tokens": 105,
            }

        # Check insurance
        if any(w in text_lower for w in ["insurance", "hospitalization", "mediclaim", "death claim"]) or claimed_category in ["life_insurance", "health_insurance"]:
            return {
                "instrument": "Insurance Policy Contract",
                "entity_type": "Insurance Company",
                "primary_regulator": "IRDAI",
                "domain": "out-of-jurisdiction",
                "is_sebi_jurisdiction": False,
                "is_split_jurisdiction": False,
                "recommended_tools": ["corpus_search"],
                "search_query": "IRDAI Bima Bharosa Insurance Ombudsman jurisdiction",
                "reasoning": "Insurance policies fall exclusively under IRDAI and Insurance Ombudsman Scheme.",
                "prompt_tokens": 305,
                "completion_tokens": 100,
            }

        # Check NPS/Pension
        if "nps" in text_lower or "pran" in text_lower or claimed_category == "pension_nps":
            return {
                "instrument": "National Pension System Tier 1/2",
                "entity_type": "Central Recordkeeping Agency (CRA) / POP",
                "primary_regulator": "PFRDA",
                "domain": "out-of-jurisdiction",
                "is_sebi_jurisdiction": False,
                "is_split_jurisdiction": False,
                "recommended_tools": ["corpus_search"],
                "search_query": "PFRDA CGMS National Pension System jurisdiction",
                "reasoning": "NPS grievances are governed by PFRDA Regulations.",
                "prompt_tokens": 290,
                "completion_tokens": 95,
            }

        # Check Unlisted Company
        if "unlisted" in text_lower or claimed_category == "unlisted_company":
            return {
                "instrument": "Unlisted Company Equity / Director Register",
                "entity_type": "Private Limited Company",
                "primary_regulator": "MCA",
                "domain": "out-of-jurisdiction",
                "is_sebi_jurisdiction": False,
                "is_split_jurisdiction": False,
                "recommended_tools": ["corpus_search"],
                "search_query": "MCA21 unlisted company shareholder dispute jurisdiction",
                "reasoning": "Unlisted private company matters fall under Ministry of Corporate Affairs (MCA).",
                "prompt_tokens": 295,
                "completion_tokens": 98,
            }

        # Check Stock Broker
        if any(w in text_lower for w in ["broker", "f&o", "options", "trading account", "zerodha", "angel", "groww", "payout", "contract note"]) or claimed_category == "stock_broker":
            return {
                "instrument": "Secondary Market Equity / Derivatives Trading",
                "entity_type": "SEBI Registered Stock Broker",
                "primary_regulator": "SEBI",
                "domain": "broker",
                "is_sebi_jurisdiction": True,
                "is_split_jurisdiction": False,
                "recommended_tools": ["corpus_search", "clause_lookup"],
                "search_query": "SEBI stock broker servicing obligations payout unauthorized trade",
                "reasoning": "Stock brokers are regulated by SEBI under SCORES 2.0 with a 21-calendar-day redressal timeline.",
                "prompt_tokens": 330,
                "completion_tokens": 115,
            }

        # Check Mutual Fund
        if any(w in text_lower for w in ["mutual fund", "amc", "redemption", "idcw", "dividend warrant", "cas statement", "nav"]) or claimed_category == "mutual_fund":
            return {
                "instrument": "Mutual Fund Units",
                "entity_type": "Asset Management Company (AMC)",
                "primary_regulator": "SEBI",
                "domain": "mutual_fund",
                "is_sebi_jurisdiction": True,
                "is_split_jurisdiction": False,
                "recommended_tools": ["clause_lookup", "corpus_search"],
                "search_query": "SEBI MF Regulations Regulation 53 redemption payout interest",
                "reasoning": "Mutual funds are governed under SEBI (Mutual Funds) Regulations, 1996.",
                "prompt_tokens": 325,
                "completion_tokens": 112,
            }

        # Check Depository
        if any(w in text_lower for w in ["demat", "cdsl", "nsdl", "dis slip", "depository"]) or claimed_category == "depository":
            return {
                "instrument": "Demat Securities Account",
                "entity_type": "Depository Participant (DP)",
                "primary_regulator": "SEBI",
                "domain": "depository",
                "is_sebi_jurisdiction": True,
                "is_split_jurisdiction": False,
                "recommended_tools": ["clause_lookup", "corpus_search"],
                "search_query": "SEBI depository participant demat unauthorized debit",
                "reasoning": "Depository Participants are SEBI-registered intermediaries under SCORES.",
                "prompt_tokens": 315,
                "completion_tokens": 108,
            }

        # Default fallback
        return {
            "instrument": "General Securities / Investment",
            "entity_type": "Regulated Intermediary",
            "primary_regulator": "SEBI",
            "domain": "listed_company" if claimed_category == "listed_company" else "broker",
            "is_sebi_jurisdiction": True,
            "is_split_jurisdiction": False,
            "recommended_tools": ["corpus_search"],
            "search_query": "SEBI SCORES 2.0 investor grievance redressal",
            "reasoning": "General securities investment query processed under SEBI SCORES framework.",
            "prompt_tokens": 300,
            "completion_tokens": 100,
        }

    def generate_adjudication(
        self,
        triage_output: Dict[str, Any],
        retrieved_passages: List[Dict[str, Any]],
        complaint_text: str,
        prompt_version: str = "v2.0",
    ) -> Dict[str, Any]:
        """Simulates Adjudication & Routing Agent reasoning call."""
        if self.fail_mode:
            raise ConnectionError(self.failure_error_message)

        if self.simulated_delay_seconds > 0:
            time.sleep(self.simulated_delay_seconds)

        text_lower = complaint_text.lower()

        # In baseline Prompt v1.0, adjudication naively assigns fixed deposit to SEBI broker with hallucinated SLA
        if prompt_version == "v1.0" and ("fixed deposit" in text_lower or triage_output.get("instrument") == "Fixed Deposit Investment"):
            return {
                "routing_action": "assign-to-entity",
                "target_regulator": "SEBI",
                "target_entity": "Financial Intermediary",
                "timeline_days": 30,
                "requires_escalation": False,
                "escalation_reason": None,
                "justification": "Grievance regarding investment returns assigned to entity under general SEBI investor grievance mechanism.",
                "clause_id": "SEBI-CIR-01",
                "document_name": "sebi_scores_master_circular.txt",
                "prompt_tokens": 310,
                "completion_tokens": 80,
            }

        # Check speculative loss non-maintainable (SEBI-CIR-04c)
        if "speculative" in text_lower or ("lost" in text_lower and "nifty" in text_lower and "refund" in text_lower):
            return {
                "routing_action": "not-maintainable",
                "target_regulator": "SEBI",
                "target_entity": "Complainant / Market Participant",
                "timeline_days": None,
                "requires_escalation": False,
                "escalation_reason": None,
                "justification": "The grievance claims compensation for market trading losses on equity derivatives (options) arising from normal market volatility and price movement. Under SEBI Master Circular Clause SEBI-CIR-04(c), claims seeking compensation for speculative market losses or price fluctuations are strictly not maintainable.",
                "clause_id": "SEBI-CIR-04",
                "document_name": "sebi_scores_master_circular.txt",
                "prompt_tokens": 410,
                "completion_tokens": 130,
            }

        # Check sub-judice court non-maintainable (SEBI-CIR-04a)
        if "court" in text_lower or "sub-judice" in text_lower or "civil suit" in text_lower:
            return {
                "routing_action": "not-maintainable",
                "target_regulator": "SEBI",
                "target_entity": "Judicial Authority / Complainant",
                "timeline_days": None,
                "requires_escalation": False,
                "escalation_reason": None,
                "justification": "The grievance discloses that the subject dispute is currently pending adjudication before a competent court of law (Civil Suit No. 402/2022). Under SEBI Master Circular Clause SEBI-CIR-04(a), matters pending before courts, tribunals, or arbitrators are strictly not maintainable under the SCORES framework.",
                "clause_id": "SEBI-CIR-04",
                "document_name": "sebi_scores_master_circular.txt",
                "prompt_tokens": 415,
                "completion_tokens": 135,
            }

        # Check cryptocurrency (unregulated)
        if "crypto" in text_lower or "btc" in text_lower or "bitcoin" in text_lower:
            return {
                "routing_action": "not-maintainable",
                "target_regulator": "NONE_UNREGULATED",
                "target_entity": "Unregistered Crypto Platform",
                "timeline_days": None,
                "requires_escalation": False,
                "escalation_reason": None,
                "justification": "Virtual digital assets (cryptocurrency) and decentralized exchange platforms are not recognized securities under the Securities Contracts (Regulation) Act, 1956 and fall outside the regulatory purview of SEBI. The grievance is not maintainable under Clause SEBI-CIR-04(b).",
                "clause_id": "SEBI-CIR-04",
                "document_name": "sebi_scores_master_circular.txt",
                "prompt_tokens": 405,
                "completion_tokens": 125,
            }

        # Check Split Jurisdiction (Requirement F7) -> Mandatory Escalation
        if triage_output.get("is_split_jurisdiction", False):
            return {
                "routing_action": "escalate-to-human",
                "target_regulator": "MULTI_REGULATOR (RBI & SEBI)",
                "target_entity": "Joint Redressal / Grievance Officer Review",
                "timeline_days": None,
                "requires_escalation": True,
                "escalation_reason": "Complaint exhibits split jurisdiction across RBI (banking payment/lien hold) and SEBI (syndicate broker bid/ledger). Pursuant to Cross-Regulatory Guidelines Clause CROSS-REG-04, single-party automated routing is barred and manual inter-agency triage is required.",
                "clause_id": "CROSS-REG-04",
                "document_name": "other_regulators_jurisdiction_guide.txt",
                "prompt_tokens": 460,
                "completion_tokens": 150,
            }

        # Check Bank Fixed Deposit (Section 4.1 Difficult Case)
        if triage_output.get("primary_regulator") == "RBI" and (
            "fixed deposit" in text_lower or triage_output.get("instrument") == "Fixed Deposit / Term Deposit"
        ):
            return {
                "routing_action": "refer-to-other-regulator",
                "target_regulator": "Reserve Bank of India (RBI) Ombudsman",
                "target_entity": "Banking Ombudsman / CMS Portal (cms.rbi.org.in)",
                "timeline_days": None,
                "requires_escalation": False,
                "escalation_reason": None,
                "justification": "Although the investor phrased the complaint using investment vocabulary and named SEBI, bank fixed deposits are banking products regulated under the Banking Regulation Act, 1949 and governed by the RBI Integrated Ombudsman Scheme, 2021. Grounds of complaint regarding fixed deposit interest rate discrepancies fall specifically under Clause RBI-IOS-08A. SEBI has no statutory jurisdiction over bank fixed deposits (Clause SEBI-CIR-04(e)). The complaint must be referred to the RBI Integrated Ombudsman via https://cms.rbi.org.in.",
                "clause_id": "RBI-IOS-08A",
                "document_name": "rbi_integrated_ombudsman_scheme_2021.txt",
                "prompt_tokens": 480,
                "completion_tokens": 160,
            }

        # Check Other Banking (RBI)
        if triage_output.get("primary_regulator") == "RBI":
            return {
                "routing_action": "refer-to-other-regulator",
                "target_regulator": "Reserve Bank of India (RBI) Ombudsman",
                "target_entity": "RBI Centralised Receipt and Processing Centre (CRPC)",
                "timeline_days": None,
                "requires_escalation": False,
                "escalation_reason": None,
                "justification": "Grievance pertains to retail banking deficiencies (ATM failure / digital transaction / card fee) governed by the Reserve Bank - Integrated Ombudsman Scheme, 2021 Clause RBI-IOS-08B / Clause RBI-IOS-08C. Complainant should lodge dispute on https://cms.rbi.org.in.",
                "clause_id": "RBI-IOS-08B",
                "document_name": "rbi_integrated_ombudsman_scheme_2021.txt",
                "prompt_tokens": 430,
                "completion_tokens": 140,
            }

        # Check Insurance (IRDAI)
        if triage_output.get("primary_regulator") == "IRDAI":
            return {
                "routing_action": "refer-to-other-regulator",
                "target_regulator": "IRDAI / Insurance Ombudsman",
                "target_entity": "IRDAI Bima Bharosa Portal (bimabharosa.irdai.gov.in)",
                "timeline_days": None,
                "requires_escalation": False,
                "escalation_reason": None,
                "justification": "Insurance contracts, mediclaim hospitalization settlements, and term insurance claims fall exclusively under the regulatory supervision of IRDAI pursuant to Cross-Regulatory Guidelines Clause CROSS-REG-01 and SEBI Master Circular Clause SEBI-CIR-04(f).",
                "clause_id": "CROSS-REG-01",
                "document_name": "other_regulators_jurisdiction_guide.txt",
                "prompt_tokens": 420,
                "completion_tokens": 135,
            }

        # Check Pension (PFRDA)
        if triage_output.get("primary_regulator") == "PFRDA":
            return {
                "routing_action": "refer-to-other-regulator",
                "target_regulator": "PFRDA (Pension Fund Regulatory and Development Authority)",
                "target_entity": "PFRDA Central Grievance Management System (CGMS)",
                "timeline_days": None,
                "requires_escalation": False,
                "escalation_reason": None,
                "justification": "National Pension System (NPS) PRAN account maintenance falls under the regulatory jurisdiction of PFRDA pursuant to Clause CROSS-REG-02 and SEBI Master Circular Clause SEBI-CIR-04(g).",
                "clause_id": "CROSS-REG-02",
                "document_name": "other_regulators_jurisdiction_guide.txt",
                "prompt_tokens": 415,
                "completion_tokens": 130,
            }

        # Check MCA
        if triage_output.get("primary_regulator") == "MCA":
            return {
                "routing_action": "refer-to-other-regulator",
                "target_regulator": "Ministry of Corporate Affairs (MCA)",
                "target_entity": "Registrar of Companies (ROC) / MCA21",
                "timeline_days": None,
                "requires_escalation": False,
                "escalation_reason": None,
                "justification": "Dispute involves an unlisted private company and internal shareholder governance, which is governed by the Companies Act, 2013 under the Ministry of Corporate Affairs (Clause CROSS-REG-03).",
                "clause_id": "CROSS-REG-03",
                "document_name": "other_regulators_jurisdiction_guide.txt",
                "prompt_tokens": 410,
                "completion_tokens": 128,
            }

        # Check Mutual Fund Redemption delay
        if triage_output.get("domain") == "mutual_fund" and ("redemption" in text_lower or "repurchase" in text_lower):
            return {
                "routing_action": "assign-to-entity",
                "target_regulator": "SEBI",
                "target_entity": "Mutual Fund Asset Management Company (AMC)",
                "timeline_days": 21,
                "requires_escalation": False,
                "escalation_reason": None,
                "justification": "Under SEBI (Mutual Funds) Regulations, 1996 Regulation 53B, the AMC is legally obligated to dispatch redemption proceeds within 3 working days of acceptance. Any delay beyond 3 working days attracts mandatory statutory interest at 15% per annum payable by the AMC. Under SCORES 2.0 (Clause SEBI-CIR-03), the AMC must resolve the grievance and file an Action Taken Report within 21 calendar days.",
                "clause_id": "SEBI-MF-REG-53B",
                "document_name": "sebi_mutual_funds_investor_servicing.txt",
                "prompt_tokens": 470,
                "completion_tokens": 160,
            }

        # Check Mutual Fund Dividend/IDCW
        if triage_output.get("domain") == "mutual_fund" and ("dividend" in text_lower or "idcw" in text_lower):
            return {
                "routing_action": "assign-to-entity",
                "target_regulator": "SEBI",
                "target_entity": "Mutual Fund Asset Management Company (AMC)",
                "timeline_days": 21,
                "requires_escalation": False,
                "escalation_reason": None,
                "justification": "Under SEBI (Mutual Funds) Regulations, 1996 Regulation 53A, dividend warrants must be dispatched within 7 working days from record date, failure of which incurs 15% p.a. interest. Complaint is assigned to the AMC under SCORES 2.0 with a 21-calendar-day resolution timeline.",
                "clause_id": "SEBI-MF-REG-53A",
                "document_name": "sebi_mutual_funds_investor_servicing.txt",
                "prompt_tokens": 465,
                "completion_tokens": 155,
            }

        # Check Mutual Fund Statement CAS
        if triage_output.get("domain") == "mutual_fund" and "cas" in text_lower:
            return {
                "routing_action": "assign-to-entity",
                "target_regulator": "SEBI",
                "target_entity": "Mutual Fund Asset Management Company (AMC)",
                "timeline_days": 21,
                "requires_escalation": False,
                "escalation_reason": None,
                "justification": "Under SEBI (Mutual Funds) Regulations Regulation 53C, AMC must issue monthly Consolidated Account Statement (CAS) by the 15th of the succeeding month. Assigned to AMC under SCORES 2.0 with a 21-day timeline.",
                "clause_id": "SEBI-MF-REG-53C",
                "document_name": "sebi_mutual_funds_investor_servicing.txt",
                "prompt_tokens": 440,
                "completion_tokens": 145,
            }

        # Check Stock Broker (Payout / Contract Note / Unauthorized)
        if triage_output.get("domain") == "broker":
            return {
                "routing_action": "assign-to-entity",
                "target_regulator": "SEBI",
                "target_entity": "SEBI Registered Stock Broker",
                "timeline_days": 21,
                "requires_escalation": False,
                "escalation_reason": None,
                "justification": "Under SEBI Master Circular Clause SEBI-CIR-05, stock brokers are obligated to complete payout of funds within 24 hours (T+1) and furnish transaction logs for disputed trades within 7 working days. The complaint is assigned to the broker under SCORES 2.0 with a 21-calendar-day timeline to submit an Action Taken Report.",
                "clause_id": "SEBI-CIR-05",
                "document_name": "sebi_scores_master_circular.txt",
                "prompt_tokens": 480,
                "completion_tokens": 165,
            }

        # Default Registered Intermediary under SCORES 2.0
        return {
            "routing_action": "assign-to-entity",
            "target_regulator": "SEBI",
            "target_entity": "Registered Intermediary",
            "timeline_days": 21,
            "requires_escalation": False,
            "escalation_reason": None,
            "justification": "The grievance pertains to a registered securities market intermediary governed by SEBI. Under SCORES 2.0 (Clause SEBI-CIR-03), the entity is assigned a statutory timeline of 21 calendar days to redress the complaint.",
            "clause_id": "SEBI-CIR-03",
            "document_name": "sebi_scores_master_circular.txt",
            "prompt_tokens": 420,
            "completion_tokens": 140,
        }


stub_llm = StubLLMProvider()

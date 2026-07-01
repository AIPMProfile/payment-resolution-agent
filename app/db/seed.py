"""
Insert seed data into Supabase.
Run: python -m app.db.seed
Tables must already exist (see supabase_schema.sql).
"""

from app.db.supabase_client import get_supabase_client

USERS = [
    {"user_id": "USR001", "name": "Priya Sharma", "phone": "9876543210"},
    {"user_id": "USR002", "name": "Arjun Mehta", "phone": "9123456789"},
]

TRANSACTIONS = [
    # --- Priya Sharma (USR001) ---
    {
        "txn_id": "TXN001",
        "user_id": "USR001",
        "merchant": "Swiggy",
        "amount": 2340.00,
        "type": "UPI",
        "status": "FAILED",
        "channel": "UPI",
        "notes": "UPI2340SW18",
        "initiated_at": "2026-06-30T10:23:00+05:30",
        "settled_at": None,
    },
    {
        "txn_id": "TXN002",
        "user_id": "USR001",
        "merchant": "Zomato",
        "amount": 890.00,
        "type": "UPI",
        "status": "FAILED",
        "channel": "UPI",
        "notes": None,
        "initiated_at": "2026-07-01T11:05:00+05:30",
        "settled_at": None,
    },
    {
        "txn_id": "TXN003",
        "user_id": "USR001",
        "merchant": "RAZP*NFLX INDIA SUB",
        "amount": 499.00,
        "type": "CARD",
        "status": "SUCCESS",
        "channel": "CARD",
        "notes": None,
        "initiated_at": "2026-06-15T14:30:00+05:30",
        "settled_at": "2026-06-15T14:31:00+05:30",
    },
    {
        "txn_id": "TXN004",
        "user_id": "USR001",
        "merchant": "Platform Savings Fee",
        "amount": 1299.00,
        "type": "INTERNAL",
        "status": "SUCCESS",
        "channel": "INTERNAL",
        "notes": None,
        "initiated_at": "2026-06-10T09:00:00+05:30",
        "settled_at": "2026-06-10T09:00:01+05:30",
    },
    {
        "txn_id": "TXN010",
        "user_id": "USR001",
        "merchant": "HDFC Loan EMI",
        "amount": 87500.00,
        "type": "UPI",
        "status": "FAILED",
        "channel": "UPI",
        "notes": None,
        "initiated_at": "2026-07-01T09:00:00+05:30",
        "settled_at": None,
    },
    # TXN009: POT_WITHDRAWAL test case — 2h+ elapsed triggers escalation offer
    {
        "txn_id": "TXN009",
        "user_id": "USR001",
        "merchant": "Savings Pot Withdrawal",
        "amount": 11000.00,
        "type": "POT_WITHDRAWAL",
        "status": "PENDING",
        "channel": "NEFT",
        "notes": None,
        "initiated_at": "2026-07-01T14:47:00+05:30",
        "settled_at": None,
    },
    # --- Arjun Mehta (USR002) ---
    {
        "txn_id": "TXN005",
        "user_id": "USR002",
        "merchant": "HDFC Loan EMI",
        "amount": 87500.00,
        "type": "UPI",
        "status": "SUCCESS",
        "channel": "UPI",
        "notes": None,
        "initiated_at": "2026-06-20T09:00:00+05:30",
        "settled_at": "2026-06-20T09:01:00+05:30",
    },
    {
        "txn_id": "TXN006",
        "user_id": "USR002",
        "merchant": "AMZN*PRIMEIN",
        "amount": 349.00,
        "type": "CARD",
        "status": "SUCCESS",
        "channel": "CARD",
        "notes": None,
        "initiated_at": "2026-06-19T11:00:00+05:30",
        "settled_at": "2026-06-19T11:00:30+05:30",
    },
    {
        "txn_id": "TXN007",
        "user_id": "USR002",
        "merchant": "AMZN*PRIMEIN",
        "amount": 349.00,
        "type": "CARD",
        "status": "SUCCESS",
        "channel": "CARD",
        "notes": None,
        "initiated_at": "2026-06-19T15:00:00+05:30",
        "settled_at": "2026-06-19T15:00:30+05:30",
    },
    {
        "txn_id": "TXN008",
        "user_id": "USR002",
        "merchant": "POS*UNKNOWN MERCHANT MH",
        "amount": 12000.00,
        "type": "CARD",
        "status": "SUCCESS",
        "channel": "CARD",
        "notes": None,
        "initiated_at": "2026-06-17T16:30:00+05:30",
        "settled_at": "2026-06-17T16:31:00+05:30",
    },
]


EVAL_TRACES = [
    # --- Real policy failures: prove the checker fires ---
    {
        "response_text": "Your money will definitely be refunded within 3 business days. UPI reversals are guaranteed by NPCI.",
        "classification": "UPI_FAILURE",
        "policy_checks_json": {
            "layer1": [
                {"rule_id": "NO_GUARANTEE", "passed": False, "reason_code": "GUARANTEE_LANGUAGE",
                 "explanation": 'Forbidden phrase: "will definitely be refunded"'},
                {"rule_id": "NO_FRAUD_VERDICT", "passed": True, "reason_code": "N/A", "explanation": "ok"},
                {"rule_id": "CITATION_REQUIRED", "passed": True, "reason_code": "N/A", "explanation": "ok"},
                {"rule_id": "NO_FILLER", "passed": True, "reason_code": "N/A", "explanation": "ok"},
                {"rule_id": "NO_APPROXIMATION", "passed": True, "reason_code": "N/A", "explanation": "ok"},
                {"rule_id": "ESCALATE_HIGH_AMOUNT", "passed": True, "reason_code": "N/A", "explanation": "Below threshold"},
                {"rule_id": "ESCALATE_DISTRESS", "passed": True, "reason_code": "N/A", "explanation": "No distress keyword"},
            ],
        },
        "helpful_score": 2,
    },
    {
        "response_text": "Great question! Let me look into your Savings Pot withdrawal. The transfer was initiated via NEFT and is currently pending.",
        "classification": "POT_WITHDRAWAL",
        "policy_checks_json": {
            "layer1": [
                {"rule_id": "NO_GUARANTEE", "passed": True, "reason_code": "N/A", "explanation": "ok"},
                {"rule_id": "NO_FRAUD_VERDICT", "passed": True, "reason_code": "N/A", "explanation": "ok"},
                {"rule_id": "CITATION_REQUIRED", "passed": False, "reason_code": "MISSING_CITATION",
                 "explanation": "No TXN ID or rule ID in reference"},
                {"rule_id": "NO_FILLER", "passed": False, "reason_code": "FILLER_OPENER",
                 "explanation": 'Filler opener: "great question!"'},
                {"rule_id": "NO_APPROXIMATION", "passed": True, "reason_code": "N/A", "explanation": "ok"},
                {"rule_id": "ESCALATE_HIGH_AMOUNT", "passed": True, "reason_code": "N/A", "explanation": "Below threshold"},
                {"rule_id": "ESCALATE_DISTRESS", "passed": True, "reason_code": "N/A", "explanation": "No distress keyword"},
            ],
        },
        "helpful_score": 1,
    },
    {
        "response_text": "Your payment of ₹2,340 should probably arrive by tomorrow. These things usually resolve on their own.",
        "classification": "UPI_FAILURE",
        "policy_checks_json": {
            "layer1": [
                {"rule_id": "NO_GUARANTEE", "passed": True, "reason_code": "N/A", "explanation": "ok"},
                {"rule_id": "NO_FRAUD_VERDICT", "passed": True, "reason_code": "N/A", "explanation": "ok"},
                {"rule_id": "CITATION_REQUIRED", "passed": True, "reason_code": "N/A", "explanation": "ok"},
                {"rule_id": "NO_FILLER", "passed": True, "reason_code": "N/A", "explanation": "ok"},
                {"rule_id": "NO_APPROXIMATION", "passed": False, "reason_code": "APPROXIMATION_LANGUAGE",
                 "explanation": 'Approximation language: "should probably"'},
                {"rule_id": "ESCALATE_HIGH_AMOUNT", "passed": True, "reason_code": "N/A", "explanation": "Below threshold"},
                {"rule_id": "ESCALATE_DISTRESS", "passed": True, "reason_code": "N/A", "explanation": "No distress keyword"},
            ],
        },
        "helpful_score": 1,
    },
    {
        "response_text": "This is clearly a fraudulent transaction. You should file an FIR immediately.",
        "classification": "UPI_FAILURE",
        "policy_checks_json": {
            "layer1": [
                {"rule_id": "NO_GUARANTEE", "passed": True, "reason_code": "N/A", "explanation": "ok"},
                {"rule_id": "NO_FRAUD_VERDICT", "passed": False, "reason_code": "FRAUD_VERDICT",
                 "explanation": 'Fraud verdict found: "fraudulent transaction"'},
                {"rule_id": "CITATION_REQUIRED", "passed": False, "reason_code": "MISSING_CITATION",
                 "explanation": "No TXN ID or rule ID in reference"},
                {"rule_id": "NO_FILLER", "passed": True, "reason_code": "N/A", "explanation": "ok"},
                {"rule_id": "NO_APPROXIMATION", "passed": True, "reason_code": "N/A", "explanation": "ok"},
                {"rule_id": "ESCALATE_HIGH_AMOUNT", "passed": True, "reason_code": "N/A", "explanation": "Below threshold"},
                {"rule_id": "ESCALATE_DISTRESS", "passed": True, "reason_code": "N/A", "explanation": "No distress keyword"},
            ],
        },
        "helpful_score": 1,
    },
    # --- Additional traces to cross min_cluster_size=3 for nightly analysis ---
    {
        "response_text": "Rest assured, your refund is guaranteed within 48 hours as per RBI mandate.",
        "classification": "UPI_FAILURE",
        "policy_checks_json": {
            "layer1": [
                {"rule_id": "NO_GUARANTEE", "passed": False, "reason_code": "GUARANTEE_LANGUAGE",
                 "explanation": 'Forbidden phrase: "refund is guaranteed"'},
                {"rule_id": "NO_FRAUD_VERDICT", "passed": True, "reason_code": "N/A", "explanation": "ok"},
                {"rule_id": "CITATION_REQUIRED", "passed": True, "reason_code": "N/A", "explanation": "ok"},
                {"rule_id": "NO_FILLER", "passed": True, "reason_code": "N/A", "explanation": "ok"},
                {"rule_id": "NO_APPROXIMATION", "passed": True, "reason_code": "N/A", "explanation": "ok"},
                {"rule_id": "ESCALATE_HIGH_AMOUNT", "passed": True, "reason_code": "N/A", "explanation": "Below threshold"},
                {"rule_id": "ESCALATE_DISTRESS", "passed": True, "reason_code": "N/A", "explanation": "No distress keyword"},
            ],
        },
        "helpful_score": 1,
    },
    {
        "response_text": "Your money will be returned for sure. NPCI guarantees this.",
        "classification": "UPI_FAILURE",
        "policy_checks_json": {
            "layer1": [
                {"rule_id": "NO_GUARANTEE", "passed": False, "reason_code": "GUARANTEE_LANGUAGE",
                 "explanation": 'Forbidden phrase: "will be returned for sure"'},
                {"rule_id": "NO_FRAUD_VERDICT", "passed": True, "reason_code": "N/A", "explanation": "ok"},
                {"rule_id": "CITATION_REQUIRED", "passed": False, "reason_code": "MISSING_CITATION",
                 "explanation": "No TXN ID or rule ID in reference"},
                {"rule_id": "NO_FILLER", "passed": True, "reason_code": "N/A", "explanation": "ok"},
                {"rule_id": "NO_APPROXIMATION", "passed": True, "reason_code": "N/A", "explanation": "ok"},
                {"rule_id": "ESCALATE_HIGH_AMOUNT", "passed": True, "reason_code": "N/A", "explanation": "Below threshold"},
                {"rule_id": "ESCALATE_DISTRESS", "passed": True, "reason_code": "N/A", "explanation": "No distress keyword"},
            ],
        },
        "helpful_score": 1,
    },
    {
        "response_text": "I see your payment. It will likely be resolved soon, these things take time.",
        "classification": "UPI_FAILURE",
        "policy_checks_json": {
            "layer1": [
                {"rule_id": "NO_GUARANTEE", "passed": True, "reason_code": "N/A", "explanation": "ok"},
                {"rule_id": "NO_FRAUD_VERDICT", "passed": True, "reason_code": "N/A", "explanation": "ok"},
                {"rule_id": "CITATION_REQUIRED", "passed": False, "reason_code": "MISSING_CITATION",
                 "explanation": "No TXN ID or rule ID in reference"},
                {"rule_id": "NO_FILLER", "passed": True, "reason_code": "N/A", "explanation": "ok"},
                {"rule_id": "NO_APPROXIMATION", "passed": False, "reason_code": "APPROXIMATION_LANGUAGE",
                 "explanation": 'Approximation language: "likely"'},
                {"rule_id": "ESCALATE_HIGH_AMOUNT", "passed": True, "reason_code": "N/A", "explanation": "Below threshold"},
                {"rule_id": "ESCALATE_DISTRESS", "passed": True, "reason_code": "N/A", "explanation": "No distress keyword"},
            ],
        },
        "helpful_score": 1,
    },
]

ANNOTATIONS = [
    {
        "failure_category": "annotation:guarantee_language",
        "failure_freetext": "[anusha] Agent promised definite refund timeline — violates NPCI guidelines. Response should say 'typically resolves within T+5 business days' not 'will definitely be refunded'.",
        "classification": "guarantee_language",
        "response_text": "Guarantee language in UPI failure response — caught by NO_GUARANTEE rule",
    },
    {
        "failure_category": "annotation:generic_response",
        "failure_freetext": "[anusha] Pot withdrawal response too generic — didn't reference the specific TXN ID or NEFT settlement window. User can't tell if agent actually looked up their transaction.",
        "classification": "generic_response",
        "response_text": "Missing citation and filler opener in pot withdrawal response",
    },
    {
        "failure_category": "annotation:hallucinated_timeline",
        "failure_freetext": "[anusha] Agent used 'should probably' which gives no actionable timeline. UPI reversals follow T+5 NPCI mandate — response must cite this, not approximate.",
        "classification": "hallucinated_timeline",
        "response_text": "Approximation language instead of citing NPCI T+5 mandate",
    },
    {
        "failure_category": "annotation:wrong_category",
        "failure_freetext": "[anusha] Agent labelled a disputed charge as fraud without investigation. Policy requires neutral language until ops team confirms.",
        "classification": "wrong_category",
        "response_text": "Premature fraud verdict on disputed UPI transaction",
    },
]


def seed():
    db = get_supabase_client()

    print("Seeding users...")
    for user in USERS:
        db.table("users").upsert(user).execute()
        print(f"  {user['user_id']} — {user['name']}")

    print("Seeding transactions...")
    for txn in TRANSACTIONS:
        db.table("transactions").upsert(txn).execute()
        print(f"  {txn['txn_id']} — {txn['merchant']} ₹{txn['amount']}")

    print("Seeding eval traces with policy failures...")
    for trace in EVAL_TRACES:
        db.table("eval_queue").insert(trace).execute()
        failed = [c for c in trace["policy_checks_json"]["layer1"] if not c["passed"]]
        label = "PASS" if not failed else ", ".join(c["rule_id"] for c in failed)
        print(f"  {trace['classification']} — {label}")

    print("Seeding annotations...")
    for ann in ANNOTATIONS:
        db.table("eval_queue").insert(ann).execute()
        mode = ann["failure_category"].replace("annotation:", "")
        print(f"  {mode} — annotated")

    print("Seed complete.")


if __name__ == "__main__":
    seed()

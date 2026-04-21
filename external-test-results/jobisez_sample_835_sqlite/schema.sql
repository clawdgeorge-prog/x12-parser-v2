-- X12 Parser — SQLite Import Schema
-- Version: 0.2.1
-- Usage:
--   sqlite3 output.db < schema.sql
--   sqlite3 output.db -cmd ".import claims_835.csv claims_835" .quit
--   (repeat .import for each CSV file)
--
-- Or use the --format sqlite option of the CLI which generates all files at once.

-- interchanges (one row per ISA envelope)
CREATE TABLE IF NOT EXISTS interchanges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interchange_ctrl TEXT,
    isa_sender TEXT,
    isa_receiver TEXT,
    isa_date TEXT,
    isa_time TEXT,
    gs_count INTEGER
);

-- functional_groups (one row per GS envelope)
CREATE TABLE IF NOT EXISTS functional_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interchange_ctrl TEXT,
    gs_ctrl TEXT,
    gs_type TEXT,
    gs_sender TEXT,
    gs_receiver TEXT,
    gs_date TEXT,
    gs_version TEXT,
    transaction_count INTEGER
);

-- transactions (one row per ST/SE transaction set)
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interchange_ctrl TEXT,
    gs_ctrl TEXT,
    st_ctrl TEXT,
    set_id TEXT,
    payment_amount REAL,
    total_billed_amount REAL,
    total_paid_amount REAL,
    claim_count INTEGER,
    loop_count INTEGER,
    -- summary JSON stored as text for flexibility
    summary_json TEXT
);

-- claims_835 (one row per CLP loop from 835 transactions)
CREATE TABLE IF NOT EXISTS claims_835 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interchange_ctrl TEXT,
    isa_sender TEXT,
    isa_receiver TEXT,
    gs_ctrl TEXT,
    gs_version TEXT,
    st_ctrl TEXT,
    transaction_type TEXT,
    claim_id TEXT,
    status_code TEXT,
    status_label TEXT,
    status_category TEXT,
    patient_name TEXT,
    clp_billed REAL,
    clp_allowed REAL,
    clp_paid REAL,
    clp_adjustment REAL,
    svc_billed REAL,
    svc_paid REAL,
    service_line_count INTEGER,
    has_billed_discrepancy INTEGER,
    has_paid_discrepancy INTEGER,
    adjustment_group_codes TEXT,
    payer_name TEXT,
    provider_name TEXT,
    payment_amount REAL,
    check_trace TEXT,
    bpr_payment_method TEXT
);

-- claims_837 (one row per CLM loop from 837 transactions)
CREATE TABLE IF NOT EXISTS claims_837 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interchange_ctrl TEXT,
    isa_sender TEXT,
    isa_receiver TEXT,
    gs_ctrl TEXT,
    gs_version TEXT,
    st_ctrl TEXT,
    transaction_type TEXT,
    claim_id TEXT,
    variant TEXT,
    variant_indicator TEXT,
    clp_billed REAL,
    total_svc_billed REAL,
    total_svc_paid REAL,
    service_line_count INTEGER,
    has_discrepancy INTEGER,
    discrepancy_reason TEXT,
    billing_provider TEXT,
    payer_name TEXT,
    submitter_name TEXT,
    subscriber_name TEXT,
    patient_name TEXT,
    bht_id TEXT,
    bht_date TEXT
);

-- service_lines (one row per service line from both 835 and 837)
CREATE TABLE IF NOT EXISTS service_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interchange_ctrl TEXT,
    isa_sender TEXT,
    gs_version TEXT,
    st_ctrl TEXT,
    transaction_type TEXT,
    claim_id TEXT,
    line_number INTEGER,
    procedure_code TEXT,
    billed REAL,
    paid REAL
);

-- entities (one row per NM1 loop from both 835 and 837)
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interchange_ctrl TEXT,
    isa_sender TEXT,
    isa_receiver TEXT,
    gs_version TEXT,
    st_ctrl TEXT,
    transaction_type TEXT,
    loop_id TEXT,
    loop_kind TEXT,
    entity_code TEXT,
    entity_type TEXT,
    nm1_e1_entity_id TEXT,
    nm1_e2_type_qualifier TEXT,
    name_last_org TEXT,
    name_first TEXT,
    name_middle TEXT,
    identification_code TEXT
);

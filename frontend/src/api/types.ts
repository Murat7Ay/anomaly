export type Severity = "INFO" | "WARNING" | "CRITICAL";
export type Priority = "P1" | "P2" | "P3" | "P4";
export type IncidentStatus = "OPEN" | "ACKNOWLEDGED" | "RESOLVED";
export type OccStatus = "PENDING" | "AT_RISK" | "RECEIVED" | "LATE" | "MISSING" | "UNSCHEDULED";

export interface User {
  username: string;
  display_name: string;
  role: "ANALYST" | "APPROVER" | "ADMIN";
}

export interface Finding {
  code: string;
  category: string;
  severity: Severity;
  message: string;
  metric: string | null;
  observed: number | null;
  expected: number | null;
  lower: number | null;
  upper: number | null;
  score: number | null;
  evidence: Record<string, unknown>;
}

export interface Incident {
  id: string;
  number: number;
  kind: "OCCURRENCE" | "SYSTEMIC";
  title: string;
  status: IncidentStatus;
  severity: Severity;
  priority: Priority;
  category: string;
  codes: string[];
  institution_id: string | null;
  institution: string | null;
  occurrence_id: string | null;
  parent_id: string | null;
  impact_customers: number | null;
  impact_amount: number | null;
  opened_at: string;
  updated_at: string;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  assignee: string | null;
  resolved_at: string | null;
  resolved_by: string | null;
  resolution: string | null;
  resolution_note: string | null;
}

export interface IncidentEvent {
  at: string;
  actor: string;
  kind: string;
  message: string;
  data: Record<string, unknown>;
}

export interface SeriesPoint {
  occurrence_id: string;
  date: string;
  slot_key: string;
  status: OccStatus;
  expected_slot: boolean;
  observed: number | null;
  expected: number | null;
  lower: number | null;
  upper: number | null;
  learning: boolean;
  arrival: number | null;
  deadline: number | null;
  window_start: number | null;
  max_severity: Severity | null;
  excluded: boolean;
  regime_break: boolean;
  incident_id: string | null;
  incident_status: IncidentStatus | null;
  resolution: string | null;
}

export interface LoadRow {
  id: string;
  received_at: string;
  file_name: string | null;
  record_count: number;
  total_amount: number;
  customer_count: number;
  assignment_reason: string | null;
  content_hash: string;
}

export interface IncidentDetail extends Incident {
  events: IncidentEvent[];
  children: Incident[];
  institution_detail?: { id: string; code: string; name: string; tier: number; sector: string; contact_email: string | null };
  occurrence?: {
    id: string;
    slot_key: string;
    slot_label: string;
    business_date: string;
    status: OccStatus;
    expected: boolean;
    window_start_utc: string | null;
    deadline_utc: string | null;
    first_received_at: string | null;
    metrics: Record<string, number>;
    baselines: Record<string, any>;
    findings: Finding[];
    spec_hash: string | null;
    excluded: boolean;
    regime_break: boolean;
    loads: LoadRow[];
  };
  series?: SeriesPoint[];
}

export interface Brief {
  runbook: { summary: string; customer_impact: string; likely_causes: string[]; recommended_checks: string[] };
  ai: null | {
    summary: string;
    customer_impact: string;
    likely_causes: string[];
    recommended_checks: string[];
    confidence: "low" | "medium" | "high";
    model: string | null;
    provider: string;
    generated_at: string;
    grounding: { status: "GROUNDED" | "UNVERIFIED_NUMBERS"; checked_numbers: number; unverified: number[] } | null;
  };
  ai_status: "OK" | "FALLBACK" | "ERROR" | "NOT_REQUESTED";
  ai_error: string | null;
  disclaimer: string;
}

export interface BoardItem {
  occurrence_id: string;
  institution_id: string;
  institution: string;
  code: string;
  tier: number;
  slot_key: string;
  slot_label: string;
  window_start: number | null;
  deadline: number | null;
  status: OccStatus;
  first_received: number | null;
  max_severity: Severity | null;
  incident_id: string | null;
  incident_priority: Priority | null;
}

export interface Overview {
  as_of: string;
  business_date: string;
  open_incidents: Partial<Record<Priority, number>>;
  today: { expected: number; by_status: Partial<Record<OccStatus, number>> };
  last_30_days: {
    on_time_rate: number | null;
    late: number;
    missing: number;
    deliveries: number;
    median_minutes_to_acknowledge: number | null;
    median_minutes_to_resolve: number | null;
  };
  board: BoardItem[];
}

export interface InstitutionHealth {
  id: string;
  code: string;
  name: string;
  sector: string;
  tier: number;
  active: boolean;
  contract_version: number | null;
  cadence: string | null;
  on_time_rate_30d: number | null;
  late_30d: number;
  missing_30d: number;
  open_incidents: number;
  last_delivery_at: string | null;
  today: OccStatus[];
}

export interface Slot {
  key: string;
  label: string;
  cadence: "BUSINESS_DAYS" | "EVERY_DAY" | "WEEKLY" | "MONTHLY";
  weekdays: number[] | null;
  month_days: number[] | null;
  last_business_day: boolean;
  holiday_shift: "NEXT_BUSINESS_DAY" | "PREVIOUS_BUSINESS_DAY" | "SKIP" | "NONE";
  window_start: string;
  deadline: string;
  grace_minutes: number;
}

export interface MetricWatch {
  metric: "record_count" | "total_amount" | "customer_count" | "avg_amount";
  sensitivity: "LOW" | "MEDIUM" | "HIGH";
  direction: "BOTH" | "LOW_ONLY" | "HIGH_ONLY";
}

export interface HardLimit {
  id: string;
  metric: string;
  min: number | null;
  max: number | null;
  severity: "WARNING" | "CRITICAL";
  note: string | null;
}

export interface ContractSpec {
  schema_version: 1;
  timezone: string;
  calendar: string;
  slots: Slot[];
  metrics: MetricWatch[];
  limits: HardLimit[];
  quality: {
    detect_duplicate_file: boolean;
    detect_stale_data: boolean;
    detect_unit_scale: boolean;
    max_zero_amount_ratio: number;
    max_duplicate_record_ratio: number;
    forbid_negative_amounts: boolean;
    unexpected_delivery: "IGNORE" | "INFO" | "WARNING";
  };
  learning: { lookback_days: number; min_history: number };
}

export interface Backtest {
  period: { start: string; end: string; days: number };
  candidate: { alerting_occurrences: number; by_code: Record<string, number> };
  current: { alerting_occurrences: number; by_code: Record<string, number> } | null;
  verdicts: {
    true_positive_total: number;
    caught_by_candidate: number;
    caught_by_current: number | null;
    false_alarm_total: number;
    false_alarms_remaining_candidate: number;
    false_alarms_remaining_current: number | null;
  };
  changes: { slot_key: string; business_date: string; current: string[]; candidate: string[] }[];
  changes_total: number;
  current_version?: number | null;
}

export interface ContractVersion {
  id: string;
  institution_id: string;
  version: number;
  status: "DRAFT" | "PENDING_APPROVAL" | "APPROVED" | "REJECTED" | "WITHDRAWN";
  effective_from: string;
  spec: ContractSpec;
  spec_hash: string;
  origin: string;
  change_note: string | null;
  created_by: string;
  created_at: string | null;
  submitted_at: string | null;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  backtest: Backtest | null;
}

export interface InstitutionDetail {
  id: string;
  code: string;
  name: string;
  sector: string;
  tier: number;
  active: boolean;
  contact_email: string | null;
  notes: string | null;
  contract: ContractVersion | null;
}

export interface Suggestion {
  key: string;
  title: string;
  rationale: string;
  false_alarms: number;
  confirmed: number;
  proposed_spec: ContractSpec;
}

export interface Meta {
  ai_enabled: boolean;
  ai_provider: string;
  resolutions: Record<string, string>;
  now: string;
}

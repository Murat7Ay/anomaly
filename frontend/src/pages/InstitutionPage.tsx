import React, { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  CircularProgress,
  Divider,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography
} from "@mui/material";
import { apiFetch, ApiError } from "../lib/http";
import { JsonEditor } from "../components/JsonEditor";

type Institution = {
  id: string;
  external_code: string;
  display_name: string;
  active: boolean;
  default_timezone?: string | null;
  default_calendar_id?: string | null;
};

type ProfileVersion = {
  id: string;
  institution_id: string;
  version_num: number;
  status: string;
  effective_from: string;
  effective_to?: string | null;
  config_hash: string;
  config_json: any;
  created_by: string;
  created_at_utc: string;
  approved_at_utc?: string | null;
  approved_by?: string | null;
  approval_reason?: string | null;
};

type DslVersion = {
  id: string;
  institution_id: string;
  version_num: number;
  status: string;
  effective_from: string;
  effective_to?: string | null;
  rules_hash: string;
  rules_json: any;
  compiled_hash?: string | null;
  compiled_json?: any | null;
  validation_report_json?: any | null;
  created_by: string;
  created_at_utc: string;
  approved_at_utc?: string | null;
  approved_by?: string | null;
  approval_reason?: string | null;
};

export function InstitutionPage() {
  const { institutionId } = useParams();
  const [tab, setTab] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [inst, setInst] = useState<Institution | null>(null);

  const today = useMemo(() => new Date().toISOString().slice(0, 10), []);
  const [asOf, setAsOf] = useState(today);

  // Profile state
  const [profileEffective, setProfileEffective] = useState<ProfileVersion | null>(null);
  const [profileVersions, setProfileVersions] = useState<ProfileVersion[]>([]);
  const [profileDraftEffectiveFrom, setProfileDraftEffectiveFrom] = useState(today);
  const [profileDraftJson, setProfileDraftJson] = useState<string>("{}");
  const [profileApprovalReason, setProfileApprovalReason] = useState("");
  const [profileStatsJson, setProfileStatsJson] = useState<string>("");
  const [profileStatsError, setProfileStatsError] = useState<string | null>(null);

  // DSL state
  const [dslEffective, setDslEffective] = useState<DslVersion | null>(null);
  const [dslVersions, setDslVersions] = useState<DslVersion[]>([]);
  const [dslDraftEffectiveFrom, setDslDraftEffectiveFrom] = useState(today);
  const [dslDraftJson, setDslDraftJson] = useState<string>(
    JSON.stringify(
      {
        schema_version: 1,
        rules: [
          {
            id: "no_data_pm",
            enabled: true,
            description: "Expect load by PM run; if missing => NO_DATA",
            type: "EXPECT_LOAD_BY_RUN",
            anomaly_type: "NO_DATA",
            message: "Expected load by PM but no data present",
            params: { schedule: { source: "PROFILE" }, run: "PM_1400", include_collisions: true }
          }
        ]
      },
      null,
      2
    )
  );
  const [dslSandboxCasesJson, setDslSandboxCasesJson] = useState<string>(
    JSON.stringify(
      [
        {
          as_of_date: today,
          run_type: "PM_1400",
          has_load: false,
          load_count: 0,
          earliest_received_minutes: null,
          metrics: { debt_item_count: 0 }
        }
      ],
      null,
      2
    )
  );
  const [dslApprovalReason, setDslApprovalReason] = useState("");
  const [dslSandboxResult, setDslSandboxResult] = useState<string>("");

  async function loadAll() {
    if (!institutionId) return;
    setLoading(true);
    setError(null);
    try {
      const i = await apiFetch<Institution>(`/institutions/${institutionId}`);
      setInst(i);

      const pv = await apiFetch<ProfileVersion[]>(`/institutions/${institutionId}/profile/versions`);
      setProfileVersions(pv);

      try {
        const eff = await apiFetch<ProfileVersion>(`/institutions/${institutionId}/profile/effective`, {
          query: { as_of: asOf }
        });
        setProfileEffective(eff);
        setProfileDraftJson(JSON.stringify(eff.config_json, null, 2));
      } catch (e: any) {
        setProfileEffective(null);
      }

      const dv = await apiFetch<DslVersion[]>(`/institutions/${institutionId}/dsl/versions`);
      setDslVersions(dv);

      try {
        const deff = await apiFetch<DslVersion>(`/institutions/${institutionId}/dsl/effective`, {
          query: { as_of: asOf }
        });
        setDslEffective(deff);
        setDslDraftJson(JSON.stringify(deff.rules_json, null, 2));
      } catch (e: any) {
        setDslEffective(null);
      }
    } catch (e: any) {
      setError(e instanceof ApiError ? `${e.message}: ${e.bodyText}` : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [institutionId]);

  async function refreshEffective() {
    await loadAll();
  }

  async function createProfileDraft() {
    if (!institutionId) return;
    setError(null);
    try {
      const config = JSON.parse(profileDraftJson);
      await apiFetch<ProfileVersion>(`/institutions/${institutionId}/profile/draft`, {
        method: "POST",
        body: { effective_from: profileDraftEffectiveFrom, config }
      });
      await loadAll();
    } catch (e: any) {
      setError(e instanceof ApiError ? `${e.message}: ${e.bodyText}` : String(e));
    }
  }

  async function approveProfile(versionId: string) {
    if (!institutionId) return;
    setError(null);
    try {
      await apiFetch<ProfileVersion>(`/institutions/${institutionId}/profile/versions/${versionId}/approve`, {
        method: "POST",
        body: { approval_reason: profileApprovalReason || null }
      });
      setProfileApprovalReason("");
      await loadAll();
    } catch (e: any) {
      setError(e instanceof ApiError ? `${e.message}: ${e.bodyText}` : String(e));
    }
  }

  async function loadProfileStats() {
    if (!institutionId) return;
    setProfileStatsError(null);
    setProfileStatsJson("");
    try {
      const snap = await apiFetch<any>(`/institutions/${institutionId}/profile/stats`, { query: { as_of: asOf } });
      setProfileStatsJson(JSON.stringify(snap, null, 2));
    } catch (e: any) {
      setProfileStatsError(e instanceof ApiError ? `${e.message}: ${e.bodyText}` : String(e));
    }
  }

  async function createDslDraft() {
    if (!institutionId) return;
    setError(null);
    try {
      const rules_json = JSON.parse(dslDraftJson);
      await apiFetch<DslVersion>(`/institutions/${institutionId}/dsl/draft`, {
        method: "POST",
        body: { effective_from: dslDraftEffectiveFrom, rules_json }
      });
      await loadAll();
    } catch (e: any) {
      setError(e instanceof ApiError ? `${e.message}: ${e.bodyText}` : String(e));
    }
  }

  async function validateDsl(versionId: string) {
    if (!institutionId) return;
    setError(null);
    try {
      await apiFetch<DslVersion>(`/institutions/${institutionId}/dsl/versions/${versionId}/validate`, {
        method: "POST",
        body: {}
      });
      await loadAll();
    } catch (e: any) {
      setError(e instanceof ApiError ? `${e.message}: ${e.bodyText}` : String(e));
    }
  }

  async function approveDsl(versionId: string) {
    if (!institutionId) return;
    setError(null);
    try {
      await apiFetch<DslVersion>(`/institutions/${institutionId}/dsl/versions/${versionId}/approve`, {
        method: "POST",
        body: { approval_reason: dslApprovalReason || null }
      });
      setDslApprovalReason("");
      await loadAll();
    } catch (e: any) {
      setError(e instanceof ApiError ? `${e.message}: ${e.bodyText}` : String(e));
    }
  }

  async function runDslSandbox() {
    if (!institutionId) return;
    setError(null);
    setDslSandboxResult("");
    try {
      const rules_json = JSON.parse(dslDraftJson);
      const test_cases = JSON.parse(dslSandboxCasesJson);
      const res = await apiFetch<any>(`/institutions/${institutionId}/dsl/sandbox`, {
        method: "POST",
        body: { rules_json, test_cases }
      });
      setDslSandboxResult(JSON.stringify(res, null, 2));
    } catch (e: any) {
      setError(e instanceof ApiError ? `${e.message}: ${e.bodyText}` : String(e));
    }
  }

  if (loading) {
    return (
      <Stack direction="row" spacing={1} alignItems="center">
        <CircularProgress size={18} />
        <Typography>Loading institution...</Typography>
      </Stack>
    );
  }

  if (!inst) {
    return <Alert severity="error">{error || "Institution not found"}</Alert>;
  }

  return (
    <Stack spacing={2}>
      <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" alignItems={{ xs: "flex-start", md: "center" }} spacing={2}>
        <Box>
          <Typography variant="h5" sx={{ fontWeight: 800 }}>
            {inst.display_name}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Code: {inst.external_code} • InstitutionId: {inst.id}
          </Typography>
        </Box>
        <Stack direction="row" spacing={1} alignItems="center">
          <TextField
            label="As Of Date"
            type="date"
            value={asOf}
            onChange={(e) => setAsOf(e.target.value)}
            InputLabelProps={{ shrink: true }}
            size="small"
          />
          <Button variant="outlined" onClick={refreshEffective}>
            Refresh
          </Button>
        </Stack>
      </Stack>

      {error && <Alert severity="error">{error}</Alert>}

      <Card>
        <CardContent>
          <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
            <Tab label="Institution Profile" />
            <Tab label="DSL Rules" />
          </Tabs>

          {tab === 0 && (
            <Stack spacing={2}>
              <Alert severity="info">
                Profile changes are versioned and require approval. Draft creation/approval requires Settings with valid <b>X-Actor-Id</b>.
              </Alert>

              <Divider />
              <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                Effective Profile (as_of={asOf})
              </Typography>
              {profileEffective ? (
                <JsonEditor
                  label={`Effective config_json (version ${profileEffective.version_num}, ${profileEffective.status})`}
                  value={JSON.stringify(profileEffective.config_json, null, 2)}
                  onChange={() => {}}
                  readOnly
                />
              ) : (
                <Alert severity="warning">No effective profile found for this date.</Alert>
              )}

              <Divider />
              <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                Create Profile Draft
              </Typography>
              <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
                <TextField
                  label="effective_from"
                  type="date"
                  value={profileDraftEffectiveFrom}
                  onChange={(e) => setProfileDraftEffectiveFrom(e.target.value)}
                  InputLabelProps={{ shrink: true }}
                  fullWidth
                />
                <Button variant="contained" onClick={createProfileDraft}>
                  Create Draft
                </Button>
              </Stack>
              <JsonEditor label="Draft config_json" value={profileDraftJson} onChange={setProfileDraftJson} height={280} />

              <Divider />
              <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                Profile Versions
              </Typography>
              <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems="center">
                <TextField
                  label="Approval reason (optional)"
                  value={profileApprovalReason}
                  onChange={(e) => setProfileApprovalReason(e.target.value)}
                  fullWidth
                />
              </Stack>
              <Stack spacing={1}>
                {profileVersions.map((v) => (
                  <Card key={v.id} variant="outlined">
                    <CardContent>
                      <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" spacing={1}>
                        <Box>
                          <Typography sx={{ fontWeight: 700 }}>
                            v{v.version_num} • {v.status} • effective_from={v.effective_from}
                          </Typography>
                          <Typography variant="body2" color="text.secondary">
                            created_by={v.created_by} • approved_by={v.approved_by || "-"} • hash={v.config_hash.slice(0, 12)}…
                          </Typography>
                        </Box>
                        <Stack direction="row" spacing={1}>
                          {v.status === "DRAFT" && (
                            <Button variant="contained" onClick={() => approveProfile(v.id)}>
                              Approve
                            </Button>
                          )}
                        </Stack>
                      </Stack>
                    </CardContent>
                  </Card>
                ))}
              </Stack>

              <Divider />
              <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                Profile Stats Snapshot (as_of={asOf})
              </Typography>
              <Stack direction="row" spacing={1}>
                <Button variant="outlined" onClick={loadProfileStats}>
                  Load / Compute Snapshot
                </Button>
              </Stack>
              {profileStatsError && <Alert severity="warning">{profileStatsError}</Alert>}
              {profileStatsJson && (
                <JsonEditor label="Stats snapshot response" value={profileStatsJson} onChange={setProfileStatsJson} height={320} />
              )}
            </Stack>
          )}

          {tab === 1 && (
            <Stack spacing={2}>
              <Alert severity="info">
                DSL rules are <b>highest priority</b>. Any matching rule finalizes an anomaly as <b>CRITICAL</b>. Use Validate + Sandbox before approval.
              </Alert>

              <Divider />
              <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                Effective DSL (as_of={asOf})
              </Typography>
              {dslEffective ? (
                <Stack spacing={1}>
                  <Typography variant="body2" color="text.secondary">
                    version {dslEffective.version_num} • status {dslEffective.status} • compiled_hash {dslEffective.compiled_hash?.slice(0, 12) || "-"}…
                  </Typography>
                  <JsonEditor
                    label="Effective rules_json"
                    value={JSON.stringify(dslEffective.rules_json, null, 2)}
                    onChange={() => {}}
                    readOnly
                    height={260}
                  />
                  {dslEffective.validation_report_json && (
                    <JsonEditor
                      label="Validation report"
                      value={JSON.stringify(dslEffective.validation_report_json, null, 2)}
                      onChange={() => {}}
                      readOnly
                      height={220}
                    />
                  )}
                </Stack>
              ) : (
                <Alert severity="warning">No effective DSL found for this date.</Alert>
              )}

              <Divider />
              <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                Create DSL Draft
              </Typography>
              <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
                <TextField
                  label="effective_from"
                  type="date"
                  value={dslDraftEffectiveFrom}
                  onChange={(e) => setDslDraftEffectiveFrom(e.target.value)}
                  InputLabelProps={{ shrink: true }}
                  fullWidth
                />
                <Button variant="contained" onClick={createDslDraft}>
                  Create Draft
                </Button>
              </Stack>
              <JsonEditor label="Draft rules_json" value={dslDraftJson} onChange={setDslDraftJson} height={300} />

              <Divider />
              <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                DSL Versions
              </Typography>
              <TextField
                label="Approval reason (optional)"
                value={dslApprovalReason}
                onChange={(e) => setDslApprovalReason(e.target.value)}
                fullWidth
              />
              <Stack spacing={1}>
                {dslVersions.map((v) => (
                  <Card key={v.id} variant="outlined">
                    <CardContent>
                      <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" spacing={1}>
                        <Box>
                          <Typography sx={{ fontWeight: 700 }}>
                            v{v.version_num} • {v.status} • effective_from={v.effective_from}
                          </Typography>
                          <Typography variant="body2" color="text.secondary">
                            created_by={v.created_by} • approved_by={v.approved_by || "-"} • rules_hash={v.rules_hash.slice(0, 12)}…
                          </Typography>
                        </Box>
                        <Stack direction="row" spacing={1}>
                          {v.status === "DRAFT" && (
                            <>
                              <Button variant="outlined" onClick={() => validateDsl(v.id)}>
                                Validate
                              </Button>
                              <Button variant="contained" onClick={() => approveDsl(v.id)}>
                                Approve
                              </Button>
                            </>
                          )}
                        </Stack>
                      </Stack>
                      {v.validation_report_json && (
                        <Box sx={{ mt: 1 }}>
                          <JsonEditor
                            label="validation_report_json"
                            value={JSON.stringify(v.validation_report_json, null, 2)}
                            onChange={() => {}}
                            readOnly
                            height={220}
                          />
                        </Box>
                      )}
                    </CardContent>
                  </Card>
                ))}
              </Stack>

              <Divider />
              <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                DSL Sandbox Test
              </Typography>
              <JsonEditor
                label="test_cases (array)"
                value={dslSandboxCasesJson}
                onChange={setDslSandboxCasesJson}
                height={220}
              />
              <Stack direction="row" spacing={1}>
                <Button variant="contained" onClick={runDslSandbox}>
                  Run Sandbox
                </Button>
              </Stack>
              {dslSandboxResult && (
                <JsonEditor label="Sandbox result" value={dslSandboxResult} onChange={setDslSandboxResult} height={360} />
              )}
            </Stack>
          )}
        </CardContent>
      </Card>
    </Stack>
  );
}



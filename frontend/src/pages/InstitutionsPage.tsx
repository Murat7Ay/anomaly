import React, { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Card,
  CardContent,
  CircularProgress,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography
} from "@mui/material";
import { Link as RouterLink } from "react-router-dom";
import { apiFetch, ApiError } from "../lib/http";

type Institution = {
  id: string;
  external_code: string;
  display_name: string;
  active: boolean;
  default_timezone?: string | null;
  default_calendar_id?: string | null;
};

export function InstitutionsPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [institutions, setInstitutions] = useState<Institution[]>([]);

  const [createOpen, setCreateOpen] = useState(false);
  const [externalCode, setExternalCode] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [defaultTimezone, setDefaultTimezone] = useState("Europe/Istanbul");
  const [defaultCalendarId, setDefaultCalendarId] = useState("");

  const canCreate = useMemo(() => externalCode.trim().length > 0 && displayName.trim().length > 0, [
    externalCode,
    displayName
  ]);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch<Institution[]>("/institutions");
      setInstitutions(res);
    } catch (e: any) {
      setError(e instanceof ApiError ? `${e.message}: ${e.bodyText}` : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function createInstitution() {
    setError(null);
    try {
      await apiFetch<Institution>("/institutions", {
        method: "POST",
        body: {
          external_code: externalCode.trim(),
          display_name: displayName.trim(),
          default_timezone: defaultTimezone.trim() || null,
          default_calendar_id: defaultCalendarId.trim() || null
        }
      });
      setCreateOpen(false);
      setExternalCode("");
      setDisplayName("");
      setDefaultCalendarId("");
      await load();
    } catch (e: any) {
      setError(e instanceof ApiError ? `${e.message}: ${e.bodyText}` : String(e));
    }
  }

  return (
    <Stack spacing={2}>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Typography variant="h5" sx={{ fontWeight: 800 }}>
          Institutions
        </Typography>
        <Stack direction="row" spacing={1}>
          <Button variant="outlined" onClick={load} disabled={loading}>
            Refresh
          </Button>
          <Button variant="contained" onClick={() => setCreateOpen((v) => !v)}>
            {createOpen ? "Close" : "Create"}
          </Button>
        </Stack>
      </Stack>

      {error && <Alert severity="error">{error}</Alert>}

      {createOpen && (
        <Card>
          <CardContent>
            <Stack spacing={2}>
              <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                Create Institution
              </Typography>
              <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
                <TextField
                  label="External Code"
                  value={externalCode}
                  onChange={(e) => setExternalCode(e.target.value)}
                  fullWidth
                />
                <TextField
                  label="Display Name"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  fullWidth
                />
              </Stack>
              <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
                <TextField
                  label="Default Timezone"
                  value={defaultTimezone}
                  onChange={(e) => setDefaultTimezone(e.target.value)}
                  fullWidth
                />
                <TextField
                  label="Default Calendar ID (optional)"
                  value={defaultCalendarId}
                  onChange={(e) => setDefaultCalendarId(e.target.value)}
                  placeholder="UUID"
                  fullWidth
                />
              </Stack>
              <Stack direction="row" justifyContent="flex-end">
                <Button variant="contained" onClick={createInstitution} disabled={!canCreate}>
                  Create
                </Button>
              </Stack>
              <Alert severity="info">
                Note: Writes require your Settings to include a valid <b>X-Actor-Id</b> and <b>X-Internal-API-Key</b>.
              </Alert>
            </Stack>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent>
          {loading ? (
            <Stack direction="row" spacing={1} alignItems="center">
              <CircularProgress size={18} />
              <Typography>Loading...</Typography>
            </Stack>
          ) : (
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Code</TableCell>
                  <TableCell>Name</TableCell>
                  <TableCell>Active</TableCell>
                  <TableCell>Timezone</TableCell>
                  <TableCell>Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {institutions.map((i) => (
                  <TableRow key={i.id} hover>
                    <TableCell>{i.external_code}</TableCell>
                    <TableCell>{i.display_name}</TableCell>
                    <TableCell>{i.active ? "Yes" : "No"}</TableCell>
                    <TableCell>{i.default_timezone || "-"}</TableCell>
                    <TableCell>
                      <Button
                        component={RouterLink}
                        to={`/institutions/${i.id}`}
                        size="small"
                        variant="outlined"
                      >
                        Open
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </Stack>
  );
}



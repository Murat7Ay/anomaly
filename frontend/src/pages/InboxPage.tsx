import {
  Box,
  Card,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
  alpha,
} from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { BoardItem, Incident, Overview } from "../api/types";
import { CodeChip, Empty, ErrorBox, IncidentStatusChip, Kpi, Loading, PriorityChip, Section } from "../components/bits";
import { ago, dateOnly, hhmm, minutes, num, OCC_STATUS_LABEL, pct } from "../lib/fmt";
import { STATUS_COLOR } from "../theme";

function BoardTile({ b }: { b: BoardItem }) {
  const color = STATUS_COLOR[b.status] ?? "#90a4ae";
  const nav = useNavigate();
  const detail =
    b.first_received != null
      ? `Geldi ${hhmm(b.first_received)}`
      : b.status === "MISSING"
        ? `Son teslim ${hhmm(b.deadline)} geçti`
        : `Pencere ${hhmm(b.window_start)}–${hhmm(b.deadline)}`;
  return (
    <Tooltip title={`${b.institution} · ${b.slot_label} · ${OCC_STATUS_LABEL[b.status]}`}>
      <Card
        onClick={() => nav(b.incident_id ? `/incidents/${b.incident_id}` : `/institutions/${b.institution_id}`)}
        sx={{
          cursor: "pointer",
          p: 1.25,
          borderLeft: `4px solid ${color}`,
          bgcolor: b.status === "MISSING" || b.status === "AT_RISK" ? alpha(color, 0.07) : undefined,
          "&:hover": { boxShadow: 2 },
        }}
      >
        <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1}>
          <Typography variant="body2" fontWeight={650} noWrap>
            {b.institution}
          </Typography>
          {b.incident_priority && <PriorityChip p={b.incident_priority} />}
        </Stack>
        <Stack direction="row" justifyContent="space-between">
          <Typography variant="caption" sx={{ color }} fontWeight={700}>
            {OCC_STATUS_LABEL[b.status]}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {detail}
          </Typography>
        </Stack>
      </Card>
    </Tooltip>
  );
}

export function InboxPage() {
  const [statusFilter, setStatusFilter] = useState<"active" | "all">("active");
  const [q, setQ] = useState("");
  const overview = useQuery({ queryKey: ["overview"], queryFn: () => api<Overview>("/overview"), refetchInterval: 30_000 });
  const incidents = useQuery({
    queryKey: ["incidents", statusFilter, q],
    queryFn: () =>
      api<{ total: number; items: Incident[] }>("/incidents", {
        query: { status: statusFilter === "active" ? ["OPEN", "ACKNOWLEDGED"] : undefined, q, limit: 100 },
      }),
    refetchInterval: 30_000,
  });

  const o = overview.data;
  const open = o?.open_incidents ?? {};
  const totalOpen = Object.values(open).reduce((a, b) => a + (b ?? 0), 0);
  const ordered = [...(o?.board ?? [])].sort((a, b) => {
    const rank = (s: string) => ({ MISSING: 0, AT_RISK: 1, LATE: 2, PENDING: 3, UNSCHEDULED: 4, RECEIVED: 5 })[s] ?? 9;
    return rank(a.status) - rank(b.status) || (a.deadline ?? 0) - (b.deadline ?? 0);
  });

  return (
    <Stack spacing={2.5}>
      <Box>
        <Typography variant="h5">Gelen kutusu</Typography>
        <Typography color="text.secondary" variant="body2">
          {o ? `${dateOnly(o.business_date)} · Bugün beklenen ${o.today.expected} teslimat` : "Yükleniyor…"} · Öncelik =
          şiddet × kurum kritikliği × etkilenen müşteri
        </Typography>
      </Box>

      {overview.isError && <ErrorBox error={overview.error} />}
      <Stack direction="row" spacing={1.5} useFlexGap flexWrap="wrap">
        <Kpi
          label="Açık olay"
          value={totalOpen}
          tone={open.P1 ? "#c62828" : undefined}
          hint={`P1 ${open.P1 ?? 0} · P2 ${open.P2 ?? 0} · P3 ${open.P3 ?? 0}`}
        />
        <Kpi
          label="Bugün"
          value={`${o?.today.by_status.RECEIVED ?? 0}/${o?.today.expected ?? 0}`}
          hint={`Gelmedi ${o?.today.by_status.MISSING ?? 0} · Risk ${o?.today.by_status.AT_RISK ?? 0} · Geç ${o?.today.by_status.LATE ?? 0}`}
        />
        <Kpi
          label="Zamanında teslim (30 gün)"
          value={pct(o?.last_30_days.on_time_rate)}
          hint={`${num(o?.last_30_days.deliveries)} teslimat · ${o?.last_30_days.missing ?? 0} gelmedi`}
        />
        <Kpi label="Üstlenme süresi (medyan)" value={minutes(o?.last_30_days.median_minutes_to_acknowledge)} hint="Son 30 gün" />
        <Kpi label="Çözüm süresi (medyan)" value={minutes(o?.last_30_days.median_minutes_to_resolve)} hint="Son 30 gün" />
      </Stack>

      <Section title="Bugünün teslimat panosu">
        {overview.isLoading ? (
          <Loading rows={2} />
        ) : ordered.length === 0 ? (
          <Empty>Bugün için beklenen teslimat yok (hafta sonu/tatil olabilir).</Empty>
        ) : (
          <Box sx={{ display: "grid", gap: 1, gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))" }}>
            {ordered.map((b) => (
              <BoardTile key={b.occurrence_id} b={b} />
            ))}
          </Box>
        )}
      </Section>

      <Section
        title={`Olay kuyruğu${incidents.data ? ` (${incidents.data.total})` : ""}`}
        action={
          <Stack direction="row" spacing={1}>
            <TextField size="small" placeholder="Ara…" value={q} onChange={(e) => setQ(e.target.value)} sx={{ width: 180 }} />
            <ToggleButtonGroup size="small" exclusive value={statusFilter} onChange={(_, v) => v && setStatusFilter(v)}>
              <ToggleButton value="active">Açık</ToggleButton>
              <ToggleButton value="all">Tümü</ToggleButton>
            </ToggleButtonGroup>
          </Stack>
        }
      >
        {incidents.isLoading ? (
          <Loading />
        ) : incidents.isError ? (
          <ErrorBox error={incidents.error} />
        ) : incidents.data!.items.length === 0 ? (
          <Empty>Açık olay yok. Her şey yolunda görünüyor.</Empty>
        ) : (
          <Box sx={{ overflowX: "auto" }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Öncelik</TableCell>
                  <TableCell>Olay</TableCell>
                  <TableCell>Bulgular</TableCell>
                  <TableCell align="right">Etki</TableCell>
                  <TableCell>Durum</TableCell>
                  <TableCell>Açılış</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {incidents.data!.items.map((i) => (
                  <TableRow key={i.id} hover sx={{ cursor: "pointer", "& a": { color: "inherit", textDecoration: "none" } }}>
                    <TableCell>
                      <PriorityChip p={i.priority} />
                    </TableCell>
                    <TableCell sx={{ maxWidth: 520 }}>
                      <Link to={`/incidents/${i.id}`}>
                        <Typography variant="body2" fontWeight={600} noWrap title={i.title}>
                          #{i.number} {i.title}
                        </Typography>
                        {i.parent_id && (
                          <Typography variant="caption" color="text.secondary">
                            Toplu kesinti olayına bağlı
                          </Typography>
                        )}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <Stack direction="row" spacing={0.5}>
                        {i.codes.map((c) => (
                          <CodeChip key={c} code={c} />
                        ))}
                      </Stack>
                    </TableCell>
                    <TableCell align="right">
                      <Typography variant="body2" noWrap>{i.impact_customers ? `${num(i.impact_customers)} müşteri` : "—"}</Typography>
                    </TableCell>
                    <TableCell>
                      <IncidentStatusChip s={i.status} resolution={i.resolution} />
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" color="text.secondary" noWrap>
                        {ago(i.opened_at)}
                        {i.assignee ? ` · ${i.assignee}` : ""}
                      </Typography>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Box>
        )}
      </Section>
    </Stack>
  );
}

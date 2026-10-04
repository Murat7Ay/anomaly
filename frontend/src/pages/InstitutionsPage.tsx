import { Box, LinearProgress, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { InstitutionHealth } from "../api/types";
import { ErrorBox, Loading, OccStatusChip, Section } from "../components/bits";
import { ago, pct, SECTOR_LABEL } from "../lib/fmt";

export function InstitutionsPage() {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const data = useQuery({ queryKey: ["institutions"], queryFn: () => api<InstitutionHealth[]>("/institutions"), refetchInterval: 60_000 });
  const rows = (data.data ?? []).filter((r) => `${r.name} ${r.code}`.toLowerCase().includes(q.toLowerCase()));

  return (
    <Stack spacing={2}>
      <Box>
        <Typography variant="h5">Kurumlar</Typography>
        <Typography variant="body2" color="text.secondary">
          Kritiklik 1 = en kritik. Zamanında teslim oranı son 30 gündeki teslimatlara göredir.
        </Typography>
      </Box>
      <Section title={`${rows.length} kurum`} action={<TextField size="small" placeholder="Ara…" value={q} onChange={(e) => setQ(e.target.value)} />}>
        {data.isLoading ? (
          <Loading />
        ) : data.isError ? (
          <ErrorBox error={data.error} />
        ) : (
          <Box sx={{ overflowX: "auto" }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Kurum</TableCell>
                  <TableCell>Sektör</TableCell>
                  <TableCell align="center">Kritiklik</TableCell>
                  <TableCell>Teslimat</TableCell>
                  <TableCell sx={{ minWidth: 160 }}>Zamanında (30g)</TableCell>
                  <TableCell align="right">Geç / Gelmedi</TableCell>
                  <TableCell align="right">Açık olay</TableCell>
                  <TableCell>Bugün</TableCell>
                  <TableCell>Son dosya</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((r) => (
                  <TableRow key={r.id} hover sx={{ cursor: "pointer" }} onClick={() => nav(`/institutions/${r.id}`)}>
                    <TableCell>
                      <Typography variant="body2" fontWeight={600}>
                        {r.name}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {r.code} · sözleşme v{r.contract_version ?? "—"}
                      </Typography>
                    </TableCell>
                    <TableCell>{SECTOR_LABEL[r.sector] ?? r.sector}</TableCell>
                    <TableCell align="center">{r.tier}</TableCell>
                    <TableCell>
                      <Typography variant="caption">{r.cadence}</Typography>
                    </TableCell>
                    <TableCell>
                      <Stack direction="row" spacing={1} alignItems="center">
                        <LinearProgress
                          variant="determinate"
                          value={(r.on_time_rate_30d ?? 0) * 100}
                          color={(r.on_time_rate_30d ?? 1) >= 0.97 ? "success" : (r.on_time_rate_30d ?? 1) >= 0.9 ? "warning" : "error"}
                          sx={{ flex: 1, height: 6, borderRadius: 3 }}
                        />
                        <Typography variant="caption" sx={{ width: 44 }}>
                          {pct(r.on_time_rate_30d, 0)}
                        </Typography>
                      </Stack>
                    </TableCell>
                    <TableCell align="right">
                      {r.late_30d} / {r.missing_30d}
                    </TableCell>
                    <TableCell align="right">
                      <Typography fontWeight={r.open_incidents ? 700 : 400} color={r.open_incidents ? "error.main" : undefined}>
                        {r.open_incidents}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Stack direction="row" spacing={0.5}>
                        {r.today.map((s, i) => (
                          <OccStatusChip key={i} s={s} />
                        ))}
                        {r.today.length === 0 && (
                          <Typography variant="caption" color="text.secondary">
                            beklenmiyor
                          </Typography>
                        )}
                      </Stack>
                    </TableCell>
                    <TableCell>
                      <Typography variant="caption">{ago(r.last_delivery_at)}</Typography>
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

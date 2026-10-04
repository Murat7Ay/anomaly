import { Alert, Box, Grid2 as Grid, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography, useTheme } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import type { ShadowReport } from "../api/types";
import { ErrorBox, Kpi, Loading, Section } from "../components/bits";
import { CODE_LABEL, pct } from "../lib/fmt";

interface Row {
  total: number;
  precision: number | null;
  TRUE_POSITIVE?: number;
  FALSE_POSITIVE?: number;
  EXPECTED_EVENT?: number;
  NEW_NORMAL?: number;
  AUTO_CLEARED?: number;
  OPEN?: number;
}
interface Insights {
  period_days: number;
  total_incidents: number;
  by_code: (Row & { code: string })[];
  by_institution: (Row & { institution: string })[];
  weekly_volume: { week: string; count: number }[];
  auto_cleared: number;
  suppressed: number;
  simulation_quality: null | {
    note: string;
    recall_by_kind: Record<string, { caught: number; total: number }>;
    alerts: number;
    precision: number | null;
  };
}
interface TuningRow {
  institution_id: string;
  institution: string;
  key: string;
  title: string;
  rationale: string;
}

const KIND_LABEL: Record<string, string> = {
  MISSING: "Dosya gelmedi",
  LATE: "Geç teslim",
  PARTIAL: "Kısmi dosya",
  SPIKE: "Hacim sıçraması",
  UNIT_SCALE: "Kuruş/TL hatası",
  DUPLICATE_FILE: "Mükerrer dosya",
  STALE: "Güncellenmemiş veri",
  ZERO_AMOUNTS: "Sıfır tutarlar",
  NEGATIVE: "Negatif tutarlar",
  UNEXPECTED: "Takvim dışı teslimat",
  SYSTEMIC_OUTAGE: "Toplu kesinti",
  SEGMENT_SHIFT: "Segment kaybı",
};

function QualityTable({ rows, label }: { rows: (Row & { name: string })[]; label: string }) {
  return (
    <Box sx={{ overflowX: "auto" }}>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>{label}</TableCell>
            <TableCell align="right">Olay</TableCell>
            <TableCell align="right">Gerçek</TableCell>
            <TableCell align="right">Yanlış</TableCell>
            <TableCell align="right">Oto. kapandı</TableCell>
            <TableCell align="right">Kesinlik</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={r.name}>
              <TableCell sx={{ minWidth: 200 }}>{r.name}</TableCell>
              <TableCell align="right">{r.total}</TableCell>
              <TableCell align="right">{r.TRUE_POSITIVE ?? 0}</TableCell>
              <TableCell align="right">{(r.FALSE_POSITIVE ?? 0) + (r.NEW_NORMAL ?? 0)}</TableCell>
              <TableCell align="right">{r.AUTO_CLEARED ?? 0}</TableCell>
              <TableCell align="right" sx={{ fontWeight: 700, color: r.precision != null && r.precision < 0.6 ? "warning.main" : undefined }}>
                {pct(r.precision, 0)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  );
}

export function InsightsPage() {
  const theme = useTheme();
  const q = useQuery({ queryKey: ["insights"], queryFn: () => api<Insights>("/insights", { query: { days: 120 } }) });
  const tuning = useQuery({ queryKey: ["tuning"], queryFn: () => api<TuningRow[]>("/tuning") });
  const shadow = useQuery({ queryKey: ["shadow"], queryFn: () => api<ShadowReport[]>("/insights/shadow") });
  if (q.isLoading) return <Loading rows={8} />;
  if (q.isError) return <ErrorBox error={q.error} />;
  const d = q.data!;
  const labelled = d.by_code.reduce((a, r) => a + (r.TRUE_POSITIVE ?? 0) + (r.FALSE_POSITIVE ?? 0) + (r.NEW_NORMAL ?? 0), 0);
  const tp = d.by_code.reduce((a, r) => a + (r.TRUE_POSITIVE ?? 0), 0);
  const sim = d.simulation_quality;
  const simCaught = sim ? Object.values(sim.recall_by_kind).reduce((a, r) => a + r.caught, 0) : 0;
  const simTotal = sim ? Object.values(sim.recall_by_kind).reduce((a, r) => a + r.total, 0) : 0;

  return (
    <Stack spacing={2}>
      <Box>
        <Typography variant="h5">Model ve içgörüler</Typography>
        <Typography variant="body2" color="text.secondary">
          Dedektörlerin başarımı analist kararlarıyla ölçülür. Düşük kesinlik = gürültü; ayar önerileri bu veriden üretilir.
        </Typography>
      </Box>
      <Stack direction="row" spacing={1.5} useFlexGap flexWrap="wrap">
        <Kpi label={`Olay (${d.period_days} gün)`} value={d.total_incidents} hint={`${d.auto_cleared} kendiliğinden düzeldi`} />
        <Kpi label="Analist onaylı kesinlik" value={pct(labelled ? tp / labelled : null, 0)} hint={`${labelled} etiketli olay`} />
        {sim && <Kpi label="Yakalama oranı (simülasyon)" value={pct(simTotal ? simCaught / simTotal : null, 0)} hint={`${simCaught}/${simTotal} enjekte anomali`} />}
        <Kpi label="Bekleyen ayar önerisi" value={tuning.data?.length ?? "…"} />
      </Stack>

      {shadow.data?.map((r) => {
        const a = r.agreement;
        const t = r.truth;
        return (
          <Section key={r.challenger} title={`Gölge model: ${r.challenger}`}>
            <Alert severity="info" sx={{ mb: 1.5 }}>
              Gölge model aynı teslimatları ana modelle birlikte değerlendirir ama kimseyi uyarmaz. Analist kararları ve ölçümlerle
              kendini kanıtlarsa, kalite kapısından geçen normal bir sürümle ana modele terfi eder.
            </Alert>
            <Stack direction="row" spacing={1.5} useFlexGap flexWrap="wrap" sx={{ mb: 1.5 }}>
              <Kpi label="Değerlendirilen teslimat" value={r.evaluated} />
              <Kpi label="İkisi de uyardı" value={a.both ?? 0} />
              <Kpi label="Yalnız ana model" value={a.champion_only ?? 0} />
              <Kpi label="Yalnız gölge model" value={a.challenger_only ?? 0} tone="#7e57c2" />
              {t && (
                <Kpi
                  label="Yakalanan gerçek sorun (simülasyon)"
                  value={`${t.challenger_caught ?? 0} / ${t.champion_caught ?? 0}`}
                  hint={`${t.issues ?? 0} sorun · gölge / ana`}
                />
              )}
              {t && (
                <Kpi
                  label="Uyarı kesinliği (simülasyon)"
                  value={`${pct(t.challenger_alerts ? (t.challenger_true ?? 0) / t.challenger_alerts : null, 0)} / ${pct(
                    t.champion_alerts ? (t.champion_true ?? 0) / t.champion_alerts : null,
                    0,
                  )}`}
                  hint="gölge / ana"
                />
              )}
            </Stack>
            {r.only_challenger.length > 0 && (
              <>
                <Typography variant="subtitle2">Yalnızca gölge modelin uyardığı teslimatlar (incelemeye değer)</Typography>
                <Table size="small">
                  <TableBody>
                    {r.only_challenger.slice(0, 8).map((o) => (
                      <TableRow key={o.occurrence_id}>
                        <TableCell>
                          <Link to={`/institutions/${o.institution_id}`}>{o.institution}</Link>
                        </TableCell>
                        <TableCell>{o.business_date.split("-").reverse().join(".")}</TableCell>
                        <TableCell>{o.codes.map((c) => CODE_LABEL[c] ?? c).join(", ")}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </>
            )}
          </Section>
        );
      })}

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 7 }}>
          <Section title="Bulgu türüne göre başarım">
            <QualityTable rows={d.by_code.map((r) => ({ ...r, name: CODE_LABEL[r.code] ?? r.code }))} label="Bulgu" />
          </Section>
        </Grid>
        <Grid size={{ xs: 12, lg: 5 }}>
          <Section title="Haftalık olay hacmi">
            <Box sx={{ height: 260 }}>
              <ResponsiveContainer>
                <BarChart data={d.weekly_volume}>
                  <CartesianGrid stroke={theme.palette.divider} vertical={false} />
                  <XAxis dataKey="week" tickFormatter={(w: string) => w.slice(5).split("-").reverse().join(".")} tick={{ fontSize: 11 }} />
                  <YAxis allowDecimals={false} width={30} tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Bar dataKey="count" name="Olay" fill={theme.palette.primary.main} radius={[3, 3, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </Box>
          </Section>
        </Grid>
        <Grid size={{ xs: 12, lg: 7 }}>
          <Section title="Kuruma göre başarım">
            <QualityTable rows={d.by_institution.map((r) => ({ ...r, name: r.institution }))} label="Kurum" />
          </Section>
        </Grid>
        <Grid size={{ xs: 12, lg: 5 }}>
          <Stack spacing={2}>
            <Section title="Ayar önerileri">
              {tuning.data?.length ? (
                <Stack spacing={1}>
                  {tuning.data.map((t) => (
                    <Box key={t.institution_id + t.key}>
                      <Typography variant="body2" fontWeight={650}>
                        <Link to={`/institutions/${t.institution_id}`}>{t.institution}</Link>: {t.title}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {t.rationale}
                      </Typography>
                    </Box>
                  ))}
                </Stack>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  Öneri yok.
                </Typography>
              )}
            </Section>
            {sim && (
              <Section title="Dedektör doğrulaması (sentetik veri)">
                <Alert severity="info" sx={{ mb: 1 }}>
                  {sim.note}
                </Alert>
                <Table size="small">
                  <TableBody>
                    {Object.entries(sim.recall_by_kind).map(([k, r]) => (
                      <TableRow key={k}>
                        <TableCell>{KIND_LABEL[k] ?? k}</TableCell>
                        <TableCell align="right">
                          {r.caught}/{r.total}
                        </TableCell>
                        <TableCell align="right">{pct(r.total ? r.caught / r.total : null, 0)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <Typography variant="caption" color="text.secondary">
                  Uyarı kesinliği: {pct(sim.precision, 0)} ({sim.alerts} uyarı)
                </Typography>
              </Section>
            )}
          </Stack>
        </Grid>
      </Grid>
    </Stack>
  );
}

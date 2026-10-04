import {
  Alert,
  Box,
  Button,
  Card,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControlLabel,
  Grid2 as Grid,
  Radio,
  RadioGroup,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Brief, EvaluationRef, Finding, IncidentDetail, Meta, VerifyResult } from "../api/types";
import {
  AiBadge,
  CodeChip,
  ErrorBox,
  IncidentStatusChip,
  Loading,
  OccStatusChip,
  PriorityChip,
  Section,
  SeverityChip,
} from "../components/bits";
import { ArrivalChart, Legend, VolumeChart } from "../components/charts";
import { useAuth } from "../auth";
import { dateOnly, dateTime, METRIC_LABEL, money, num, num2, RESOLUTION_LABEL } from "../lib/fmt";

const RESOLUTION_HELP: Record<string, string> = {
  TRUE_POSITIVE: "Gerçek bir sorun vardı. Bu teslimat 'normal' öğrenilmez; dedektör başarısı olarak sayılır.",
  FALSE_POSITIVE: "Sorun yoktu. Ayar önerileri bu geri bildirimle oluşur (açıklama zorunlu).",
  EXPECTED_EVENT: "Önceden bilinen tek seferlik olay (kampanya, göç vb.). Öğrenmeden hariç tutulur.",
  NEW_NORMAL: "Kalıcı değişim (tarife, abone tabanı). Beklenen seviye bu teslimattan itibaren yeniden öğrenilir.",
  DUPLICATE: "Başka bir olayın tekrarı.",
};

function Why({ f }: { f: Finding }) {
  const b = (f.evidence?.baseline ?? null) as null | {
    n: number;
    k: number;
    components: Record<string, number | string | null>;
  };
  if (!b) return null;
  const c = b.components;
  const rows: [string, string][] = [
    ["Öğrenilen seviye", num(c.level as number)],
    ["Ay içi dönem etkisi", `x${num2(c.month_phase_factor as number)} (${{ START: "ay başı", MID: "ay ortası", END: "ay sonu" }[c.month_phase as string]})`],
    ["Haftanın günü etkisi", `x${num2(c.weekday_factor as number)}`],
    ["Aylık eğilim", `x${num2(c.trend_per_30d as number)}`],
    ["Geçen yıl mevsimselliği", `x${num2((c.annual_factor as number) ?? 1)}`],
    ["Doğal oynaklık", `±%${num2(c.noise_pct as number)}`],
    ["Kullanılan geçmiş", `${b.n} teslimat`],
    ["Sapma skoru", `${num2(f.score)} (eşik ±${num2(b.k)})`],
  ];
  return (
    <Box sx={{ mt: 1, p: 1.25, bgcolor: "action.hover", borderRadius: 1 }}>
      <Typography variant="caption" fontWeight={700} color="text.secondary">
        BEKLENEN DEĞER NASIL HESAPLANDI?
      </Typography>
      <Box sx={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))", gap: 0.5, mt: 0.5 }}>
        {rows.map(([k, v]) => (
          <Typography key={k} variant="caption">
            <Box component="span" color="text.secondary">
              {k}:
            </Box>{" "}
            <b>{v}</b>
          </Typography>
        ))}
      </Box>
    </Box>
  );
}

function BriefCard({ id, aiEnabled }: { id: string; aiEnabled: boolean }) {
  const qc = useQueryClient();
  const brief = useQuery({ queryKey: ["brief", id], queryFn: () => api<Brief>(`/incidents/${id}/brief`) });
  const regen = useMutation({
    mutationFn: () => api<Brief>(`/incidents/${id}/brief`, { method: "POST" }),
    onSuccess: (d) => qc.setQueryData(["brief", id], d),
  });
  if (brief.isLoading) return <Loading rows={3} />;
  if (brief.isError) return <ErrorBox error={brief.error} />;
  const b = brief.data!;
  return (
    <Stack spacing={2}>
      {b.ai ? (
        <Box>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
            <AiBadge label={`Yapay zekâ özeti · ${b.ai.model ?? b.ai.provider}`} />
            <Chip size="small" variant="outlined" label={`güven: ${{ low: "düşük", medium: "orta", high: "yüksek" }[b.ai.confidence]}`} />
          </Stack>
          {b.ai.grounding?.status === "UNVERIFIED_NUMBERS" && (
            <Alert severity="warning" icon={<WarningAmberIcon />} sx={{ mb: 1 }}>
              Metinde kaynak verilerde bulunmayan sayılar var ({b.ai.grounding.unverified.map((n) => num2(n)).join(", ")}). Bu
              ifadelere güvenmeyin; bulgular bölümündeki değerler esastır.
            </Alert>
          )}
          <Typography variant="body2" sx={{ mb: 1 }}>
            {b.ai.summary}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            {b.ai.customer_impact}
          </Typography>
          <Typography variant="caption" fontWeight={700} color="text.secondary">
            OLASI NEDENLER
          </Typography>
          <ul style={{ marginTop: 4 }}>
            {b.ai.likely_causes.map((c) => (
              <li key={c}>
                <Typography variant="body2">{c}</Typography>
              </li>
            ))}
          </ul>
          <Typography variant="caption" fontWeight={700} color="text.secondary">
            ÖNERİLEN KONTROLLER
          </Typography>
          <ul style={{ marginTop: 4 }}>
            {b.ai.recommended_checks.map((c) => (
              <li key={c}>
                <Typography variant="body2">{c}</Typography>
              </li>
            ))}
          </ul>
          <Divider sx={{ my: 1 }} />
        </Box>
      ) : (
        b.ai_status === "ERROR" && <Alert severity="info">Yapay zekâ özeti üretilemedi ({b.ai_error}). Kural tabanlı kontrol listesi aşağıda.</Alert>
      )}
      <Box>
        <Typography variant="caption" fontWeight={700} color="text.secondary">
          OPERASYON KONTROL LİSTESİ (KURAL TABANLI)
        </Typography>
        <Typography variant="body2" sx={{ mt: 0.5 }}>
          {b.runbook.customer_impact}
        </Typography>
        <Typography variant="body2" fontWeight={600} sx={{ mt: 1 }}>
          Olası nedenler
        </Typography>
        <ul style={{ marginTop: 2 }}>
          {b.runbook.likely_causes.map((c) => (
            <li key={c}>
              <Typography variant="body2">{c}</Typography>
            </li>
          ))}
        </ul>
        <Typography variant="body2" fontWeight={600}>
          Kontroller
        </Typography>
        <ol style={{ marginTop: 2 }}>
          {b.runbook.recommended_checks.map((c) => (
            <li key={c}>
              <Typography variant="body2">{c}</Typography>
            </li>
          ))}
        </ol>
      </Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Typography variant="caption" color="text.secondary" sx={{ maxWidth: 420 }}>
          {b.disclaimer}
        </Typography>
        {aiEnabled && (
          <Button size="small" startIcon={<AutoAwesomeIcon />} onClick={() => regen.mutate()} disabled={regen.isPending}>
            {b.ai ? "Yeniden üret" : "Özet üret"}
          </Button>
        )}
      </Stack>
    </Stack>
  );
}

function DecisionRecord({ evals }: { evals: EvaluationRef[] }) {
  const [res, setRes] = useState<Record<string, VerifyResult>>({});
  const verify = useMutation({
    mutationFn: (id: string) => api<VerifyResult>(`/evaluations/${id}/verify`, { method: "POST" }),
    onSuccess: (r, id) => setRes((x) => ({ ...x, [id]: r })),
  });
  return (
    <Stack spacing={1}>
      <Typography variant="caption" color="text.secondary">
        Her karar, girdilerinin değişmez bir kopyasıyla saklanır. "Doğrula" kararı bugünkü motorla aynı girdilerden yeniden üretir.
      </Typography>
      {evals.slice(0, 6).map((e) => {
        const r = res[e.id];
        return (
          <Stack key={e.id} direction="row" spacing={1} alignItems="center" justifyContent="space-between">
            <Typography variant="body2">
              {dateTime(e.evaluated_at)} · {e.trigger} · <code>{e.engine_version}</code>
            </Typography>
            {r ? (
              r.verifiable ? (
                <Chip
                  size="small"
                  color={r.reproduced && r.snapshot_integrity ? "success" : "error"}
                  label={r.reproduced && r.snapshot_integrity ? "Birebir üretildi" : "Fark var"}
                />
              ) : (
                <Chip size="small" label="Geçmiş aktarım (anlık görüntü yok)" />
              )
            ) : (
              <Button size="small" disabled={!e.verifiable || verify.isPending} onClick={() => verify.mutate(e.id)}>
                {e.verifiable ? "Doğrula" : "Anlık görüntü yok"}
              </Button>
            )}
          </Stack>
        );
      })}
    </Stack>
  );
}

export function IncidentPage() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const { user } = useAuth();
  const [resolveOpen, setResolveOpen] = useState(false);
  const [resolution, setResolution] = useState("TRUE_POSITIVE");
  const [note, setNote] = useState("");
  const [comment, setComment] = useState("");
  const q = useQuery({ queryKey: ["incident", id], queryFn: () => api<IncidentDetail>(`/incidents/${id}`) });
  const meta = useQuery({ queryKey: ["meta"], queryFn: () => api<Meta>("/meta"), staleTime: Infinity });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["incident", id] });
    qc.invalidateQueries({ queryKey: ["incidents"] });
    qc.invalidateQueries({ queryKey: ["overview"] });
  };
  const act = useMutation({
    mutationFn: (p: { path: string; body?: unknown }) => api(`/incidents/${id}/${p.path}`, { method: "POST", body: p.body ?? {} }),
    onSuccess: refresh,
  });

  if (q.isLoading) return <Loading rows={8} />;
  if (q.isError) return <ErrorBox error={q.error} />;
  const inc = q.data!;
  const occ = inc.occurrence;
  const needsNote = ["FALSE_POSITIVE", "EXPECTED_EVENT", "NEW_NORMAL"].includes(resolution);

  return (
    <Stack spacing={2}>
      <Box>
        <Button component={Link} to="/" startIcon={<ArrowBackIcon />} size="small" sx={{ mb: 1 }}>
          Gelen kutusu
        </Button>
        <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
          <PriorityChip p={inc.priority} />
          <SeverityChip s={inc.severity} />
          <IncidentStatusChip s={inc.status} resolution={inc.resolution} />
          {inc.codes.map((c) => (
            <CodeChip key={c} code={c} />
          ))}
        </Stack>
        <Typography variant="h5" sx={{ mt: 1 }}>
          #{inc.number} {inc.title}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Açıldı {dateTime(inc.opened_at)}
          {inc.assignee && ` · Sorumlu: ${inc.assignee}`}
          {inc.institution_detail && (
            <>
              {" · "}
              <Link to={`/institutions/${inc.institution_detail.id}`}>{inc.institution_detail.name}</Link> (kritiklik{" "}
              {inc.institution_detail.tier})
            </>
          )}
        </Typography>
      </Box>

      {act.isError && <ErrorBox error={act.error} />}

      <Card sx={{ p: 1.5 }}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "center" }} justifyContent="space-between">
          <Stack direction="row" spacing={3}>
            <Box>
              <Typography variant="caption" color="text.secondary">
                Etkilenen müşteri (tahmini)
              </Typography>
              <Typography variant="h6">{inc.impact_customers ? num(inc.impact_customers) : "—"}</Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">
                Etkilenen borç tutarı
              </Typography>
              <Typography variant="h6">{money(inc.impact_amount)}</Typography>
            </Box>
          </Stack>
          {inc.status !== "RESOLVED" ? (
            <Stack direction="row" spacing={1}>
              {inc.status === "OPEN" && (
                <Button variant="outlined" onClick={() => act.mutate({ path: "acknowledge" })} disabled={act.isPending}>
                  Üstlen
                </Button>
              )}
              <Button variant="contained" onClick={() => setResolveOpen(true)}>
                Karara bağla
              </Button>
            </Stack>
          ) : (
            <Alert severity="success" sx={{ py: 0 }}>
              {RESOLUTION_LABEL[inc.resolution ?? ""] ?? inc.resolution} · {inc.resolved_by} · {dateTime(inc.resolved_at)}
              {inc.resolution_note && ` — ${inc.resolution_note}`}
            </Alert>
          )}
        </Stack>
      </Card>

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 7 }}>
          <Stack spacing={2}>
            {occ && (
              <Section
                title="Bulgular"
                action={
                  <Stack direction="row" spacing={1} alignItems="center">
                    <Typography variant="caption" color="text.secondary">
                      {occ.slot_label} · {dateOnly(occ.business_date)}
                    </Typography>
                    <OccStatusChip s={occ.status} />
                  </Stack>
                }
              >
                <Stack spacing={1.5} divider={<Divider flexItem />}>
                  {occ.findings.map((f, i) => (
                    <Box key={i}>
                      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
                        <SeverityChip s={f.severity} />
                        <CodeChip code={f.code} />
                        {f.metric && (
                          <Typography variant="caption" color="text.secondary">
                            {METRIC_LABEL[f.metric] ?? f.metric}
                          </Typography>
                        )}
                      </Stack>
                      <Typography variant="body2">{f.message}</Typography>
                      <Why f={f} />
                    </Box>
                  ))}
                  {occ.findings.length === 0 && <Typography variant="body2">Güncel bulgu yok (koşul ortadan kalkmış).</Typography>}
                </Stack>
              </Section>
            )}
            {inc.series && inc.series.length > 0 && (
              <Section title="Kayıt sayısı: gözlenen ve beklenen">
                <VolumeChart data={inc.series} highlight={occ?.id} />
                <Box sx={{ mt: 1 }}>
                  <Legend />
                </Box>
                <Typography variant="subtitle2" sx={{ mt: 2 }}>
                  Varış saatleri
                </Typography>
                <ArrivalChart data={inc.series} />
              </Section>
            )}
            {occ && occ.loads.length > 0 && (
              <Section title="Alınan dosyalar">
                <Box sx={{ overflowX: "auto" }}>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>Zaman</TableCell>
                        <TableCell>Dosya</TableCell>
                        <TableCell align="right">Kayıt</TableCell>
                        <TableCell align="right">Tutar</TableCell>
                        <TableCell align="right">Müşteri</TableCell>
                        <TableCell>Eşleşme</TableCell>
                        <TableCell>İçerik özeti</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {occ.loads.map((l) => (
                        <TableRow key={l.id}>
                          <TableCell sx={{ whiteSpace: "nowrap" }}>{dateTime(l.received_at)}</TableCell>
                          <TableCell>{l.file_name}</TableCell>
                          <TableCell align="right">{num(l.record_count)}</TableCell>
                          <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>{money(l.total_amount)}</TableCell>
                          <TableCell align="right">{num(l.customer_count)}</TableCell>
                          <TableCell>{l.assignment_reason}</TableCell>
                          <TableCell sx={{ fontFamily: "monospace", fontSize: 12 }}>{l.content_hash}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </Box>
              </Section>
            )}
            {inc.children.length > 0 && (
              <Section title={`Bağlı kurum olayları (${inc.children.length})`}>
                <Stack spacing={0.5}>
                  {inc.children.map((c) => (
                    <Link key={c.id} to={`/incidents/${c.id}`}>
                      <Typography variant="body2">
                        #{c.number} {c.title}
                      </Typography>
                    </Link>
                  ))}
                </Stack>
              </Section>
            )}
          </Stack>
        </Grid>
        <Grid size={{ xs: 12, lg: 5 }}>
          <Stack spacing={2}>
            <Section title="Analiz ve öneriler">
              <BriefCard id={inc.id} aiEnabled={!!meta.data?.ai_enabled} />
            </Section>
            {inc.evaluations && inc.evaluations.length > 0 && (
              <Section title="Karar kaydı">
                <DecisionRecord evals={inc.evaluations} />
              </Section>
            )}
            <Section title="Zaman çizelgesi">
              <Stack spacing={1.25}>
                {inc.events.map((e, i) => (
                  <Box key={i} sx={{ borderLeft: 2, borderColor: "divider", pl: 1.5 }}>
                    <Typography variant="caption" color="text.secondary">
                      {dateTime(e.at)} · {e.actor} · {e.kind}
                    </Typography>
                    <Typography variant="body2">{e.message}</Typography>
                  </Box>
                ))}
              </Stack>
              <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
                <TextField
                  size="small"
                  fullWidth
                  placeholder="Not ekle (ör. kurumla görüşüldü)…"
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                />
                <Button
                  disabled={!comment.trim()}
                  onClick={() => act.mutate({ path: "comments", body: { text: comment } }, { onSuccess: () => setComment("") })}
                >
                  Ekle
                </Button>
              </Stack>
            </Section>
          </Stack>
        </Grid>
      </Grid>

      <Dialog open={resolveOpen} onClose={() => setResolveOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Olayı karara bağla</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            Kararınız sistemin öğrenmesini ve ayar önerilerini doğrudan etkiler.
          </Typography>
          <RadioGroup value={resolution} onChange={(e) => setResolution(e.target.value)}>
            {Object.keys(RESOLUTION_HELP).map((r) => (
              <FormControlLabel
                key={r}
                value={r}
                control={<Radio />}
                label={
                  <Box sx={{ py: 0.5 }}>
                    <Typography variant="body2" fontWeight={600}>
                      {RESOLUTION_LABEL[r]}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {RESOLUTION_HELP[r]}
                    </Typography>
                  </Box>
                }
              />
            ))}
          </RadioGroup>
          <TextField
            label={needsNote ? "Açıklama (zorunlu)" : "Açıklama"}
            multiline
            minRows={2}
            fullWidth
            sx={{ mt: 2 }}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setResolveOpen(false)}>Vazgeç</Button>
          <Button
            variant="contained"
            disabled={(needsNote && !note.trim()) || act.isPending || !user}
            onClick={() =>
              act.mutate({ path: "resolve", body: { resolution, note: note || null } }, { onSuccess: () => setResolveOpen(false) })
            }
          >
            Kaydet
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}

import {
  Alert,
  Box,
  Button,
  Card,
  Chip,
  Grid2 as Grid,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tabs,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import ScienceIcon from "@mui/icons-material/Science";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Backtest, ContractSpec, ContractVersion, Incident, InstitutionDetail, Meta, SeriesPoint, Suggestion } from "../api/types";
import { AiBadge, CodeChip, Empty, ErrorBox, IncidentStatusChip, Loading, OccStatusChip, PriorityChip, Section } from "../components/bits";
import { ArrivalChart, Legend, VolumeChart } from "../components/charts";
import { BacktestView, ContractEditor, ContractView, SpecDiff } from "../components/contract";
import { dateOnly, dateTime, hhmm, METRIC_LABEL, num, pct, SECTOR_LABEL } from "../lib/fmt";

const VERSION_STATUS: Record<string, string> = {
  DRAFT: "Taslak",
  PENDING_APPROVAL: "Onay bekliyor",
  APPROVED: "Onaylı",
  REJECTED: "Reddedildi",
  WITHDRAWN: "Geri çekildi",
};
const ORIGIN: Record<string, string> = {
  MANUAL: "Elle",
  INFERRED: "Geçmişten çıkarım",
  TUNING: "Geri bildirim önerisi",
  AI_ASSIST: "YZ yardımıyla",
  SEED: "İlk kurulum",
};

function Overview({ id }: { id: string }) {
  const [metric, setMetric] = useState("record_count");
  const [days, setDays] = useState(120);
  const series = useQuery({
    queryKey: ["series", id, metric, days],
    queryFn: () => api<SeriesPoint[]>(`/institutions/${id}/series`, { query: { metric, days } }),
  });
  const incidents = useQuery({
    queryKey: ["incidents", "inst", id],
    queryFn: () => api<{ total: number; items: Incident[] }>("/incidents", { query: { institution_id: id, limit: 15 } }),
  });
  const pts = series.data ?? [];
  const exp = pts.filter((p) => p.expected_slot && p.status !== "PENDING");
  const onTime = exp.length ? exp.filter((p) => p.status === "RECEIVED").length / exp.length : null;

  return (
    <Grid container spacing={2}>
      <Grid size={{ xs: 12, lg: 8 }}>
        <Section
          title="Hacim: gözlenen ve öğrenilen beklenti"
          action={
            <Stack direction="row" spacing={1}>
              <ToggleButtonGroup size="small" exclusive value={metric} onChange={(_, v) => v && setMetric(v)}>
                {["record_count", "total_amount", "customer_count"].map((m) => (
                  <ToggleButton key={m} value={m}>
                    {METRIC_LABEL[m]}
                  </ToggleButton>
                ))}
              </ToggleButtonGroup>
              <ToggleButtonGroup size="small" exclusive value={days} onChange={(_, v) => v && setDays(v)}>
                <ToggleButton value={60}>60g</ToggleButton>
                <ToggleButton value={120}>120g</ToggleButton>
                <ToggleButton value={365}>1y</ToggleButton>
              </ToggleButtonGroup>
            </Stack>
          }
        >
          {series.isLoading ? <Loading /> : <VolumeChart data={pts} height={300} />}
          <Box sx={{ mt: 1 }}>
            <Legend />
          </Box>
          <Typography variant="subtitle2" sx={{ mt: 2 }}>
            Varış saatleri (zamanında oran {pct(onTime, 0)})
          </Typography>
          <ArrivalChart data={pts} />
        </Section>
      </Grid>
      <Grid size={{ xs: 12, lg: 4 }}>
        <Section title="Son olaylar">
          {incidents.data?.items.length ? (
            <Stack spacing={1}>
              {incidents.data.items.map((i) => (
                <Card key={i.id} component={Link} to={`/incidents/${i.id}`} sx={{ p: 1, textDecoration: "none", color: "inherit" }}>
                  <Stack direction="row" spacing={0.5} alignItems="center" sx={{ mb: 0.5 }}>
                    <PriorityChip p={i.priority} />
                    <IncidentStatusChip s={i.status} resolution={i.resolution} />
                    {i.codes.slice(0, 2).map((c) => (
                      <CodeChip key={c} code={c} />
                    ))}
                  </Stack>
                  <Typography variant="caption" color="text.secondary">
                    #{i.number} · {dateTime(i.opened_at)}
                  </Typography>
                </Card>
              ))}
            </Stack>
          ) : (
            <Empty>Olay yok</Empty>
          )}
        </Section>
      </Grid>
    </Grid>
  );
}

function Deliveries({ id }: { id: string }) {
  const series = useQuery({
    queryKey: ["series", id, "record_count", 60],
    queryFn: () => api<SeriesPoint[]>(`/institutions/${id}/series`, { query: { metric: "record_count", days: 60 } }),
  });
  if (series.isLoading) return <Loading />;
  const rows = [...(series.data ?? [])].reverse();
  return (
    <Section title="Son 60 günün teslimatları">
      <Box sx={{ overflowX: "auto" }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Tarih</TableCell>
              <TableCell>Teslimat</TableCell>
              <TableCell>Durum</TableCell>
              <TableCell>Varış</TableCell>
              <TableCell align="right">Kayıt</TableCell>
              <TableCell align="right">Beklenen</TableCell>
              <TableCell>Not</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((p) => (
              <TableRow key={p.occurrence_id}>
                <TableCell>{dateOnly(p.date)}</TableCell>
                <TableCell>{p.slot_key}</TableCell>
                <TableCell>
                  <OccStatusChip s={p.status} />
                </TableCell>
                <TableCell>{hhmm(p.arrival)}</TableCell>
                <TableCell align="right">{num(p.observed)}</TableCell>
                <TableCell align="right">
                  {p.learning ? "öğreniyor" : p.expected != null ? `${num(p.expected)} (${num(p.lower)}–${num(p.upper)})` : "—"}
                </TableCell>
                <TableCell>
                  <Stack direction="row" spacing={0.5}>
                    {p.incident_id && (
                      <Button size="small" component={Link} to={`/incidents/${p.incident_id}`}>
                        olay
                      </Button>
                    )}
                    {p.excluded && <Chip size="small" label="öğrenmeden hariç" />}
                    {p.regime_break && <Chip size="small" color="secondary" label="yeni normal" />}
                  </Stack>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Box>
    </Section>
  );
}

function tomorrow(): string {
  const d = new Date(Date.now() + 86_400_000);
  return d.toLocaleDateString("sv-SE", { timeZone: "Europe/Istanbul" });
}

function ContractTab({ inst }: { inst: InstitutionDetail }) {
  const qc = useQueryClient();
  const meta = useQuery({ queryKey: ["meta"], queryFn: () => api<Meta>("/meta"), staleTime: Infinity });
  const versions = useQuery({ queryKey: ["contracts", inst.id], queryFn: () => api<ContractVersion[]>(`/institutions/${inst.id}/contracts`) });
  const suggestions = useQuery({
    queryKey: ["suggestions", inst.id],
    queryFn: () =>
      api<{ tuning: Suggestion[]; inferred: { spec: ContractSpec | null; confidence: number; rationale: string[] } }>(
        `/institutions/${inst.id}/suggestions`,
      ),
  });
  const [draft, setDraft] = useState<ContractSpec | null>(null);
  const [draftId, setDraftId] = useState<string | null>(null);
  const [origin, setOrigin] = useState("MANUAL");
  const [note, setNote] = useState("");
  const [effective, setEffective] = useState(tomorrow());
  const [bt, setBt] = useState<Backtest | null>(null);
  const [instruction, setInstruction] = useState("");
  const [assist, setAssist] = useState<{ explanation: string; assumptions: string[] } | null>(null);

  const startDraft = (spec: ContractSpec, o: string, n = "") => {
    setDraft(structuredClone(spec));
    setDraftId(null);
    setOrigin(o);
    setNote(n);
    setBt(null);
  };
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["contracts", inst.id] });
    qc.invalidateQueries({ queryKey: ["approvals"] });
  };
  const backtest = useMutation({
    mutationFn: () => api<Backtest>(`/institutions/${inst.id}/backtest`, { method: "POST", body: { spec: draft, days: 90 } }),
    onSuccess: setBt,
  });
  const save = useMutation({
    mutationFn: () => {
      const body = { spec: draft, effective_from: effective, change_note: note || null, origin };
      return draftId
        ? api<ContractVersion>(`/contracts/${draftId}`, { method: "PUT", body })
        : api<ContractVersion>(`/institutions/${inst.id}/contracts`, { method: "POST", body });
    },
    onSuccess: (cv) => {
      setDraftId(cv.id);
      invalidate();
    },
  });
  const submit = useMutation({
    mutationFn: (id: string) => api<ContractVersion>(`/contracts/${id}/submit`, { method: "POST" }),
    onSuccess: () => {
      setDraft(null);
      setDraftId(null);
      invalidate();
    },
  });
  const withdraw = useMutation({
    mutationFn: (id: string) => api(`/contracts/${id}/withdraw`, { method: "POST" }),
    onSuccess: invalidate,
  });
  const askAi = useMutation({
    mutationFn: () =>
      api<{ ok: boolean; spec?: ContractSpec; explanation?: string; assumptions?: string[]; error?: string }>(`/institutions/${inst.id}/assist`, {
        method: "POST",
        body: { instruction, base_spec: draft ?? inst.contract?.spec ?? null },
      }),
    onSuccess: (r) => {
      if (r.ok && r.spec) {
        startDraft(r.spec, "AI_ASSIST", `YZ önerisi: ${instruction}`);
        setAssist({ explanation: r.explanation ?? "", assumptions: r.assumptions ?? [] });
      }
    },
  });

  const active = inst.contract;
  return (
    <Grid container spacing={2}>
      <Grid size={{ xs: 12, lg: draft ? 7 : 8 }}>
        <Stack spacing={2}>
          {draft ? (
            <Section
              title={draftId ? "Taslak düzenleniyor (kaydedildi)" : "Yeni taslak"}
              action={
                <Stack direction="row" spacing={1}>
                  <Chip size="small" label={ORIGIN[origin]} />
                  <Button size="small" onClick={() => setDraft(null)}>
                    Kapat
                  </Button>
                </Stack>
              }
            >
              <Stack spacing={2}>
                {origin === "AI_ASSIST" && assist && (
                  <Alert severity="info" icon={<AutoAwesomeIcon />}>
                    <Stack spacing={0.5}>
                      <AiBadge />
                      <Typography variant="body2">{assist.explanation}</Typography>
                      {assist.assumptions.length > 0 && (
                        <Typography variant="caption">Varsayımlar: {assist.assumptions.join(" · ")}</Typography>
                      )}
                      <Typography variant="caption">Lütfen aşağıdaki farkları kontrol edin. Kaydedilen taslak başka bir yetkilinin onayı olmadan devreye girmez.</Typography>
                    </Stack>
                  </Alert>
                )}
                <ContractEditor spec={draft} onChange={(s) => { setDraft(s); setBt(null); }} />
                <Typography variant="subtitle2">Aktif sözleşmeye göre değişiklikler</Typography>
                <SpecDiff before={active?.spec ?? null} after={draft} />
                <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
                  <TextField size="small" type="date" label="Geçerlilik başlangıcı" InputLabelProps={{ shrink: true }} value={effective} onChange={(e) => setEffective(e.target.value)} />
                  <TextField size="small" fullWidth label="Değişiklik gerekçesi" value={note} onChange={(e) => setNote(e.target.value)} />
                </Stack>
                {(save.error || submit.error || backtest.error) && <ErrorBox error={save.error ?? submit.error ?? backtest.error} />}
                <Stack direction="row" spacing={1}>
                  <Button startIcon={<ScienceIcon />} variant="outlined" onClick={() => backtest.mutate()} disabled={backtest.isPending}>
                    {backtest.isPending ? "Test ediliyor…" : "Geriye dönük test (90 gün)"}
                  </Button>
                  <Button variant="outlined" onClick={() => save.mutate()} disabled={save.isPending || !note.trim()}>
                    Taslağı kaydet
                  </Button>
                  <Button variant="contained" disabled={!draftId || submit.isPending} onClick={() => draftId && submit.mutate(draftId)}>
                    Onaya gönder
                  </Button>
                </Stack>
                {!note.trim() && (
                  <Typography variant="caption" color="text.secondary">
                    Kaydetmek için gerekçe yazın. Onaya gönderilen her sürüm otomatik olarak geriye dönük test edilir.
                  </Typography>
                )}
                {bt && <BacktestView bt={bt} />}
              </Stack>
            </Section>
          ) : (
            <Section
              title={active ? `Aktif sözleşme v${active.version}` : "Aktif sözleşme yok"}
              action={
                active && (
                  <Button variant="outlined" size="small" onClick={() => startDraft(active.spec, "MANUAL")}>
                    Değişiklik taslağı
                  </Button>
                )
              }
            >
              {active ? (
                <>
                  <ContractView spec={active.spec} />
                  <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
                    {dateOnly(active.effective_from)} itibarıyla · hazırlayan {active.created_by} · onaylayan {active.decided_by} · özet{" "}
                    {active.spec_hash.slice(0, 10)}
                  </Typography>
                </>
              ) : (
                <Empty>Önce geçmişten çıkarılan takvimi veya elle bir taslağı kullanın.</Empty>
              )}
            </Section>
          )}
          <Section title="Sürüm geçmişi">
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Sürüm</TableCell>
                  <TableCell>Durum</TableCell>
                  <TableCell>Kaynak</TableCell>
                  <TableCell>Geçerlilik</TableCell>
                  <TableCell>Hazırlayan / Karar</TableCell>
                  <TableCell>Gerekçe</TableCell>
                  <TableCell />
                </TableRow>
              </TableHead>
              <TableBody>
                {versions.data?.map((v) => (
                  <TableRow key={v.id}>
                    <TableCell>v{v.version}</TableCell>
                    <TableCell>
                      <Chip size="small" label={VERSION_STATUS[v.status]} color={v.status === "APPROVED" ? "success" : v.status === "PENDING_APPROVAL" ? "warning" : "default"} />
                    </TableCell>
                    <TableCell>{ORIGIN[v.origin] ?? v.origin}</TableCell>
                    <TableCell>{dateOnly(v.effective_from)}</TableCell>
                    <TableCell>
                      {v.created_by}
                      {v.decided_by ? ` / ${v.decided_by}` : ""}
                    </TableCell>
                    <TableCell sx={{ maxWidth: 280 }}>
                      <Typography variant="caption">{v.change_note}</Typography>
                      {v.decision_note && (
                        <Typography variant="caption" display="block" color="text.secondary">
                          Karar notu: {v.decision_note}
                        </Typography>
                      )}
                    </TableCell>
                    <TableCell>
                      {v.status === "DRAFT" && (
                        <Button
                          size="small"
                          onClick={() => {
                            startDraft(v.spec, v.origin, v.change_note ?? "");
                            setDraftId(v.id);
                            setEffective(v.effective_from);
                          }}
                        >
                          Düzenle
                        </Button>
                      )}
                      {(v.status === "DRAFT" || v.status === "PENDING_APPROVAL") && (
                        <Button size="small" color="inherit" onClick={() => withdraw.mutate(v.id)}>
                          Geri çek
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Section>
        </Stack>
      </Grid>
      <Grid size={{ xs: 12, lg: draft ? 5 : 4 }}>
        <Stack spacing={2}>
          <Section title="Doğal dille değişiklik" action={<AiBadge label="YZ yardımcısı" />}>
            {meta.data?.ai_enabled ? (
              <Stack spacing={1}>
                <TextField
                  multiline
                  minRows={3}
                  placeholder="Ör. 'Kurum Kasım'dan itibaren dosyayı 11:00'e kadar gönderecek, toplam tutar için hassasiyeti düşür.'"
                  value={instruction}
                  onChange={(e) => setInstruction(e.target.value)}
                />
                <Button startIcon={<AutoAwesomeIcon />} variant="outlined" disabled={instruction.trim().length < 5 || askAi.isPending} onClick={() => askAi.mutate()}>
                  {askAi.isPending ? "Hazırlanıyor…" : "Taslak öner"}
                </Button>
                {askAi.data && !askAi.data.ok && <Alert severity="warning">{askAi.data.error}</Alert>}
                <Typography variant="caption" color="text.secondary">
                  Yapay zekâ yalnızca taslak önerir; şema doğrulamasından geçer, siz farkları inceleyip kaydedersiniz ve başka bir yetkili onaylar.
                </Typography>
              </Stack>
            ) : (
              <Typography variant="body2" color="text.secondary">
                Yapay zekâ sağlayıcısı yapılandırılmamış (LG_AI_PROVIDER). Form ile düzenleme ve aşağıdaki istatistiksel öneriler kullanılabilir.
              </Typography>
            )}
          </Section>
          <Section title="Geri bildirimden ayar önerileri">
            {suggestions.isLoading ? (
              <Loading rows={2} />
            ) : suggestions.data?.tuning.length ? (
              <Stack spacing={1.5}>
                {suggestions.data.tuning.map((s) => (
                  <Card key={s.key} sx={{ p: 1.5 }}>
                    <Typography variant="body2" fontWeight={650}>
                      {s.title}
                    </Typography>
                    <Typography variant="caption" color="text.secondary" display="block">
                      {s.rationale}
                    </Typography>
                    <Button size="small" sx={{ mt: 1 }} onClick={() => startDraft(s.proposed_spec, "TUNING", `${s.title}. ${s.rationale}`)}>
                      Taslağa al ve test et
                    </Button>
                  </Card>
                ))}
              </Stack>
            ) : (
              <Typography variant="body2" color="text.secondary">
                Şu an öneri yok. Analist kararları (özellikle yanlış alarm işaretlemeleri) biriktikçe burada somut eşik/saat önerileri çıkar.
              </Typography>
            )}
          </Section>
          <Section title="Geçmişten çıkarılan takvim">
            {suggestions.data?.inferred.spec ? (
              <Stack spacing={1}>
                <Typography variant="body2">Güven: {pct(suggestions.data.inferred.confidence, 0)}</Typography>
                {suggestions.data.inferred.rationale.map((r) => (
                  <Typography key={r} variant="caption" color="text.secondary" display="block">
                    • {r}
                  </Typography>
                ))}
                <Button size="small" sx={{ alignSelf: "flex-start" }} onClick={() => startDraft({ ...suggestions.data!.inferred.spec!, limits: active?.spec.limits ?? [] }, "INFERRED", "Son 180 günün teslimat örüntüsünden çıkarıldı")}>
                  Taslağa al
                </Button>
              </Stack>
            ) : (
              <Typography variant="body2" color="text.secondary">
                {suggestions.data?.inferred.rationale[0] ?? "—"}
              </Typography>
            )}
          </Section>
        </Stack>
      </Grid>
    </Grid>
  );
}

export function InstitutionPage() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const [tab, setTab] = useState(0);
  const inst = useQuery({ queryKey: ["institution", id], queryFn: () => api<InstitutionDetail>(`/institutions/${id}`) });
  if (inst.isLoading) return <Loading rows={6} />;
  if (inst.isError) return <ErrorBox error={inst.error} />;
  const i = inst.data!;
  return (
    <Stack spacing={2}>
      <Box>
        <Button startIcon={<ArrowBackIcon />} size="small" onClick={() => nav("/institutions")} sx={{ mb: 1 }}>
          Kurumlar
        </Button>
        <Typography variant="h5">{i.name}</Typography>
        <Typography variant="body2" color="text.secondary">
          {i.code} · {SECTOR_LABEL[i.sector] ?? i.sector} · kritiklik {i.tier}
          {i.contact_email && ` · ${i.contact_email}`}
        </Typography>
      </Box>
      <Tabs value={tab} onChange={(_, v) => setTab(v)}>
        <Tab label="Genel bakış" />
        <Tab label="Teslimatlar" />
        <Tab label="Sözleşme ve kurallar" />
      </Tabs>
      {tab === 0 && <Overview id={i.id} />}
      {tab === 1 && <Deliveries id={i.id} />}
      {tab === 2 && <ContractTab inst={i} />}
    </Stack>
  );
}

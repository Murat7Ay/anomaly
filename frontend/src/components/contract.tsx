import {
  Alert,
  Box,
  Button,
  Card,
  Chip,
  FormControlLabel,
  IconButton,
  MenuItem,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/DeleteOutline";
import type { Backtest, ContractSpec, HardLimit, MetricWatch, Slot } from "../api/types";
import { CODE_LABEL, dateOnly, METRIC_LABEL, pct, WEEKDAYS } from "../lib/fmt";

const CADENCE_LABEL: Record<Slot["cadence"], string> = {
  BUSINESS_DAYS: "Her iş günü",
  EVERY_DAY: "Her gün (7/24)",
  WEEKLY: "Haftalık",
  MONTHLY: "Aylık",
};
const SHIFT_LABEL: Record<Slot["holiday_shift"], string> = {
  NEXT_BUSINESS_DAY: "Sonraki iş gününe kaydır",
  PREVIOUS_BUSINESS_DAY: "Önceki iş gününe kaydır",
  SKIP: "O dönem beklenmez",
  NONE: "Tatilde de beklenir",
};
const SENS_LABEL = { LOW: "Düşük", MEDIUM: "Orta", HIGH: "Yüksek" } as const;
const DIR_LABEL = { BOTH: "İki yön", LOW_ONLY: "Yalnız düşüş", HIGH_ONLY: "Yalnız artış" } as const;
const UNEXPECTED_LABEL = { IGNORE: "Yok say", INFO: "Bilgi olarak kaydet", WARNING: "Uyarı üret" } as const;

export function describeSlot(s: Slot): string {
  let when = CADENCE_LABEL[s.cadence];
  if (s.cadence === "WEEKLY" && s.weekdays) when = `Her hafta ${s.weekdays.map((d) => WEEKDAYS[d - 1]).join(", ")}`;
  if (s.cadence === "MONTHLY") {
    const parts = [];
    if (s.month_days?.length) parts.push(`ayın ${s.month_days.join(", ")}. günü`);
    if (s.last_business_day) parts.push("ayın son iş günü");
    when = `Her ay ${parts.join(" ve ")}`;
  }
  const grace = s.grace_minutes ? ` (+${s.grace_minutes} dk tolerans)` : "";
  return `${when} · ${s.window_start.slice(0, 5)}–${s.deadline.slice(0, 5)}${grace}`;
}

export function ContractView({ spec }: { spec: ContractSpec }) {
  return (
    <Stack spacing={1.5}>
      <Box>
        <Typography variant="caption" fontWeight={700} color="text.secondary">
          TESLİMATLAR
        </Typography>
        {spec.slots.map((s) => (
          <Typography key={s.key} variant="body2">
            <b>{s.label}</b> — {describeSlot(s)} · Tatilde: {SHIFT_LABEL[s.holiday_shift].toLowerCase()}
          </Typography>
        ))}
      </Box>
      <Box>
        <Typography variant="caption" fontWeight={700} color="text.secondary">
          İZLENEN HACİMLER (öğrenilen beklentiye göre)
        </Typography>
        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mt: 0.5 }}>
          {spec.metrics.map((m) => (
            <Chip
              key={m.metric}
              size="small"
              variant="outlined"
              label={`${METRIC_LABEL[m.metric]} · hassasiyet ${SENS_LABEL[m.sensitivity]} · ${DIR_LABEL[m.direction]}`}
            />
          ))}
          {spec.metrics.length === 0 && <Typography variant="body2">—</Typography>}
        </Stack>
      </Box>
      <Box>
        <Typography variant="caption" fontWeight={700} color="text.secondary">
          VERİ KALİTESİ
        </Typography>
        <Typography variant="body2">
          Mükerrer dosya {spec.quality.detect_duplicate_file ? "✓" : "✗"} · Güncellenmemiş veri {spec.quality.detect_stale_data ? "✓" : "✗"} · Birim
          hatası {spec.quality.detect_unit_scale ? "✓" : "✗"} · Sıfır tutar ≤ {pct(spec.quality.max_zero_amount_ratio)} · Negatif tutar{" "}
          {spec.quality.forbid_negative_amounts ? "yasak" : "serbest"} · Takvim dışı teslimat: {UNEXPECTED_LABEL[spec.quality.unexpected_delivery]}
        </Typography>
      </Box>
      {spec.limits.length > 0 && (
        <Box>
          <Typography variant="caption" fontWeight={700} color="text.secondary">
            KESİN İŞ KURALLARI
          </Typography>
          {spec.limits.map((l) => (
            <Typography key={l.id} variant="body2">
              {l.id}: {METRIC_LABEL[l.metric] ?? l.metric} {l.min != null ? `≥ ${l.min}` : ""} {l.max != null ? `≤ ${l.max}` : ""} → {l.severity}
              {l.note ? ` (${l.note})` : ""}
            </Typography>
          ))}
        </Box>
      )}
      <Typography variant="caption" color="text.secondary">
        Öğrenme: son {spec.learning.lookback_days} gün, en az {spec.learning.min_history} teslimat · Saat dilimi {spec.timezone} · Takvim {spec.calendar}
      </Typography>
    </Stack>
  );
}

function flatten(o: unknown, prefix = ""): Record<string, string> {
  const out: Record<string, string> = {};
  if (o && typeof o === "object" && !Array.isArray(o)) {
    for (const [k, v] of Object.entries(o)) Object.assign(out, flatten(v, prefix ? `${prefix}.${k}` : k));
  } else if (Array.isArray(o) && o.some((x) => x && typeof x === "object")) {
    o.forEach((v, i) => {
      const key = (v as { key?: string; id?: string; metric?: string })?.key ?? (v as { id?: string })?.id ?? (v as { metric?: string })?.metric ?? i;
      Object.assign(out, flatten(v, `${prefix}[${key}]`));
    });
  } else out[prefix] = JSON.stringify(o);
  return out;
}

export function SpecDiff({ before, after }: { before: ContractSpec | null; after: ContractSpec }) {
  const a = before ? flatten(before) : {};
  const b = flatten(after);
  const keys = [...new Set([...Object.keys(a), ...Object.keys(b)])].filter((k) => a[k] !== b[k]).sort();
  if (keys.length === 0) return <Alert severity="info">Mevcut sözleşmeyle fark yok.</Alert>;
  return (
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>Alan</TableCell>
          <TableCell>Önce</TableCell>
          <TableCell>Sonra</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {keys.map((k) => (
          <TableRow key={k}>
            <TableCell sx={{ fontFamily: "monospace", fontSize: 12 }}>{k}</TableCell>
            <TableCell sx={{ color: "error.main", fontFamily: "monospace", fontSize: 12 }}>{a[k] ?? "—"}</TableCell>
            <TableCell sx={{ color: "success.main", fontFamily: "monospace", fontSize: 12 }}>{b[k] ?? "—"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export function BacktestView({ bt }: { bt: Backtest }) {
  const v = bt.verdicts;
  const delta = bt.current ? bt.candidate.alerting_occurrences - bt.current.alerting_occurrences : null;
  return (
    <Stack spacing={1.5}>
      <Typography variant="body2" color="text.secondary">
        {dateOnly(bt.period.start)} – {dateOnly(bt.period.end)} ({bt.period.days} gün) geçmiş veri yeniden oynatıldı.
      </Typography>
      <Stack direction="row" spacing={1.5} useFlexGap flexWrap="wrap">
        <Card sx={{ p: 1.5, flex: 1, minWidth: 180 }}>
          <Typography variant="caption" color="text.secondary">
            Uyarı üreten teslimat
          </Typography>
          <Typography variant="h6">
            {bt.current?.alerting_occurrences ?? "—"} → {bt.candidate.alerting_occurrences}
            {delta != null && (
              <Typography component="span" sx={{ ml: 1, color: delta <= 0 ? "success.main" : "warning.main" }}>
                ({delta > 0 ? "+" : ""}
                {delta})
              </Typography>
            )}
          </Typography>
        </Card>
        <Card sx={{ p: 1.5, flex: 1, minWidth: 180 }}>
          <Typography variant="caption" color="text.secondary">
            Onaylı gerçek sorunlar yakalanıyor
          </Typography>
          <Typography variant="h6" color={v.caught_by_candidate < (v.caught_by_current ?? v.true_positive_total) ? "error.main" : undefined}>
            {v.caught_by_candidate}/{v.true_positive_total}
            <Typography component="span" variant="body2" color="text.secondary">
              {" "}
              (şu an {v.caught_by_current ?? "—"})
            </Typography>
          </Typography>
        </Card>
        <Card sx={{ p: 1.5, flex: 1, minWidth: 180 }}>
          <Typography variant="caption" color="text.secondary">
            Bilinen yanlış alarmlar sürüyor
          </Typography>
          <Typography variant="h6">
            {v.false_alarms_remaining_candidate}/{v.false_alarm_total}
            <Typography component="span" variant="body2" color="text.secondary">
              {" "}
              (şu an {v.false_alarms_remaining_current ?? "—"})
            </Typography>
          </Typography>
        </Card>
      </Stack>
      {v.caught_by_candidate < (v.caught_by_current ?? 0) && (
        <Alert severity="warning">Bu değişiklik, analistlerin gerçek sorun olarak onayladığı bazı olayları kaçırırdı.</Alert>
      )}
      {bt.changes.length > 0 && (
        <Box sx={{ maxHeight: 220, overflow: "auto" }}>
          <Table size="small" stickyHeader>
            <TableHead>
              <TableRow>
                <TableCell>Tarih</TableCell>
                <TableCell>Mevcut</TableCell>
                <TableCell>Öneri</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {bt.changes.map((c) => (
                <TableRow key={c.business_date + c.slot_key}>
                  <TableCell>{dateOnly(c.business_date)}</TableCell>
                  <TableCell>{c.current.map((x) => CODE_LABEL[x] ?? x).join(", ") || "—"}</TableCell>
                  <TableCell>{c.candidate.map((x) => CODE_LABEL[x] ?? x).join(", ") || "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      )}
    </Stack>
  );
}

// --- editor ------------------------------------------------------------------------------------------

const t5 = (s: string) => s.slice(0, 5);
const t8 = (s: string) => (s.length === 5 ? `${s}:00` : s);

function SlotEditor({ slot, onChange, onRemove }: { slot: Slot; onChange: (s: Slot) => void; onRemove?: () => void }) {
  const set = (p: Partial<Slot>) => onChange({ ...slot, ...p });
  return (
    <Card sx={{ p: 1.5 }}>
      <Stack spacing={1.5}>
        <Stack direction="row" spacing={1}>
          <TextField size="small" label="Ad" value={slot.label} onChange={(e) => set({ label: e.target.value })} sx={{ flex: 2 }} />
          <TextField size="small" label="Anahtar" value={slot.key} onChange={(e) => set({ key: e.target.value })} sx={{ flex: 1 }} />
          {onRemove && (
            <IconButton onClick={onRemove} aria-label="kaldır">
              <DeleteIcon />
            </IconButton>
          )}
        </Stack>
        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
          <TextField
            select
            size="small"
            label="Sıklık"
            value={slot.cadence}
            sx={{ minWidth: 170 }}
            onChange={(e) => {
              const c = e.target.value as Slot["cadence"];
              set({
                cadence: c,
                weekdays: c === "WEEKLY" ? (slot.weekdays ?? [1]) : null,
                month_days: c === "MONTHLY" ? (slot.month_days ?? [1]) : null,
                last_business_day: c === "MONTHLY" ? slot.last_business_day : false,
              });
            }}
          >
            {Object.entries(CADENCE_LABEL).map(([k, v]) => (
              <MenuItem key={k} value={k}>
                {v}
              </MenuItem>
            ))}
          </TextField>
          <TextField size="small" type="time" label="Pencere başı" value={t5(slot.window_start)} onChange={(e) => set({ window_start: t8(e.target.value) })} InputLabelProps={{ shrink: true }} />
          <TextField size="small" type="time" label="Son teslim" value={t5(slot.deadline)} onChange={(e) => set({ deadline: t8(e.target.value) })} InputLabelProps={{ shrink: true }} />
          <TextField size="small" type="number" label="Tolerans (dk)" value={slot.grace_minutes} sx={{ width: 120 }} onChange={(e) => set({ grace_minutes: Number(e.target.value) })} />
          {(slot.cadence === "WEEKLY" || slot.cadence === "MONTHLY") && (
            <TextField select size="small" label="Tatile denk gelirse" value={slot.holiday_shift} sx={{ minWidth: 220 }} onChange={(e) => set({ holiday_shift: e.target.value as Slot["holiday_shift"] })}>
              {Object.entries(SHIFT_LABEL).map(([k, v]) => (
                <MenuItem key={k} value={k}>
                  {v}
                </MenuItem>
              ))}
            </TextField>
          )}
        </Stack>
        {slot.cadence === "WEEKLY" && (
          <ToggleButtonGroup size="small" value={slot.weekdays ?? []} onChange={(_, v: number[]) => v.length && set({ weekdays: [...v].sort() })}>
            {WEEKDAYS.map((d, i) => (
              <ToggleButton key={d} value={i + 1}>
                {d}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
        )}
        {slot.cadence === "MONTHLY" && (
          <Stack direction="row" spacing={2} alignItems="center">
            <TextField
              size="small"
              label="Ayın günleri (virgülle)"
              value={(slot.month_days ?? []).join(",")}
              onChange={(e) => {
                const days = e.target.value
                  .split(",")
                  .map((x) => parseInt(x.trim(), 10))
                  .filter((x) => x >= 1 && x <= 31);
                set({ month_days: days.length ? days : null });
              }}
            />
            <FormControlLabel control={<Switch checked={slot.last_business_day} onChange={(e) => set({ last_business_day: e.target.checked })} />} label="Ayın son iş günü" />
          </Stack>
        )}
        <Typography variant="caption" color="text.secondary">
          {describeSlot(slot)}
        </Typography>
      </Stack>
    </Card>
  );
}

const ALL_METRICS: MetricWatch["metric"][] = ["record_count", "total_amount", "customer_count", "avg_amount"];

export function ContractEditor({ spec, onChange }: { spec: ContractSpec; onChange: (s: ContractSpec) => void }) {
  const set = (p: Partial<ContractSpec>) => onChange({ ...spec, ...p });
  const setQ = (p: Partial<ContractSpec["quality"]>) => set({ quality: { ...spec.quality, ...p } });
  return (
    <Stack spacing={2}>
      <Typography variant="subtitle2">Teslimat takvimi</Typography>
      {spec.slots.map((s, i) => (
        <SlotEditor
          key={i}
          slot={s}
          onChange={(ns) => set({ slots: spec.slots.map((x, j) => (j === i ? ns : x)) })}
          onRemove={spec.slots.length > 1 ? () => set({ slots: spec.slots.filter((_, j) => j !== i) }) : undefined}
        />
      ))}
      <Button
        size="small"
        startIcon={<AddIcon />}
        sx={{ alignSelf: "flex-start" }}
        onClick={() =>
          set({
            slots: [
              ...spec.slots,
              {
                key: `slot-${spec.slots.length + 1}`,
                label: "Ek teslimat",
                cadence: "BUSINESS_DAYS",
                weekdays: null,
                month_days: null,
                last_business_day: false,
                holiday_shift: "NEXT_BUSINESS_DAY",
                window_start: "13:00:00",
                deadline: "16:00:00",
                grace_minutes: 0,
              },
            ],
          })
        }
      >
        Teslimat ekle
      </Button>

      <Typography variant="subtitle2">Hacim izleme</Typography>
      <Table size="small">
        <TableBody>
          {ALL_METRICS.map((m) => {
            const w = spec.metrics.find((x) => x.metric === m);
            const upd = (p: Partial<MetricWatch> | null) =>
              set({
                metrics:
                  p === null
                    ? spec.metrics.filter((x) => x.metric !== m)
                    : w
                      ? spec.metrics.map((x) => (x.metric === m ? { ...x, ...p } : x))
                      : [...spec.metrics, { metric: m, sensitivity: "MEDIUM", direction: "BOTH", ...p }],
              });
            return (
              <TableRow key={m}>
                <TableCell sx={{ width: 220 }}>
                  <FormControlLabel control={<Switch checked={!!w} onChange={(e) => upd(e.target.checked ? {} : null)} />} label={METRIC_LABEL[m]} />
                </TableCell>
                <TableCell>
                  {w && (
                    <Stack direction="row" spacing={1}>
                      <ToggleButtonGroup size="small" exclusive value={w.sensitivity} onChange={(_, v) => v && upd({ sensitivity: v })}>
                        {Object.entries(SENS_LABEL).map(([k, v]) => (
                          <ToggleButton key={k} value={k}>
                            {v}
                          </ToggleButton>
                        ))}
                      </ToggleButtonGroup>
                      <ToggleButtonGroup size="small" exclusive value={w.direction} onChange={(_, v) => v && upd({ direction: v })}>
                        {Object.entries(DIR_LABEL).map(([k, v]) => (
                          <ToggleButton key={k} value={k}>
                            {v}
                          </ToggleButton>
                        ))}
                      </ToggleButtonGroup>
                    </Stack>
                  )}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
      <Typography variant="caption" color="text.secondary">
        Hassasiyet yükseldikçe olağan aralık daralır: daha çok sorun yakalanır, daha çok yanlış alarm oluşur. Etkisini kaydetmeden önce geriye dönük testle görün.
      </Typography>

      <Typography variant="subtitle2">Veri kalitesi</Typography>
      <Stack direction="row" spacing={2} useFlexGap flexWrap="wrap" alignItems="center">
        <FormControlLabel control={<Switch checked={spec.quality.detect_duplicate_file} onChange={(e) => setQ({ detect_duplicate_file: e.target.checked })} />} label="Mükerrer dosya" />
        <FormControlLabel control={<Switch checked={spec.quality.detect_stale_data} onChange={(e) => setQ({ detect_stale_data: e.target.checked })} />} label="Güncellenmemiş veri" />
        <FormControlLabel control={<Switch checked={spec.quality.detect_unit_scale} onChange={(e) => setQ({ detect_unit_scale: e.target.checked })} />} label="Kuruş/TL birim hatası" />
        <FormControlLabel control={<Switch checked={spec.quality.forbid_negative_amounts} onChange={(e) => setQ({ forbid_negative_amounts: e.target.checked })} />} label="Negatif tutar yasak" />
        <TextField size="small" type="number" label="Azami sıfır tutar oranı (%)" sx={{ width: 200 }} value={Math.round(spec.quality.max_zero_amount_ratio * 1000) / 10} onChange={(e) => setQ({ max_zero_amount_ratio: Number(e.target.value) / 100 })} />
        <TextField select size="small" label="Takvim dışı teslimat" sx={{ width: 200 }} value={spec.quality.unexpected_delivery} onChange={(e) => setQ({ unexpected_delivery: e.target.value as ContractSpec["quality"]["unexpected_delivery"] })}>
          {Object.entries(UNEXPECTED_LABEL).map(([k, v]) => (
            <MenuItem key={k} value={k}>
              {v}
            </MenuItem>
          ))}
        </TextField>
      </Stack>

      <Typography variant="subtitle2">Kesin iş kuralları</Typography>
      {spec.limits.map((l, i) => {
        const upd = (p: Partial<HardLimit>) => set({ limits: spec.limits.map((x, j) => (j === i ? { ...x, ...p } : x)) });
        return (
          <Stack key={i} direction="row" spacing={1} useFlexGap flexWrap="wrap" alignItems="center">
            <TextField size="small" label="Kimlik" value={l.id} sx={{ width: 140 }} onChange={(e) => upd({ id: e.target.value })} />
            <TextField select size="small" label="Ölçü" value={l.metric} sx={{ width: 200 }} onChange={(e) => upd({ metric: e.target.value })}>
              {Object.entries(METRIC_LABEL).map(([k, v]) => (
                <MenuItem key={k} value={k}>
                  {v}
                </MenuItem>
              ))}
            </TextField>
            <TextField size="small" type="number" label="Alt sınır" value={l.min ?? ""} sx={{ width: 130 }} onChange={(e) => upd({ min: e.target.value === "" ? null : Number(e.target.value) })} />
            <TextField size="small" type="number" label="Üst sınır" value={l.max ?? ""} sx={{ width: 130 }} onChange={(e) => upd({ max: e.target.value === "" ? null : Number(e.target.value) })} />
            <TextField select size="small" label="Şiddet" value={l.severity} sx={{ width: 120 }} onChange={(e) => upd({ severity: e.target.value as HardLimit["severity"] })}>
              <MenuItem value="WARNING">Uyarı</MenuItem>
              <MenuItem value="CRITICAL">Kritik</MenuItem>
            </TextField>
            <TextField size="small" label="Not" value={l.note ?? ""} sx={{ flex: 1, minWidth: 160 }} onChange={(e) => upd({ note: e.target.value || null })} />
            <IconButton onClick={() => set({ limits: spec.limits.filter((_, j) => j !== i) })} aria-label="kuralı kaldır">
              <DeleteIcon />
            </IconButton>
          </Stack>
        );
      })}
      <Button
        size="small"
        startIcon={<AddIcon />}
        sx={{ alignSelf: "flex-start" }}
        onClick={() => set({ limits: [...spec.limits, { id: `kural-${spec.limits.length + 1}`, metric: "record_count", min: null, max: 1000000, severity: "CRITICAL", note: null }] })}
      >
        Kural ekle
      </Button>
    </Stack>
  );
}

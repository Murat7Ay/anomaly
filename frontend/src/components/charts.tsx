import { Box, Stack, Typography, useTheme } from "@mui/material";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { SeriesPoint } from "../api/types";
import { dateOnly, hhmm, num, OCC_STATUS_LABEL, short } from "../lib/fmt";
import { SEVERITY_COLOR, STATUS_COLOR } from "../theme";

const dayLabel = (iso: string) => iso.slice(5).split("-").reverse().join(".");

function pointColor(p: SeriesPoint): string {
  if (p.max_severity === "CRITICAL" || p.max_severity === "WARNING") return SEVERITY_COLOR[p.max_severity];
  return "#5c7cfa";
}

/** Observed volume against the learned expectation band: the core "why" picture for an analyst. */
export function VolumeChart({ data, highlight, height = 280 }: { data: SeriesPoint[]; highlight?: string; height?: number }) {
  const theme = useTheme();
  const rows = data
    .filter((p) => p.expected_slot)
    .map((p) => ({
      ...p,
      band: p.lower != null && p.upper != null ? [p.lower, p.upper] : null,
      dot: p.observed,
    }));
  if (rows.length === 0) return <Typography color="text.secondary">Veri yok</Typography>;
  return (
    <Box sx={{ width: "100%", height }}>
      <ResponsiveContainer>
        <ComposedChart data={rows} margin={{ top: 8, right: 12, left: 4, bottom: 0 }}>
          <CartesianGrid stroke={theme.palette.divider} vertical={false} />
          <XAxis dataKey="date" tickFormatter={dayLabel} minTickGap={24} tick={{ fontSize: 11 }} />
          <YAxis tickFormatter={(v: number) => short(v)} width={52} tick={{ fontSize: 11 }} />
          <Tooltip
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const p = payload[0]!.payload as SeriesPoint;
              return (
                <Box sx={{ bgcolor: "background.paper", border: 1, borderColor: "divider", p: 1, borderRadius: 1, fontSize: 12 }}>
                  <b>{dateOnly(p.date)}</b> · {OCC_STATUS_LABEL[p.status]}
                  <div>Gözlenen: {num(p.observed)}</div>
                  {p.expected != null && (
                    <div>
                      Beklenen: {num(p.expected)} ({num(p.lower)} – {num(p.upper)})
                    </div>
                  )}
                  {p.learning && <div>Öğrenme aşaması</div>}
                  {p.excluded && <div>Öğrenmeden hariç (onaylı anomali)</div>}
                  {p.regime_break && <div>Yeni normal başlangıcı</div>}
                </Box>
              );
            }}
          />
          <Area dataKey="band" stroke="none" fill={theme.palette.primary.main} fillOpacity={0.12} isAnimationActive={false} />
          <Line dataKey="expected" stroke={theme.palette.primary.main} strokeDasharray="4 3" dot={false} strokeWidth={1.5} isAnimationActive={false} />
          <Scatter
            dataKey="dot"
            isAnimationActive={false}
            shape={(props: { cx?: number; cy?: number; payload?: SeriesPoint }) => {
              const { cx, cy, payload } = props;
              if (cx == null || cy == null || !payload) return <g />;
              const big = payload.occurrence_id === highlight;
              const c = pointColor(payload);
              return (
                <circle
                  cx={cx}
                  cy={cy}
                  r={big ? 7 : payload.max_severity ? 4.5 : 3}
                  fill={payload.excluded ? "transparent" : c}
                  stroke={big ? theme.palette.text.primary : c}
                  strokeWidth={big ? 2 : 1.5}
                />
              );
            }}
          />
          {data
            .filter((p) => p.regime_break)
            .map((p) => (
              <ReferenceLine key={p.occurrence_id} x={p.date} stroke="#7e57c2" strokeDasharray="3 3" label={{ value: "yeni normal", fontSize: 10, fill: "#7e57c2" }} />
            ))}
        </ComposedChart>
      </ResponsiveContainer>
    </Box>
  );
}

/** Arrival times against the contractual window and deadline. */
export function ArrivalChart({ data, height = 220 }: { data: SeriesPoint[]; height?: number }) {
  const theme = useTheme();
  const rows = data.filter((p) => p.expected_slot);
  const deadline = rows.find((p) => p.deadline != null)?.deadline;
  const windowStart = rows.find((p) => p.window_start != null)?.window_start;
  const pts = rows.map((p) => ({ ...p, y: p.arrival ?? (p.status === "MISSING" ? (deadline ?? 0) + 60 : null) }));
  const ys = pts.map((p) => p.y).filter((v): v is number => v != null).concat(deadline ?? [], windowStart ?? []);
  const lo = ys.length ? Math.floor(Math.min(...ys) / 60) * 60 : 0;
  const hi = ys.length ? Math.ceil(Math.max(...ys) / 60) * 60 : 1440;
  const step = hi - lo > 360 ? 120 : 60;
  const ticks = Array.from({ length: Math.floor((hi - lo) / step) + 1 }, (_, i) => lo + i * step);
  return (
    <Box sx={{ width: "100%", height }}>
      <ResponsiveContainer>
        <ComposedChart data={pts} margin={{ top: 8, right: 12, left: 4, bottom: 0 }}>
          <CartesianGrid stroke={theme.palette.divider} vertical={false} />
          <XAxis dataKey="date" tickFormatter={dayLabel} minTickGap={24} tick={{ fontSize: 11 }} />
          <YAxis
            reversed
            domain={[lo, hi]}
            ticks={ticks}
            tickFormatter={(v: number) => hhmm(v)}
            width={46}
            tick={{ fontSize: 11 }}
          />
          <Tooltip
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const p = payload[0]!.payload as SeriesPoint;
              return (
                <Box sx={{ bgcolor: "background.paper", border: 1, borderColor: "divider", p: 1, borderRadius: 1, fontSize: 12 }}>
                  <b>{dateOnly(p.date)}</b> · {OCC_STATUS_LABEL[p.status]}
                  <div>Varış: {p.arrival != null ? hhmm(p.arrival) : "—"}</div>
                </Box>
              );
            }}
          />
          {windowStart != null && <ReferenceLine y={windowStart} stroke="#90a4ae" strokeDasharray="3 3" label={{ value: "pencere", fontSize: 10, position: "insideTopLeft" }} />}
          {deadline != null && <ReferenceLine y={deadline} stroke="#c62828" strokeDasharray="4 3" label={{ value: "son teslim", fontSize: 10, position: "insideBottomLeft", fill: "#c62828" }} />}
          <Scatter
            dataKey="y"
            isAnimationActive={false}
            shape={(props: { cx?: number; cy?: number; payload?: SeriesPoint }) => {
              const { cx, cy, payload } = props;
              if (cx == null || cy == null || !payload) return <g />;
              return <circle cx={cx} cy={cy} r={3.5} fill={STATUS_COLOR[payload.status] ?? "#5c7cfa"} />;
            }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </Box>
  );
}

export function Legend() {
  const item = (c: string, l: string, hollow = false) => (
    <Stack direction="row" spacing={0.5} alignItems="center" key={l}>
      <Box sx={{ width: 10, height: 10, borderRadius: "50%", bgcolor: hollow ? "transparent" : c, border: `2px solid ${c}` }} />
      <Typography variant="caption">{l}</Typography>
    </Stack>
  );
  return (
    <Stack direction="row" spacing={2} useFlexGap flexWrap="wrap">
      {item("#5c7cfa", "Normal")}
      {item(SEVERITY_COLOR.WARNING, "Uyarı")}
      {item(SEVERITY_COLOR.CRITICAL, "Kritik")}
      {item("#5c7cfa", "Öğrenmeden hariç", true)}
      <Typography variant="caption" color="text.secondary">
        Gölgeli alan: öğrenilmiş olağan aralık · kesikli çizgi: beklenen değer
      </Typography>
    </Stack>
  );
}

import { Alert, Box, Card, CardContent, Chip, Skeleton, Stack, Tooltip, Typography, alpha } from "@mui/material";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import type { ReactNode } from "react";
import type { Priority, Severity } from "../api/types";
import { CODE_LABEL, INCIDENT_STATUS_LABEL, OCC_STATUS_LABEL, RESOLUTION_LABEL } from "../lib/fmt";
import { PRIORITY_COLOR, SEVERITY_COLOR, STATUS_COLOR } from "../theme";

function Tinted({ label, color, title }: { label: string; color: string; title?: string }) {
  const chip = (
    <Chip
      size="small"
      label={label}
      sx={{ bgcolor: alpha(color, 0.14), color, border: `1px solid ${alpha(color, 0.35)}`, height: 22 }}
    />
  );
  return title ? <Tooltip title={title}>{chip}</Tooltip> : chip;
}

const PRIORITY_HELP: Record<Priority, string> = {
  P1: "Kritik ve geniş müşteri etkisi: hemen müdahale",
  P2: "Kritik veya yüksek etkili uyarı: bugün içinde",
  P3: "Uyarı: mesai içinde incelenmeli",
  P4: "Bilgi",
};

export const PriorityChip = ({ p }: { p: Priority }) => (
  <Tinted label={p} color={PRIORITY_COLOR[p]} title={PRIORITY_HELP[p]} />
);

export const SeverityChip = ({ s }: { s: Severity }) => (
  <Tinted label={{ CRITICAL: "Kritik", WARNING: "Uyarı", INFO: "Bilgi" }[s]} color={SEVERITY_COLOR[s]} />
);

export const OccStatusChip = ({ s }: { s: string }) => (
  <Tinted label={OCC_STATUS_LABEL[s] ?? s} color={STATUS_COLOR[s] ?? "#90a4ae"} />
);

export const IncidentStatusChip = ({ s, resolution }: { s: string; resolution?: string | null }) => {
  const color = s === "OPEN" ? "#c62828" : s === "ACKNOWLEDGED" ? "#1565c0" : "#2e7d32";
  const label = s === "RESOLVED" && resolution ? RESOLUTION_LABEL[resolution] ?? resolution : INCIDENT_STATUS_LABEL[s] ?? s;
  return <Tinted label={label} color={color} />;
};

export const CodeChip = ({ code }: { code: string }) => (
  <Chip size="small" variant="outlined" label={CODE_LABEL[code] ?? code} sx={{ height: 22 }} />
);

export function Kpi({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: string }) {
  return (
    <Card sx={{ flex: 1, minWidth: 160 }}>
      <CardContent sx={{ py: 1.5, "&:last-child": { pb: 1.5 } }}>
        <Typography variant="caption" color="text.secondary" fontWeight={600}>
          {label}
        </Typography>
        <Typography variant="h5" sx={{ color: tone, mt: 0.25 }}>
          {value}
        </Typography>
        {hint && (
          <Typography variant="caption" color="text.secondary">
            {hint}
          </Typography>
        )}
      </CardContent>
    </Card>
  );
}

export function Section({ title, action, children, sx }: { title: ReactNode; action?: ReactNode; children: ReactNode; sx?: object }) {
  return (
    <Card sx={sx}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ px: 2, pt: 1.5, pb: 1 }}>
        <Typography variant="subtitle1" fontWeight={650}>
          {title}
        </Typography>
        {action}
      </Stack>
      <Box sx={{ px: 2, pb: 2 }}>{children}</Box>
    </Card>
  );
}

export function Loading({ rows = 4 }: { rows?: number }) {
  return (
    <Stack spacing={1}>
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} variant="rounded" height={36} />
      ))}
    </Stack>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  return <Alert severity="error">{error instanceof Error ? error.message : "Beklenmeyen hata"}</Alert>;
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <Box sx={{ py: 4, textAlign: "center", color: "text.secondary" }}>
      <Typography variant="body2">{children}</Typography>
    </Box>
  );
}

/** Every AI-generated surface carries this badge: advisory only, never a decision. */
export function AiBadge({ label = "Yapay zekâ önerisi" }: { label?: string }) {
  return (
    <Tooltip title="Yapay zekâ yalnızca açıklama ve öneri üretir. Kararlar, kurallar ve eşikler deterministik motordan gelir; değişiklikler insan onayı olmadan uygulanmaz.">
      <Chip
        size="small"
        icon={<AutoAwesomeIcon sx={{ fontSize: 14 }} />}
        label={label}
        sx={{ height: 22, bgcolor: alpha("#7e57c2", 0.12), color: "#7e57c2", "& .MuiChip-icon": { color: "#7e57c2" } }}
      />
    </Tooltip>
  );
}

import { alpha, createTheme, type PaletteMode } from "@mui/material/styles";

export const SEVERITY_COLOR = {
  CRITICAL: "#d32f2f",
  WARNING: "#ed6c02",
  INFO: "#0288d1",
} as const;

export const PRIORITY_COLOR = { P1: "#c62828", P2: "#ef6c00", P3: "#f9a825", P4: "#78909c" } as const;

export const STATUS_COLOR: Record<string, string> = {
  RECEIVED: "#2e7d32",
  LATE: "#ef6c00",
  MISSING: "#c62828",
  AT_RISK: "#f9a825",
  PENDING: "#90a4ae",
  UNSCHEDULED: "#7e57c2",
};

export function makeTheme(mode: PaletteMode) {
  const dark = mode === "dark";
  return createTheme({
    palette: {
      mode,
      primary: { main: dark ? "#7aa7ff" : "#1f4fd1" },
      secondary: { main: "#7e57c2" },
      background: dark ? { default: "#0f1218", paper: "#161b24" } : { default: "#f4f6fa", paper: "#ffffff" },
      divider: dark ? alpha("#ffffff", 0.08) : alpha("#0b1b3f", 0.08),
    },
    shape: { borderRadius: 10 },
    typography: {
      fontFamily: "Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
      h5: { fontWeight: 700, letterSpacing: -0.3 },
      h6: { fontWeight: 650, letterSpacing: -0.2 },
      subtitle2: { fontWeight: 600 },
      button: { textTransform: "none", fontWeight: 600 },
    },
    components: {
      MuiCssBaseline: {
        styleOverrides: (t) => ({ a: { color: t.palette.primary.main, textUnderlineOffset: 2 } }),
      },
      MuiPaper: { defaultProps: { elevation: 0 }, styleOverrides: { root: { backgroundImage: "none" } } },
      MuiCard: {
        defaultProps: { variant: "outlined" },
        styleOverrides: { root: ({ theme }) => ({ borderColor: theme.palette.divider }) },
      },
      MuiChip: { styleOverrides: { root: { fontWeight: 600 } } },
      MuiTableCell: { styleOverrides: { head: { fontWeight: 650, whiteSpace: "nowrap" } } },
      MuiTooltip: { defaultProps: { arrow: true } },
    },
  });
}

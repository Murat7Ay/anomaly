import {
  AppBar,
  Avatar,
  Badge,
  Box,
  Chip,
  Drawer,
  IconButton,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Stack,
  Toolbar,
  Tooltip,
  Typography,
  useMediaQuery,
} from "@mui/material";
import { useTheme } from "@mui/material/styles";
import InboxIcon from "@mui/icons-material/Inbox";
import ApartmentIcon from "@mui/icons-material/Apartment";
import FactCheckIcon from "@mui/icons-material/FactCheck";
import InsightsIcon from "@mui/icons-material/Insights";
import MenuIcon from "@mui/icons-material/Menu";
import LogoutIcon from "@mui/icons-material/Logout";
import DarkModeIcon from "@mui/icons-material/DarkMode";
import LightModeIcon from "@mui/icons-material/LightMode";
import ShieldIcon from "@mui/icons-material/Shield";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { api } from "../api/client";
import type { ContractVersion, Meta } from "../api/types";
import { useAuth } from "../auth";
import { ROLE_LABEL } from "../lib/fmt";

const WIDTH = 232;

export function Layout({ mode, toggleMode }: { mode: "light" | "dark"; toggleMode: () => void }) {
  const { user, logout } = useAuth();
  const loc = useLocation();
  const theme = useTheme();
  const wide = useMediaQuery(theme.breakpoints.up("md"));
  const [open, setOpen] = useState(false);
  const approvals = useQuery({
    queryKey: ["approvals"],
    queryFn: () => api<ContractVersion[]>("/approvals"),
    refetchInterval: 60_000,
  });
  const meta = useQuery({ queryKey: ["meta"], queryFn: () => api<Meta>("/meta"), staleTime: Infinity });

  const nav = [
    { to: "/", label: "Gelen kutusu", icon: <InboxIcon />, match: (p: string) => p === "/" || p.startsWith("/incidents") },
    { to: "/institutions", label: "Kurumlar", icon: <ApartmentIcon />, match: (p: string) => p.startsWith("/institutions") },
    {
      to: "/approvals",
      label: "Onaylar",
      icon: (
        <Badge color="error" badgeContent={approvals.data?.length ?? 0}>
          <FactCheckIcon />
        </Badge>
      ),
      match: (p: string) => p.startsWith("/approvals"),
    },
    { to: "/insights", label: "Model & içgörü", icon: <InsightsIcon />, match: (p: string) => p.startsWith("/insights") },
  ];

  const drawer = (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ px: 2, height: 64 }}>
        <ShieldIcon color="primary" />
        <Box>
          <Typography fontWeight={800} lineHeight={1.1}>
            LoadGuard
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Borç dosyası gözetimi
          </Typography>
        </Box>
      </Stack>
      <List sx={{ px: 1 }}>
        {nav.map((n) => (
          <ListItemButton
            key={n.to}
            component={Link}
            to={n.to}
            selected={n.match(loc.pathname)}
            onClick={() => setOpen(false)}
            sx={{ borderRadius: 2, mb: 0.5 }}
          >
            <ListItemIcon sx={{ minWidth: 38 }}>{n.icon}</ListItemIcon>
            <ListItemText primary={n.label} primaryTypographyProps={{ fontWeight: 600, fontSize: 14 }} />
          </ListItemButton>
        ))}
      </List>
      <Box sx={{ flexGrow: 1 }} />
      <Box sx={{ p: 2 }}>
        <Chip
          size="small"
          variant="outlined"
          label={meta.data?.ai_enabled ? `YZ: ${meta.data.ai_provider}` : "YZ kapalı · kural tabanlı özet"}
          sx={{ mb: 1 }}
        />
        <Typography variant="caption" color="text.secondary" display="block">
          Yapay zekâ danışman rolündedir; karar yetkisi yoktur.
        </Typography>
      </Box>
    </Box>
  );

  return (
    <Box sx={{ display: "flex", minHeight: "100vh" }}>
      <Drawer
        variant={wide ? "permanent" : "temporary"}
        open={wide || open}
        onClose={() => setOpen(false)}
        sx={{ width: WIDTH, "& .MuiDrawer-paper": { width: WIDTH, boxSizing: "border-box" } }}
      >
        {drawer}
      </Drawer>
      <Box sx={{ flexGrow: 1, minWidth: 0 }}>
        <AppBar position="sticky" color="inherit" elevation={0} sx={{ borderBottom: 1, borderColor: "divider" }}>
          <Toolbar sx={{ gap: 1 }}>
            {!wide && (
              <IconButton onClick={() => setOpen(true)} edge="start" aria-label="menü">
                <MenuIcon />
              </IconButton>
            )}
            <Box sx={{ flexGrow: 1 }} />
            <Tooltip title={mode === "dark" ? "Açık tema" : "Koyu tema"}>
              <IconButton onClick={toggleMode} aria-label="tema">
                {mode === "dark" ? <LightModeIcon /> : <DarkModeIcon />}
              </IconButton>
            </Tooltip>
            {user && (
              <Stack direction="row" spacing={1} alignItems="center">
                <Avatar sx={{ width: 30, height: 30, fontSize: 13, bgcolor: "primary.main" }}>
                  {user.display_name.split(" ").map((x) => x[0]).join("")}
                </Avatar>
                <Box sx={{ display: { xs: "none", sm: "block" } }}>
                  <Typography variant="body2" fontWeight={600} lineHeight={1.1}>
                    {user.display_name}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {ROLE_LABEL[user.role]}
                  </Typography>
                </Box>
                <Tooltip title="Çıkış">
                  <IconButton onClick={logout} aria-label="çıkış">
                    <LogoutIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              </Stack>
            )}
          </Toolbar>
        </AppBar>
        <Box component="main" sx={{ p: { xs: 2, md: 3 }, maxWidth: 1500, mx: "auto" }}>
          <Outlet />
        </Box>
      </Box>
    </Box>
  );
}

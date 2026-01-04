import React, { useState } from "react";
import { Outlet, Link as RouterLink, useLocation } from "react-router-dom";
import {
  AppBar,
  Box,
  Button,
  Container,
  IconButton,
  Stack,
  Toolbar,
  Typography
} from "@mui/material";
import SettingsIcon from "@mui/icons-material/Settings";
import HomeIcon from "@mui/icons-material/Home";
import { SettingsDialog } from "./SettingsDialog";

export function AppLayout() {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const location = useLocation();

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "background.default" }}>
      <AppBar position="sticky" elevation={1}>
        <Toolbar>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ flexGrow: 1 }}>
            <HomeIcon fontSize="small" />
            <Typography variant="h6" sx={{ fontWeight: 700 }}>
              Anomaly Ops
            </Typography>
            <Button
              component={RouterLink}
              to="/"
              color="inherit"
              sx={{ textTransform: "none", opacity: location.pathname === "/" ? 1 : 0.9 }}
            >
              Institutions
            </Button>
          </Stack>
          <IconButton color="inherit" onClick={() => setSettingsOpen(true)}>
            <SettingsIcon />
          </IconButton>
        </Toolbar>
      </AppBar>

      <Container maxWidth="xl" sx={{ py: 3 }}>
        <Outlet />
      </Container>

      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </Box>
  );
}



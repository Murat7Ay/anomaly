import React, { useMemo, useState } from "react";
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  TextField,
  Typography
} from "@mui/material";
import { AppSettings, getSettings, saveSettings } from "../lib/settings";

export function SettingsDialog(props: { open: boolean; onClose: () => void }) {
  const initial = useMemo(() => getSettings(), []);
  const [settings, setSettings] = useState<AppSettings>(initial);

  return (
    <Dialog open={props.open} onClose={props.onClose} fullWidth maxWidth="sm">
      <DialogTitle>Settings</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            These values are stored in your browser localStorage.
          </Typography>
          <TextField
            label="API Base URL"
            value={settings.apiBaseUrl}
            onChange={(e) => setSettings({ ...settings, apiBaseUrl: e.target.value })}
            placeholder="http://localhost:8000"
            fullWidth
          />
          <TextField
            label="X-Internal-API-Key"
            value={settings.internalApiKey}
            onChange={(e) => setSettings({ ...settings, internalApiKey: e.target.value })}
            fullWidth
          />
          <TextField
            label="X-Actor-Id"
            value={settings.actorId}
            onChange={(e) => setSettings({ ...settings, actorId: e.target.value })}
            helperText="Required for creating/approving profile & DSL versions."
            fullWidth
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={props.onClose}>Cancel</Button>
        <Button
          variant="contained"
          onClick={() => {
            saveSettings(settings);
            props.onClose();
          }}
        >
          Save
        </Button>
      </DialogActions>
    </Dialog>
  );
}



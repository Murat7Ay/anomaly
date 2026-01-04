import React from "react";
import { Alert, Stack } from "@mui/material";

export function NotFoundPage() {
  return (
    <Stack spacing={2}>
      <Alert severity="error">Page not found.</Alert>
    </Stack>
  );
}



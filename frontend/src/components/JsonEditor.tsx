import React, { useMemo } from "react";
import { Button, Stack, TextField, Typography } from "@mui/material";

export function JsonEditor(props: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  height?: number;
  readOnly?: boolean;
}) {
  const parseError = useMemo(() => {
    try {
      JSON.parse(props.value);
      return null;
    } catch (e: any) {
      return String(e?.message || "Invalid JSON");
    }
  }, [props.value]);
  const isValid = parseError === null;

  return (
    <Stack spacing={1}>
      <Stack direction="row" spacing={1} justifyContent="space-between" alignItems="center">
        <Typography variant="subtitle2">{props.label}</Typography>
        <Stack direction="row" spacing={1}>
          <Button
            size="small"
            disabled={props.readOnly}
            onClick={() => {
              try {
                const parsed = JSON.parse(props.value);
                props.onChange(JSON.stringify(parsed, null, 2));
              } catch {
                // ignore
              }
            }}
          >
            Format
          </Button>
          <Button
            size="small"
            onClick={() => {
              navigator.clipboard.writeText(props.value);
            }}
          >
            Copy
          </Button>
        </Stack>
      </Stack>
      <TextField
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
        multiline
        minRows={Math.max(6, Math.round((props.height || 240) / 24))}
        error={!isValid}
        helperText={parseError || " "}
        disabled={props.readOnly}
        inputProps={{ style: { fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" } }}
      />
    </Stack>
  );
}



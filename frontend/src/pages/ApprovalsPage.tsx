import { Alert, Box, Button, Chip, Grid2 as Grid, Stack, TextField, Typography } from "@mui/material";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { ContractVersion } from "../api/types";
import { useAuth } from "../auth";
import { Empty, ErrorBox, Loading, Section } from "../components/bits";
import { BacktestView, ContractView, SpecDiff } from "../components/contract";
import { dateOnly, dateTime } from "../lib/fmt";

type Pending = ContractVersion & { institution: string; current: ContractVersion | null };

function ApprovalCard({ v }: { v: Pending }) {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const decide = useMutation({
    mutationFn: (approve: boolean) => api(`/contracts/${v.id}/${approve ? "approve" : "reject"}`, { method: "POST", body: { note: note || null } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["approvals"] });
      qc.invalidateQueries({ queryKey: ["contracts", v.institution_id] });
    },
  });
  const own = user?.username === v.created_by;
  const canApprove = user && (user.role === "APPROVER" || user.role === "ADMIN") && !own;

  return (
    <Section
      title={
        <span>
          <Link to={`/institutions/${v.institution_id}`}>{v.institution}</Link> · sözleşme v{v.version}
        </span>
      }
      action={<Chip size="small" color="warning" label="Onay bekliyor" />}
    >
      <Typography variant="body2" sx={{ mb: 1 }}>
        <b>{v.created_by}</b> tarafından {dateTime(v.submitted_at)} gönderildi · geçerlilik {dateOnly(v.effective_from)}
      </Typography>
      <Alert severity="info" sx={{ mb: 2 }}>
        {v.change_note ?? "Gerekçe girilmemiş."}
      </Alert>
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 6 }}>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            Değişiklikler
          </Typography>
          <SpecDiff before={v.current?.spec ?? null} after={v.spec} />
          <Typography variant="subtitle2" sx={{ mt: 2, mb: 1 }}>
            Önerilen sözleşme
          </Typography>
          <ContractView spec={v.spec} />
        </Grid>
        <Grid size={{ xs: 12, lg: 6 }}>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            Geriye dönük test
          </Typography>
          {v.backtest ? <BacktestView bt={v.backtest} /> : <Empty>Test sonucu yok</Empty>}
        </Grid>
      </Grid>
      <Box sx={{ mt: 2 }}>
        {own && <Alert severity="warning" sx={{ mb: 1 }}>Dört göz ilkesi: kendi hazırladığınız değişikliği onaylayamazsınız.</Alert>}
        {!own && !canApprove && <Alert severity="info" sx={{ mb: 1 }}>Onay için Onaycı veya Yönetici rolü gerekir.</Alert>}
        {decide.isError && <ErrorBox error={decide.error} />}
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
          <TextField size="small" fullWidth label="Karar notu (ret için zorunlu)" value={note} onChange={(e) => setNote(e.target.value)} />
          <Button variant="outlined" color="error" disabled={!canApprove || !note.trim() || decide.isPending} onClick={() => decide.mutate(false)}>
            Reddet
          </Button>
          <Button variant="contained" disabled={!canApprove || decide.isPending} onClick={() => decide.mutate(true)}>
            Onayla
          </Button>
        </Stack>
      </Box>
    </Section>
  );
}

export function ApprovalsPage() {
  const q = useQuery({ queryKey: ["approvals"], queryFn: () => api<Pending[]>("/approvals") });
  return (
    <Stack spacing={2}>
      <Box>
        <Typography variant="h5">Onaylar</Typography>
        <Typography variant="body2" color="text.secondary">
          Sözleşme değişiklikleri; hazırlayan dışında bir yetkilinin, geriye dönük test sonucunu görerek onayıyla devreye girer.
        </Typography>
      </Box>
      {q.isLoading ? <Loading /> : q.isError ? <ErrorBox error={q.error} /> : q.data!.length === 0 ? <Empty>Onay bekleyen değişiklik yok.</Empty> : q.data!.map((v) => <ApprovalCard key={v.id} v={v} />)}
    </Stack>
  );
}

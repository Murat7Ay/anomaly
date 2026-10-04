import { Alert, Box, Card, CardActionArea, CardContent, Stack, Typography } from "@mui/material";
import ShieldIcon from "@mui/icons-material/Shield";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { User } from "../api/types";
import { useAuth } from "../auth";
import { ROLE_LABEL } from "../lib/fmt";

const ROLE_HELP: Record<string, string> = {
  ANALYST: "Olayları üstlenir ve karara bağlar, sözleşme taslağı hazırlar.",
  APPROVER: "Başkasının hazırladığı sözleşme değişikliklerini onaylar (dört göz).",
  ADMIN: "Kurum tanımları ve tüm yetkiler.",
};

export function LoginPage() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [err, setErr] = useState<string | null>(null);
  const users = useQuery({ queryKey: ["dev-users"], queryFn: () => api<User[]>("/auth/dev-users") });

  return (
    <Box sx={{ minHeight: "100vh", display: "grid", placeItems: "center", p: 2 }}>
      <Box sx={{ width: "100%", maxWidth: 520 }}>
        <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 3 }}>
          <ShieldIcon color="primary" sx={{ fontSize: 40 }} />
          <Box>
            <Typography variant="h5">LoadGuard</Typography>
            <Typography color="text.secondary">Fatura borç dosyası teslim gözetimi</Typography>
          </Box>
        </Stack>
        <Alert severity="info" sx={{ mb: 2 }}>
          Geliştirme modu: bir demo kullanıcısı seçin. Üretimde giriş kurumsal kimlik sağlayıcısı (OIDC/SSO) üzerinden yapılır.
        </Alert>
        {err && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {err}
          </Alert>
        )}
        <Stack spacing={1.5}>
          {users.data?.map((u) => (
            <Card key={u.username}>
              <CardActionArea
                onClick={async () => {
                  try {
                    await login(u.username);
                    nav("/");
                  } catch (e) {
                    setErr(e instanceof Error ? e.message : "Giriş başarısız");
                  }
                }}
              >
                <CardContent>
                  <Typography fontWeight={650}>
                    {u.display_name} · {ROLE_LABEL[u.role]}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {ROLE_HELP[u.role]}
                  </Typography>
                </CardContent>
              </CardActionArea>
            </Card>
          ))}
          {users.isError && <Alert severity="error">API'ye ulaşılamıyor.</Alert>}
        </Stack>
      </Box>
    </Box>
  );
}

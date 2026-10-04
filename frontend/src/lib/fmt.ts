const nf = new Intl.NumberFormat("tr-TR");
const nf2 = new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 2 });
const compact = new Intl.NumberFormat("tr-TR", { notation: "compact", maximumFractionDigits: 1 });
const tz = "Europe/Istanbul";

export const num = (v: number | null | undefined) => (v == null ? "—" : nf.format(Math.round(v)));
export const num2 = (v: number | null | undefined) => (v == null ? "—" : nf2.format(v));
export const short = (v: number | null | undefined) => (v == null ? "—" : compact.format(v));
export const money = (v: number | null | undefined) => (v == null ? "—" : `${compact.format(v)} TL`);
export const pct = (v: number | null | undefined, d = 1) =>
  v == null ? "—" : `%${(v * 100).toLocaleString("tr-TR", { maximumFractionDigits: d })}`;

export const hhmm = (m: number | null | undefined) =>
  m == null ? "—" : `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;

export const dateTime = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleString("tr-TR", { timeZone: tz, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
    : "—";

export const dateOnly = (iso: string | null | undefined) =>
  iso ? new Date(iso.length === 10 ? `${iso}T12:00:00` : iso).toLocaleDateString("tr-TR", { timeZone: tz }) : "—";

export function ago(iso: string | null | undefined): string {
  if (!iso) return "—";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "şimdi";
  if (mins < 60) return `${mins} dk önce`;
  const h = Math.round(mins / 60);
  if (h < 48) return `${h} sa önce`;
  return `${Math.round(h / 24)} gün önce`;
}

export const minutes = (m: number | null | undefined) => {
  if (m == null) return "—";
  if (m < 60) return `${Math.round(m)} dk`;
  const h = Math.floor(m / 60);
  const r = Math.round(m % 60);
  return r ? `${h} sa ${r} dk` : `${h} sa`;
};

export const METRIC_LABEL: Record<string, string> = {
  record_count: "Kayıt sayısı",
  total_amount: "Toplam tutar",
  customer_count: "Müşteri sayısı",
  avg_amount: "Ortalama tutar",
  zero_amount_ratio: "Sıfır tutar oranı",
  negative_amount_count: "Negatif kayıt",
  duplicate_record_ratio: "Mükerrer kayıt oranı",
  max_amount: "En yüksek tutar",
};

export const CODE_LABEL: Record<string, string> = {
  MISSING_DELIVERY: "Dosya gelmedi",
  DELIVERY_AT_RISK: "Gecikme riski",
  LATE_DELIVERY: "Geç geldi",
  EARLY_DELIVERY: "Erken geldi",
  ARRIVAL_DRIFT: "Varış kayıyor",
  UNEXPECTED_DELIVERY: "Takvim dışı",
  VOLUME_LOW: "Hacim düşük",
  VOLUME_HIGH: "Hacim yüksek",
  UNIT_SCALE_SUSPECT: "Birim hatası",
  DUPLICATE_FILE: "Mükerrer dosya",
  STALE_DATA: "Güncellenmemiş veri",
  ZERO_AMOUNT_RECORDS: "Sıfır tutarlar",
  NEGATIVE_AMOUNTS: "Negatif tutarlar",
  DUPLICATE_RECORDS: "Mükerrer kayıt",
  LIMIT_BREACH: "Kural ihlali",
  SYSTEMIC_OUTAGE: "Toplu kesinti",
};

export const OCC_STATUS_LABEL: Record<string, string> = {
  PENDING: "Bekleniyor",
  AT_RISK: "Risk altında",
  RECEIVED: "Zamanında",
  LATE: "Geç geldi",
  MISSING: "Gelmedi",
  UNSCHEDULED: "Takvim dışı",
};

export const INCIDENT_STATUS_LABEL: Record<string, string> = {
  OPEN: "Açık",
  ACKNOWLEDGED: "Üstlenildi",
  RESOLVED: "Kapandı",
};

export const RESOLUTION_LABEL: Record<string, string> = {
  TRUE_POSITIVE: "Gerçek sorun",
  FALSE_POSITIVE: "Yanlış alarm",
  EXPECTED_EVENT: "Bilinen olay",
  NEW_NORMAL: "Yeni normal",
  DUPLICATE: "Tekrar",
  AUTO_CLEARED: "Kendiliğinden düzeldi",
  SUPPRESSED: "Bastırıldı",
};

export const SECTOR_LABEL: Record<string, string> = {
  ELECTRICITY: "Elektrik",
  GAS: "Doğalgaz",
  WATER: "Su",
  TELECOM: "Telekom",
  MEDIA: "Yayın",
  EDUCATION: "Eğitim",
  PUBLIC: "Kamu",
  INSURANCE: "Sigorta",
  HEATING: "Isınma",
};

export const ROLE_LABEL: Record<string, string> = { ANALYST: "Analist", APPROVER: "Onaycı", ADMIN: "Yönetici" };

export const WEEKDAYS = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"];

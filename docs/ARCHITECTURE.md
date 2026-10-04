# Mimari

```
            ┌───────────────┐  POST /ingest/loads (X-Api-Key, idempotent)
SFTP/API ──▶│  Alım kenarı  │─────────────────────────────┐
            │ (parser, ileride) │                          ▼
            └───────────────┘                 ┌──────────────────────┐
                                              │ api (FastAPI)        │◀── web (React, nginx) ◀── Analist / Onaycı
                                              │  • REST /api/v1      │       OIDC/SSO (üretim)
                                              │  • RFC 9457 hatalar  │
                                              └─────────┬────────────┘
                                                        │ tek transaction (unit of work)
                                              ┌─────────▼────────────┐
                                              │ PostgreSQL 16        │  veri + iş kuyruğu (SKIP LOCKED)
                                              └─────────▲────────────┘  + advisory lock (lider seçimi)
                                                        │
                                              ┌─────────┴────────────┐
                                              │ worker               │  EVALUATE_LOAD · AI_BRIEF · NOTIFY
                                              │  • son teslim taraması│  materialize · sweep · systemic
                                              └─────────┬────────────┘
                                                        │ yalnızca danışman
                                              ┌─────────▼────────────┐
                                              │ LLM sağlayıcı        │  none | on-prem (OpenAI uyumlu) | Claude
                                              └──────────────────────┘
```

## Katmanlar (backend/src/loadguard)

| Paket | Sorumluluk | Kural |
|---|---|---|
| `domain/` | Takvim, sözleşme, eşleme, baseline, dedektörler, motor, öncelik, replay, backtest, çıkarım, ayar önerisi | **Saf.** I/O, ORM ve saat yok (`now` parametre olarak gelir). %100 birim test edilebilir. |
| `services/` | Girdileri yükler, motoru çağırır, sonucu ve olayları yazar | İş akışı burada; karar mantığı burada değil |
| `ai/` | Sağlayıcı, olay özeti, sözleşme yardımcısı, doğrulama (grounding) | Hiçbir şeye yazma yetkisi yok (yalnızca `ai_interactions`) |
| `api/` | HTTP, kimlik, rol, şema | İnce katman |
| `worker/` | Kuyruk tüketimi ve periyodik işler | Çoklu worker güvenli |
| `sim/` | Etiketli simülatör, kalite ölçümü, demo seed | Üretimde kullanılmaz |

## Mimari kararlar (ADR)

**ADR-1 · Saf tespit motoru.** Canlı akış, geriye dönük test ve simülasyon aynı `evaluate()` fonksiyonunu çağırır. Böylece "test ettiğim kural canlıda başka davranır" sorunu ortadan kalkar ve her karar yeniden üretilebilir.

**ADR-2 · Yalnızca PostgreSQL (Redis/Celery yok).** Bu yükte (kurum × gün başına birkaç teslimat) Postgres hem veri hem kuyruk olarak yeterlidir: `FOR UPDATE SKIP LOCKED`, `dedupe_key` ile tekilleştirme ve advisory lock ile tek lider. Tek bir sistem yedeklenir, izlenir ve denetlenir. Ölçek gerekince kuyruk Kafka'ya taşınır; motor aynı kalır.

**ADR-3 · Teslimat (occurrence) değerlendirme birimidir.** Dosya değil beklenti modellenir. "Gelmeyen dosya" ancak böyle tespit edilebilir, kısmi ve tamamlayıcı dosyalar da doğal olarak birleşir.

**ADR-4 · Durum mutabakatı (reconciliation).** Her değerlendirme olayları güncel bulgularla uzlaştırır: yeni ise açar, değiştiyse günceller, kaybolduysa otomatik kapatır. Analistin kapattığı olay aynı bulgu için tekrar açılmaz.

**ADR-5 · Açıklanabilir istatistik, kara kutu ML yok.** Bkz. DOMAIN.md §4.2. Model değişiklikleri kalite kapısından geçmek zorundadır.

**ADR-6 · Yapay zekâ danışmandır.** Bkz. DOMAIN.md §7. Sağlayıcı arayüzü dar tutulur (`complete_json`). Testler sahte sağlayıcıyla çalışır.

**ADR-7 · Kimlik ve yetki ayrımı.** Kimlik IdP'den (OIDC, JWKS ile doğrulanır), rol uygulamanın tablosundan gelir. Geliştirme modunda parolasız demo girişi vardır (`LG_AUTH_MODE=dev`). Token'lar sistem saatiyle değil gerçek saatle üretilir, simüle saat güvenliği etkilemez.

**ADR-8 · Zaman.** Tüm zaman damgaları UTC `timestamptz` olarak tutulur. İş günü ve yerel saat hesapları `Europe/Istanbul` ile yapılır. Sistem saati `core/clock.py` üzerinden alınır, bu sayede testler ve replay saati kontrol edebilir.

## Kalite güvencesi
- `pytest`: alan birim testleri, Postgres'e karşı entegrasyon testleri (canlı akış, dört göz, sistemik kesinti, YZ güvenlik önlemleri), dedektör kalite kapısı.
- `mypy --strict`, `ruff`; frontend `tsc --strict`.
- CI: `.github/workflows/ci.yml`.

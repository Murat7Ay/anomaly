# LoadGuard: Borç Dosyası Teslim Gözetimi

> ⚠️ **Deneysel proje.** Bu depo kişisel bir deneme ve öğrenme çalışmasıdır. Üretimde kullanılmak üzere hazırlanmamıştır. İçindeki tüm kurum adları, kişiler ve veriler **sentetiktir**. Gösterilen başarı ölçümleri simülasyondan gelir, gerçek dünya performansı değildir.

Fatura tahsilatında kurumlar (elektrik, su, doğalgaz, telekom, kamu…) tahsil edilecek borçları her gün **borç dosyası** olarak gönderir. Dosya gelmezse, geç gelirse, eksik, mükerrer, güncellenmemiş ya da hatalı gelirse müşteri borcunu ödeyemez veya yanlış tutar görür.

LoadGuard bu dosyaları izler. Sorunları **tespit eder, nedenini açıklar, etkisine göre önceliklendirir**, analistin kararından **öğrenir**; yapay zekâyı yalnızca **danışman** olarak kullanır.

| | |
|---|---|
| İş analizi | [docs/DOMAIN.md](docs/DOMAIN.md) |
| Mimari ve kararlar (ADR) | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| 10 yıllık tasarım ve yol haritası | [docs/LONGEVITY.md](docs/LONGEVITY.md) |

---

## Nasıl çalışır: aşama aşama

```
 ①  Alım  ──▶ ②  Eşleme ──▶ ③  Değerlendirme ──▶ ④  Önceliklendirme ──▶ ⑤  Olay yönetimi ──▶ ⑥  Öğrenme ──▶ ⑦  Yönetişim
 (dosya özeti)  (hangi teslimat?)  (kurallar + istatistik)  (etki × kritiklik)   (analist + YZ özeti)  (karar → ayar)  (onay, kanıt)
```

| Aşama | Ne yapılıyor | Yöntem | Teknoloji / kod |
|---|---|---|---|
| **① Alım** | Kurumun dosyası alınır. Sisteme ham dosya değil, yalnızca **özeti** gelir: kayıt, tutar, müşteri, sıfır/negatif/mükerrer sayıları, içerik özeti (hash). | Idempotent REST uç noktası, Postgres tabanlı iş kuyruğu | FastAPI, PostgreSQL `FOR UPDATE SKIP LOCKED` · `services/pipeline.py`, `services/common.py` |
| **② Eşleme** | Gelen dosya hangi beklenen teslimata ait? Örneğin "Pazartesi 07:00–10:00 günlük dosya". Gelmeyen dosya da bir "teslimat" olarak modellenir; böylece "gelmedi" tespit edilebilir. | Sözleşmeden takvim üretimi (TR resmî tatilleri, arife yarım günleri, tatile denk gelince kaydırma) ve deterministik eşleme kuralları | `domain/schedule.py`, `domain/matching.py`, `domain/holidays_tr.py` |
| **③ Değerlendirme** | Teslimat beş açıdan incelenir: **zamanlılık** (son teslimden *önce* risk uyarısı dahil), **hacim**, **içerik kalitesi**, **kesin kurallar**, **toplu kesinti**. | Kural motoru (aşağıda) ve açıklanabilir istatistik modeli: log ölçekte Theil–Sen eğilim, ay başı/ortası/sonu ve haftanın günü etkileri (median polish), yıllık mevsimsellik, MAD ile dayanıklı ölçek, kalibre edilmiş tahmin aralığı | NumPy · `domain/engine.py`, `domain/baseline.py`, `domain/detectors/*` |
| **④ Önceliklendirme** | P1–P4 öncelik: şiddet × kurum kritikliği × etkilenen müşteri tahmini. Birçok kurum aynı anda gecikirse tek bir "toplu kesinti" olayı açılır. | Kural tabanlı triage | `domain/triage.py`, `domain/systemic.py` |
| **⑤ Olay yönetimi** | Gelen kutusu, "neden?" açıklaması, grafikler, kontrol listesi; üstlenme, yorum, karar. Durum uzlaştırmalıdır: kısmi dosyanın tamamlayıcısı gelirse olay **kendiliğinden kapanır**. | Olay yaşam döngüsü, gecikmeli bildirim | `services/incidents.py` · React, MUI, TanStack Query, Recharts |
| **⑥ Öğrenme** | Analist kararı modele geri döner. "Gerçek sorun" → bu teslimattan öğrenilmez. "Yeni normal" → seviye yeniden öğrenilir. "Yanlış alarm" → somut ayar önerisi (eşik, saat, yön). | Geri bildirimden kural önerisi, geçmişten takvim çıkarımı | `domain/tuning.py`, `domain/inference.py` |
| **⑦ Yönetişim** | Kural değişikliği önce **90 günlük geçmişte test edilir**, sonra **hazırlayan dışında biri onaylar** (dört göz). Her kararın girdileri değişmez biçimde saklanır ve yıllar sonra yeniden üretilebilir. Denetim kaydı hash zinciridir. | Saf motorla replay, içerik adresli anlık görüntüler, DB trigger'ları, gölge (challenger) modeller | `domain/backtest.py`, `domain/replay.py`, `domain/snapshot.py`, `domain/challengers.py`, `services/governance.py` |
| **Yapay zekâ (yan rol)** | Olay özeti ve doğal dille kural taslağı. **Karar yetkisi yoktur.** Metindeki her sayı kaynak veriyle doğrulanır; kural taslağı şema doğrulamasından ve dört göz onayından geçmeden uygulanmaz. Her çağrı kayıt altındadır. | Yapılandırılmış JSON çıktı, sayı doğrulama (grounding), kural tabanlı yedek | OpenAI uyumlu sunucular (yerel vLLM/Ollama veya OpenAI) ya da Claude (Anthropic SDK) · `ai/*` |

## Kural motoru var mı? "Şu durumda anomali say" diyebiliyor muyuz?

**Evet.** Her kurumun **sözleşmesi** aynı zamanda onun kural setidir. Sürümlüdür, onaylıdır ve hash'lidir. Kurallar istatistik modelden **bağımsız ve her zaman** uygulanır; geçmiş veri olmasa da çalışır. Arayüzde form ile düzenlenir (Kurum → Sözleşme ve kurallar). Doğal dille de tarif edilebilir; yapay zekâ taslağa çevirir, sen kaydedersin, başka biri onaylar.

| Kural türü | Ne zaman anomali | Sözleşmedeki karşılığı |
|---|---|---|
| Son teslim | Dosya saat X'e (+tolerans) kadar gelmezse → `MISSING_DELIVERY` (kritik) · geç gelirse → `LATE_DELIVERY` | `slots[].deadline`, `grace_minutes` |
| Teslim takvimi | Her iş günü / her gün / haftanın günleri / ayın günleri / ayın son iş günü; tatilde kaydırma | `slots[].cadence`, `weekdays`, `month_days`, `holiday_shift` |
| Takvim dışı dosya | Beklenmeyen günde dosya gelirse yok say / bilgi / uyarı | `quality.unexpected_delivery` |
| **Kesin sınır** | Bir ölçü sınırın dışına çıkarsa → `LIMIT_BREACH` (şiddet seçilir) | `limits[]`: `metric`, `min`, `max`, `severity`, `note` |
| İçerik kalitesi | Sıfır tutar oranı > %X, negatif tutar var, mükerrer kayıt oranı > %X, mükerrer dosya, güncellenmemiş veri, kuruş/TL birim hatası | `quality.*` |
| Hacim izleme | Öğrenilen olağan aralığın dışına çıkarsa; hassasiyet ve yön (yalnız düşüş/artış) seçilir | `metrics[]`: `metric`, `sensitivity`, `direction` |

Kesin sınırın kullanılabildiği ölçüler: `record_count`, `total_amount`, `customer_count`, `avg_amount`, `max_amount`, `zero_amount_ratio`, `negative_amount_count`, `duplicate_record_ratio`.

```json
{
  "slots": [{ "key": "daily", "label": "Günlük borç dosyası", "cadence": "BUSINESS_DAYS",
              "window_start": "06:00:00", "deadline": "10:00:00", "grace_minutes": 15 }],
  "limits": [
    { "id": "kapasite", "metric": "record_count", "max": 2000000, "severity": "CRITICAL", "note": "Sistem kapasite sınırı" },
    { "id": "asgari-tutar", "metric": "total_amount", "min": 1000000, "severity": "WARNING" }
  ],
  "quality": { "max_zero_amount_ratio": 0.05, "forbid_negative_amounts": true, "unexpected_delivery": "WARNING" }
}
```

İlk prototipteki DSL kural tipleri bu modele şöyle karşılık gelir:

| Eski DSL | Yeni karşılığı |
|---|---|
| `EXPECT_LOAD_BY_RUN` | `slots[].deadline` (sabit 09:00/14:00 koşuları yerine sürekli değerlendirme ve son teslimden önce risk uyarısı) |
| `UNEXPECTED_LOAD_DAY` | `quality.unexpected_delivery` |
| `ABSOLUTE_VOLUME_BOUNDS` | `limits[]` |
| `ARRIVAL_TIME_BOUNDS` | `slots[].window_start` / `deadline` |

**Bugünkü sınırlar:** Kurallar tek ölçülü eşiklerdir. "Pazartesi **ve** ay başıysa **ve** kayıt < X" gibi bileşik koşullar veya oran ifadeleri (`tutar / kayıt > Y`) henüz yazılamıyor. Bunun için güvenli, `eval` kullanmayan küçük bir koşul dili (AND/OR, haftanın günü, ay dönemi, türetilmiş oranlar) yol haritasında. Kural motoru saf `domain/` katmanında olduğu için eklenmesi motorun geri kalanını etkilemez.

---

## Teknoloji yığını

| Katman | Seçim | Neden |
|---|---|---|
| Tespit çekirdeği | Python 3.12, NumPy, Pydantic v2 | Saf (I/O'suz) motor: canlı akış, geriye dönük test ve simülasyon aynı kodu çalıştırır |
| API | FastAPI, RFC 9457 hata gövdesi, JWT / OIDC | İnce katman, OpenAPI dokümantasyonu `/api/v1/docs` |
| Veri ve kuyruk | PostgreSQL 16, SQLAlchemy 2, Alembic | Tek bir veri deposu: veri, iş kuyruğu (`SKIP LOCKED`) ve lider seçimi (advisory lock) |
| Worker | Python süreci | Kuyruk tüketimi, son teslim taraması, toplu kesinti kontrolü, nabız |
| Arayüz | React 18, TypeScript (strict), MUI 6, TanStack Query, Recharts 3, Vite | Türkçe operatör arayüzü, açık/koyu tema |
| Yapay zekâ | OpenAI uyumlu API veya Anthropic SDK | Dar arayüz; sağlayıcı yapılandırmayla değişir |
| Kalite | pytest, mypy `--strict`, ruff, Playwright E2E, GitHub Actions | Dedektör kalite kapısı CI'da: yakalama, kesinlik ve yanlış alarm eşikleri |
| Çalıştırma | Docker Compose, nginx; hash'li kilit dosyası, Renovate | Tekrarlanabilir derleme |

## Hızlı başlangıç (Docker)

```bash
docker compose up -d --build
```

```bash
docker compose run --rm api python -m loadguard.sim.seed --reset
```

Arayüz: http://localhost:8080 · API dokümantasyonu: http://localhost:8080/api/v1/docs

Seed işlemi 18 sentetik kurum için yaklaşık 16 aylık etiketli geçmiş üretir. Son günlere gerçekçi sorunlar ekler (gelmeyen dosya, kuruş/TL hatası, kısmi dosya, güncellenmemiş veri…) ve onay bekleyen bir kural değişikliği hazırlar. `LG_SIMULATOR_LIVE=true` iken bugünün dosyaları zamanı geldikçe "teslim edilir".

**Demo kullanıcıları** (geliştirme modunda parolasız):

| Kullanıcı | Rol | Dene |
|---|---|---|
| Ayşe Yılmaz | Analist | Olayı üstlen, karara bağla; kural taslağı hazırla |
| Mehmet Kaya | Onaycı | Ayşe'nin taslağını onayla (kendi taslağını onaylayamaz) |
| Zeynep Arslan | Yönetici | Kurum yönetimi |

## Yapay zekâyı açmak (isteğe bağlı)

```bash
# Yerel model (veri dışarı çıkmaz): vLLM / TGI / Ollama gibi OpenAI uyumlu sunucu
LG_AI_PROVIDER=openai_compatible LG_AI_BASE_URL=http://llm.local:8000 LG_AI_MODEL=qwen2.5-32b docker compose up -d

# OpenAI (aynı OpenAI uyumlu sağlayıcı; anahtar ve model ortam değişkenlerinden)
LG_AI_PROVIDER=openai_compatible LG_AI_BASE_URL=https://api.openai.com LG_AI_MODEL=$OPENAI_MODEL LG_AI_API_KEY=$OPENAI_API_KEY docker compose up -d

# Claude (Anthropic SDK, yapılandırılmış çıktı, varsayılan model claude-opus-5-5)
LG_AI_PROVIDER=anthropic LG_AI_API_KEY=sk-ant-... docker compose up -d
```

`LG_AI_TEMPERATURE` varsayılan olarak gönderilmez (bazı modeller yalnızca varsayılan değeri kabul eder); deterministik çıktı isteyen yerel modellerde `0` verilebilir. YZ kapalıyken her şey çalışır; olay ekranında kural tabanlı kontrol listesi gösterilir.

## Entegrasyon: dosya bildirimi

```bash
curl -X POST http://localhost:8080/api/v1/ingest/loads -H "X-Api-Key: dev-ingest-key" -H "Content-Type: application/json" -d '{"institution_code":"ELK01","external_id":"sftp:/in/ELK01_20261005.txt:sha256:ab12","received_at":"2026-10-05T04:31:00Z","content_hash":"ab12cd34ef56","record_count":214332,"total_amount":137171234.5,"customer_count":203611,"zero_amount_count":1100,"slot_hint":"daily"}'
```

`external_id` idempotenttir; aynı bildirim iki kez gelirse yok sayılır.

## Operasyon ve güven kontrolleri

```bash
docker compose run --rm api python -m loadguard.ops status
```

```bash
docker compose run --rm api python -m loadguard.ops audit-verify
```

```bash
docker compose run --rm api python -m loadguard.ops verify-sample --n 500
```

`status` worker nabzını ve kuyruğu kontrol eder. `audit-verify` denetim kaydının hash zincirini doğrular. `verify-sample` kayıtlı kararları bugünkü motorla yeniden üretir. Üçü de sorun olduğunda sıfırdan farklı çıkış kodu döndürür. Prometheus metrikleri: `/api/v1/metrics`.

## Geliştirme

```bash
cd backend && python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"   # Linux/macOS: .venv/bin/pip
```

```bash
docker compose up -d db && cd backend && .venv/Scripts/alembic upgrade head
```

```bash
cd backend && .venv/Scripts/python -m pytest
```

```bash
cd backend && .venv/Scripts/python -m loadguard.sim.evaluate
```

```bash
cd frontend && npm install && npm run dev
```

```bash
cd e2e && npm install && npx playwright install chromium && npx playwright test
```

API yerelde `uvicorn loadguard.api.app:app --app-dir src --port 8000`, worker `python -m loadguard.worker.main` ile çalışır. Vite `/api` isteklerini 8000'e yönlendirir.

## Ölçümler (sentetik veri)

| | Ana model | Gölge `mix-shift-v2` |
|---|---|---|
| Yakalama oranı | %95,9 | %99,2 |
| Uyarı kesinliği | %84,2 | %84,6 |
| 100 teslimatta yanlış alarm | 0,63 | 0,63 |

74 backend testi (alan birim testleri, gerçek migration'larla Postgres entegrasyonu, YZ güvenlik önlemleri, karar yeniden üretimi, denetim zinciri, kalite kapısı) ve 4 uçtan uca test (Playwright).

## Proje yapısı

```
backend/src/loadguard/
  domain/     saf tespit motoru: takvim, sözleşme/kurallar, eşleme, baseline, dedektörler,
              replay, backtest, çıkarım, ayar önerisi, anlık görüntü, challenger modeller
  services/   canlı akış, olay yaşam döngüsü, sözleşme yönetişimi, analitik, bildirim, güven kontrolleri
  ai/         sağlayıcılar, olay özeti, kural yardımcısı, sayı doğrulama
  api/        FastAPI uç noktaları
  worker/     kuyruk ve periyodik tarama
  sim/        etiketli simülatör, kalite ölçümü, demo seed
frontend/src/ React operatör arayüzü
e2e/          Playwright testleri
docs/         iş analizi, mimari, uzun vadeli tasarım
```

## Lisans ve sorumluluk reddi

Deneysel bir çalışmadır; hiçbir garanti verilmez. Sentetik verilerdeki kurum adları hayalîdir; gerçek kuruluşlarla benzerlik tesadüftür.

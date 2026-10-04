# LoadGuard: Fatura Borç Dosyası Teslim Gözetimi

Fatura tahsilatı yapılan kurumların (elektrik, su, doğalgaz, telekom, kamu…) gönderdiği **borç dosyalarını** izler. Dosya **gelmediğinde, geç kaldığında, eksik, mükerrer, bayat ya da hatalı** olduğunda bunu tespit eder ve açıklar. Etkiye göre önceliklendirir ve analistin kararından öğrenir.

- **Açıklanabilir tespit:** zamanlılık (son teslimden önce risk uyarısı dahil), mevsimselliği bilen istatistiksel hacim modeli, içerik kalitesi, kesin iş kuralları, sistemik kesinti.
- **Kullanıcı odaklı:** gelen kutusu, teslimat panosu, "neden?" açıklaması, kontrol listesi, karar akışı.
- **Kapalı öğrenme döngüsü:** analist kararı → öğrenme → ayar önerisi → geriye dönük test → dört göz onayı.
- **Danışman yapay zekâ:** özet ve doğal dilden sözleşme taslağı. Karar yetkisi yoktur; sayı doğrulaması yapılır ve her çağrı kaydedilir.

İş analizi: [docs/DOMAIN.md](docs/DOMAIN.md) · Mimari ve kararlar: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Hızlı başlangıç (Docker)

```bash
docker compose up -d --build
```

```bash
docker compose run --rm api python -m loadguard.sim.seed --reset
```

Arayüz: http://localhost:8080 · API dokümantasyonu: http://localhost:8080/api/v1/docs

Seed işlemi 18 kurum için yaklaşık 16 aylık etiketli sentetik geçmiş üretir. Son günlere birkaç gerçekçi sorun ekler (gelmeyen dosya, kuruş/TL hatası, kısmi dosya, bayat veri…) ve onay bekleyen bir sözleşme değişikliği hazırlar. Worker, `LG_SIMULATOR_LIVE=true` iken bugünün dosyalarını zamanı geldikçe "teslim eder".

**Demo kullanıcıları** (geliştirme modunda parolasız):

| Kullanıcı | Rol | Dene |
|---|---|---|
| Ayşe Yılmaz | Analist | Olayı üstlen, karara bağla; sözleşme taslağı hazırla |
| Mehmet Kaya | Onaycı | Ayşe'nin taslağını onayla (kendi taslağını onaylayamaz) |
| Zeynep Arslan | Yönetici | Kurum yönetimi |

## Yapay zekâyı açmak (isteğe bağlı)

```bash
# Kurum içinde barındırılan model (veri dışarı çıkmaz): vLLM / TGI / Ollama gibi OpenAI uyumlu sunucu
LG_AI_PROVIDER=openai_compatible LG_AI_BASE_URL=http://llm.local:8000 LG_AI_MODEL=qwen2.5-32b docker compose up -d

# Claude (resmî Anthropic SDK, yapılandırılmış çıktı, varsayılan model claude-opus-5-5)
LG_AI_PROVIDER=anthropic LG_AI_API_KEY=sk-ant-... docker compose up -d
```

YZ kapalıyken her şey çalışır; olay ekranında kural tabanlı kontrol listesi gösterilir.

## Entegrasyon: dosya bildirimi

Alım katmanı (SFTP izleyici / API gateway) dosyayı ayrıştırır ve yalnızca **özet** gönderir. Ham müşteri verisi bu sisteme girmez.

```bash
curl -X POST http://localhost:8080/api/v1/ingest/loads -H "X-Api-Key: dev-ingest-key" -H "Content-Type: application/json" -d '{"institution_code":"ELK01","external_id":"sftp:/in/ELK01_20261005.txt:sha256:ab12","received_at":"2026-10-05T04:31:00Z","content_hash":"ab12cd34ef56","record_count":214332,"total_amount":137171234.5,"customer_count":203611,"zero_amount_count":1100,"slot_hint":"daily"}'
```

`external_id` idempotenttir; aynı bildirim iki kez gelirse yok sayılır.

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

Yerel geliştirmede API `uvicorn loadguard.api.app:app --app-dir src --port 8000`, worker `python -m loadguard.worker.main` ile çalışır. Vite `/api` isteklerini 8000'e yönlendirir.

## Kalite

| | |
|---|---|
| Testler | 59 test: alan birim testleri, Postgres entegrasyon testleri, YZ güvenlik önlemleri, dedektör kalite kapısı |
| Statik analiz | `mypy --strict`, `ruff`, `tsc --strict` |
| Dedektör kalitesi (sentetik, 480 gün) | yakalama %97,7 · kesinlik %88 · 100 teslimatta 0,48 yanlış alarm |

## Yapı

```
backend/src/loadguard/
  domain/     saf tespit motoru (takvim, sözleşme, baseline, dedektörler, replay, backtest, çıkarım, ayar)
  services/   canlı akış, olay yaşam döngüsü, sözleşme yönetişimi, analitik, bildirim
  ai/         sağlayıcılar, olay özeti, sözleşme yardımcısı, sayı doğrulama
  api/        FastAPI uç noktaları
  worker/     kuyruk + periyodik tarama
  sim/        etiketli simülatör, kalite ölçümü, demo seed
frontend/src/ React + MUI + TanStack Query
docs/         iş analizi ve mimari
```

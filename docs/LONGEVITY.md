# 10 Yıl Dayanacak Şekilde Tasarım

> Soru: "Bu sistem 2036'da da çalışıyor, güveniliyor ve değiştirilebiliyor olacak mı?"
> On yılda değişmesi kesin olanlar: ekip, kütüphaneler, Python/Node sürümleri, yapay zekâ modelleri, regülasyon, kurum sayısı, belki ülke. Değişmemesi gerekenler: **kararların açıklanabilirliği, kanıtların bütünlüğü, eski verinin okunabilirliği.**

## İlkeler

| # | İlke | Somut karşılığı (kodda) |
|---|---|---|
| 1 | **Çekirdek saf ve küçüktür.** Karar mantığı I/O, framework ve veritabanı bilmez. | `domain/`: FastAPI, Postgres veya kuyruk değişse bile motor aynı kalır. |
| 2 | **Her karar yeniden üretilebilir.** "2027'de bu uyarı neden çıktı?" sorusu 2036'da cevaplanabilmeli. | `domain/snapshot.py` + `input_snapshots`: kararın gördüğü her şey içerik adresli (sha256) saklanır. `ops verify-sample` kararları bugünkü motorla yeniden üretir. |
| 3 | **Kanıt değiştirilemez.** | `evaluations`, `audit_log`, `input_snapshots` tablolarında UPDATE/DELETE veritabanı trigger'ıyla yasak. Denetim kaydı hash zinciridir (`ops audit-verify`); trigger'ı aşan bir süper kullanıcının değişikliği de tespit edilir. |
| 4 | **Eski veri her zaman okunur.** | `domain/contract_migrations.py`: saklanan sözleşmeler asla yerinde değiştirilmez. Okurken sürüm geçişi (upcast) uygulanır. Gelecek sürümden bir kayıt gelirse sistem sessizce yanlış okumaz, açık hata verir. |
| 5 | **Model, kanıtla ve kör olmadan değişir.** | `domain/challengers.py`: yeni model gölge modda çalışır, kimseyi uyarmaz. Analist kararları ve ölçümle karşılaştırılır (İçgörü ekranı). Terfi, kalite kapısından geçen normal bir sürümle olur. |
| 6 | **Davranış değişikliği sürümlenir.** | `ENGINE_VERSION`: tespit davranışını değiştiren her değişiklikte artar ve her kararda kaydedilir. Challenger isimleri değişmez (`mix-shift-v1` → `v2`). |
| 7 | **Bekçiyi de izle.** | Worker nabzı (`worker_heartbeats`), arayüzde kırmızı banner, `/api/v1/metrics` (Prometheus) ve `ops status` (çıkış kodlu, dağıtım hattına bağlanabilir). |
| 8 | **Bağımlılıklar kilitli ama bayat değil.** | `requirements.lock` (hash'li), `package-lock.json`, Renovate ile haftalık gruplu güncellemeler. Sayısal kütüphaneler (numpy) için ek onay şartı var, çünkü kayan nokta sonuçları değişebilir. |
| 9 | **Varsayımlar koda gömülmez.** | Çalışma saat dilimi ve takvim yapılandırmadan gelir. Kurumun saat dilimi ve takvimi sözleşmesinden okunur. |
| 10 | **YZ bir sağlayıcıya kilitli değildir.** | Dar arayüz (`complete_json`): yerel model, OpenAI uyumlu servis veya Claude. Model değişince ürün değişmez; sayı doğrulaması ve kural tabanlı yedek her zaman vardır. |
| 11 | **Testler davranışı korur, uygulamayı değil.** | Alan birim testleri, gerçek migration'larla çalışan Postgres entegrasyon testleri, dedektör kalite kapısı, gerçek tarayıcıyla E2E. |

## Yükseltme reçetesi (her büyük değişiklikte)

```
1. Değişikliği yap, ENGINE_VERSION'ı artır (davranış değiştiyse)
2. pytest              → kalite kapısı: yakalama/kesinlik/yanlış alarm eşikleri
3. ops verify-sample   → geçmiş kararların kaçı aynı çıkıyor? Farklar açıklanabilir mi?
4. Gölge modda en az 4 hafta çalıştır → analist kararlarıyla karşılaştır
5. Terfi: normal sürüm + onay. Eski motor sürümüyle alınmış kararlar snapshot'larıyla açıklanabilir kalır.
```

Altyapı yükseltmelerinde (Python 3.12 → 3.1x, numpy 2 → 3) `verify-sample` sonucunun **%100** olması beklenir. Fark çıkarsa bu deterministiklik kaybıdır ve sürüm durdurulur.

## Ölçülen etki (sentetik, 480 gün)

| Model | Yakalama | Kesinlik | 100 teslimatta yanlış alarm | Segment kaybı |
|---|---|---|---|---|
| Ana model (engine-2.1.0) | %95,9 | %84,2 | 0,63 | 3/7 |
| Gölge `mix-shift-v1` | %99,2 | %75,6 | 1,11 | 7/7 |
| Gölge `mix-shift-v2` | **%99,2** | **%84,6** | **0,63** | **7/7** |

v1 canlıya doğrudan alınsaydı yakalama artarken analistler ısınma sezonunun yanlış alarmlarına boğulurdu. Gölge mod bunu gösterdi. v2 aynı yakalamayı ek gürültü olmadan sağlıyor. Terfi kararı canlı gölge verisiyle verilecek.

## Kalan yol haritası (öncelik sırasıyla)

### 0–6 ay: üretime hazırlık
- **Alım kenarı:** SFTP izleyici ve dosya ayrıştırıcı ayrı bir servis olarak yazılmalı. Yalnızca özet metrikler `POST /ingest/loads` ile gelir. Dosya içi segment dağılımı (bölge, abone grubu) eklenirse kısmi dosyada *hangi segmentin* eksik olduğu gösterilebilir.
- **Kimlik:** OIDC kodu hazır ama gerçek bir IdP ile denenmedi. Kurumsal IdP ile entegrasyon testi yapılmalı. Rol eşlemesi için IdP grupları kullanılabilir.
- **Gizli bilgi yönetimi:** Ortam değişkenleri yerine Vault / Key Vault. API anahtarları periyodik olarak döndürülmeli.
- **Bildirim kanalları:** Teams/Slack webhook'u var. E-posta, SMS, nöbet çizelgesi ve eskalasyon (P1 15 dk üstlenilmezse) eklenmeli.
- **Yedekleme ve felaket kurtarma:** Postgres PITR. `input_snapshots` ve `audit_log` için WORM (değiştirilemez) arşiv.

### 6–24 ay: ölçek ve derinlik
- **Saklama ve bölümleme:** `evaluations` ve `input_snapshots` yıllara göre bölümlenir (partition). Regülasyon süresi dolan bölümler soğuk depolamaya taşınır; hash'ler sıcak kalır, böylece kanıt zinciri korunur.
- **Ödeme tarafı sinyali:** Kanallardaki "borç bulunamadı" sorgularındaki artış en doğrudan müşteri etkisi ölçüsüdür. Gölge dedektör olarak eklenmeli.
- **Denetimli model:** Etiketler biriktiğinde (her kurum için yüzlerce karar) gradient boosting ile bir *challenger* eğitilir. Aynı gölge süreci ve kalite kapısı uygulanır. Model kartı ve doğrulama raporu otomatik üretilir.
- **Çoklu kiracı / çoklu ülke:** Takvim, para birimi ve saat dilimi zaten sözleşme düzeyinde. Kurum grubu ve kiracı (tenant) ayrımı ile satır düzeyi güvenlik (RLS) eklenmeli.
- **Arayüz uluslararasılaştırma:** Metinler i18n kaynaklarına taşınmalı. Backend mesajları zaten `code` + parametre taşıyor.

### 2–5 yıl: mimari evrim
- **Akış işleme:** Postgres kuyruğu yerine Kafka/Redpanda ve CDC. Motor saf olduğu için olduğu gibi taşınır.
- **Kurum portalı:** Kurum kendi SLA'sını, gecikmelerini ve kalite puanını görür. Sorun kaynağında azalır.
- **Olay bilgi tabanı:** Geçmiş olaylar ve analist notları üzerinde arama. YZ benzer olayları getirir ("geçen mart aynı kurumda aynı hata, çözüm şuydu").

### 5–10 yıl: ajan destekli operasyon (yetki sınırlarıyla)
- YZ olası nedeni araştırır, kanıt toplar (loglar, geçmiş olaylar, kurum duyuruları) ve aksiyon **önerir**. Yürütme yetkisi, politika olarak tanımlanmış dar işlemlerle sınırlıdır (ör. kuruma bilgilendirme taslağı hazırlamak). Para hareketi, eşik değişikliği ve olay kapatma her zaman insanda kalır. Her öneri bugünkü gibi kayıt ve doğrulama altındadır.
- Düzenleyici raporlama ve model envanteri, karar kayıtlarından otomatik üretilir.

## Bilinçli olarak yapılmayanlar

- **Mikroservislere bölmek:** Bu ölçekte bölmek karmaşıklık getirir, fayda getirmez. Çekirdek saf olduğu için gerektiğinde bölmek kolaydır.
- **Kara kutu modeli doğrudan karar vermeye koymak:** Açıklanabilirlik ve model riski gereklilikleri buna izin vermez. Her model gölge süreçten geçer.
- **YZ'ye yazma yetkisi vermek:** On yıl içinde modeller çok daha yetenekli olacak. Yetki sınırları teknik yetenekle değil, sorumlulukla belirlenir.

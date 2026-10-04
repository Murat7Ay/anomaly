# İş Analizi: Borç Dosyası Teslim Gözetimi

> Bu belge "ne yapıyoruz ve neden" sorusunun cevabıdır. Kod bu belgeyi uygular; çelişki varsa önce bu belge güncellenir.

## 1. Problem

Bir tahsilat kuruluşu, elektrik/su/doğalgaz/telekom/kamu gibi **kurumlar** adına fatura tahsil eder. Müşterinin ödeme kanallarında ödeme yapabilmesi için kurumun güncel **borç dosyasını** zamanında ve doğru göndermesi gerekir. Dosyada bir sorun olduğunda bunun maliyeti doğrudan müşteriye yansır:

| Ne olur | İş etkisi |
|---|---|
| Dosya gelmez veya geç gelir | Müşteri ödeyemez → şikâyet, kurumun tahsilatı gecikir, çağrı merkezi yükü |
| Kısmi dosya (bir bölge/segment eksik) | Müşterilerin bir kısmı "borç bulunamadı" görür |
| Aynı dosya iki kez yüklenir | **Çift tahsilat** riski, iade süreçleri, itibar |
| Kuruş/TL birim hatası (×100) | Herkes yanlış tutar görür, en kritik veri kalitesi hatası |
| Güncellenmemiş (dünkü) veri | Ödenmiş borçlar tekrar görünür |
| Sıfır/negatif tutarlar | Eşleme hatası; iade kayıtları borç gibi görünür |
| Birçok kurumda aynı anda kesinti | Sorun büyük olasılıkla **bizim** alım altyapımızdadır |

**Eski sistemin varsayımları ve eksikleri:**
- Günde iki sabit kontrol (09:00 / 14:00) vardı. Sorun 07:30'da başlasa bile ancak 09:00'da görülüyordu ve "geç kalacak" diye önceden uyarı yoktu.
- Tek bir anomali kararı üretiyordu. Kimin ne kadar etkilendiği yoktu, bu yüzden önceliklendirme de yoktu.
- İçerik kalitesine (mükerrer, birim hatası, bayat veri) bakılmıyordu.
- Mahalanobis tabanlı ML skoru açıklanamıyordu.
- Kullanıcıya anomali listesi gösterilmiyordu. Analist kararı sisteme geri dönmüyor, sistem de hatalarından öğrenmiyordu.
- Kural düzenleme ham JSON ile yapılıyordu ve etkisi test edilemiyordu.

## 2. Kullanıcılar ve işleri

| Kişi | Yapmak istediği iş | Sistemde karşılığı |
|---|---|---|
| **Operasyon analisti** | "Sabah ilk 5 dakikada hangi kurumda sorun var, ne kadar acil, ne yapmalıyım?" | Gelen kutusu, teslimat panosu, öncelik, kontrol listesi |
| | "Bu uyarı neden çıktı? Gerçek mi?" | Bulguda beklenen değer ve olağan aralık; nasıl hesaplandığı (seviye, ay başı etkisi, eğilim) |
| | "Kurumu son teslimden önce arayayım." | `DELIVERY_AT_RISK`: alışılmış saatten geç ama son teslimden önce |
| | "Yanlış alarm, bir daha görmeyeyim." | Karar türleri öğrenmeyi besler, ayar önerisine dönüşür |
| **Onaycı / takım lideri** | "Eşik değişikliği gerçek sorunları kaçırtır mı?" | Geriye dönük test ve dört göz onayı |
| **Kurum ilişkileri** | "Hangi kurum sözleşmeye uymuyor?" | Kurum bazında zamanında teslim oranı, geç ve gelmedi sayıları |
| **Denetim / iç kontrol** | "Bu karar hangi kuralla, kimin onayıyla verildi?" | Değişmez değerlendirme kaydı, sözleşme hash'i, denetim günlüğü |

## 3. Kavram modeli

```
Kurum ──< Sözleşme sürümü (onaylı, hash'li, geçerlilik tarihli)
  │            └─ Teslimat slotları (ne zaman), izlenen hacimler (ne kadar), kalite politikası, kesin kurallar
  │
  └──< Teslimat (occurrence) = kurum × slot × iş günü     ← değerlendirme, geçmiş ve vaka yönetiminin birimi
          ├──< Dosya (load): alım katmanının ürettiği özet (kayıt/tutar/müşteri/sıfır/negatif/özet hash)
          ├──< Değerlendirme (append-only): girdiler, motor sürümü, sözleşme hash'i, bulgular
          └──< Olay (incident): kategori başına bir tane; açık → üstlenildi → karara bağlandı
                     └──< Zaman çizelgesi olayları, analist kararı
```

- **Teslimat (occurrence)** temel birimdir. "Bugün ELK01'den 07:00–10:00 arası günlük dosya bekleniyor" bir teslimattır. Dosya gelmese bile vardır, bu yüzden "gelmedi" tespit edilebilir.
- Bir slota birden fazla dosya gelirse (parça dosya, tamamlayıcı) **toplamı** değerlendirilir. Kısmi dosya sonradan tamamlanırsa olay kendiliğinden kapanır.
- Dosyanın hangi teslimata ait olduğu önce entegrasyonun verdiği `slot_hint` ile, yoksa deterministik eşleme kuralıyla bulunur (`domain/matching.py`): pencere içi → aynı gün gecikmiş → ek dosya → erken → önceki günlerin eksiği → takvim dışı.

## 4. Tespit stratejisi

Tüm mantık saf (I/O'suz) bir motordadır (`domain/engine.py`). Canlı akış, geriye dönük test ve simülasyon aynı kodu çalıştırır.

### 4.1 Zamanlılık
- `MISSING_DELIVERY` (son teslim + tolerans geçti), `LATE_DELIVERY` (ertesi güne kaldıysa kritik), `EARLY_DELIVERY` (bilgi).
- **`DELIVERY_AT_RISK` (öngörüsel):** Kurumun geçmiş varışlarının %97'si 08:00'den önceyse ve saat 08:15 olduğu halde dosya gelmediyse uyarı verilir. Analist, son teslim saatinden önce kurumu arayabilir.
- `ARRIVAL_DRIFT`: süresinde geldi ama alışılmıştan geç (eğilim uyarısı, bilgi).
- Takvim: Türkiye resmi tatilleri ve arife yarım günleri. Tatile denk gelen teslim slot bazında kaydırılır (sonraki/önceki iş günü, atla, tatilde de bekle).

### 4.2 Hacim: açıklanabilir istatistik modeli
Fatura hacimleri çarpımsaldır ve sağa çarpıktır. Bu yüzden log ölçeğinde şu ayrıştırma kullanılır:

`log(y) = seviye + eğilim·t + ay_içi_dönem_etkisi + haftanın_günü_etkisi + yıllık_mevsimsellik + gürültü`

| Bileşen | Yöntem | Neden |
|---|---|---|
| Eğilim | Theil–Sen (dayanıklı) | Büyüyen kurum anomali değildir; %29'a kadar aykırı değere dayanıklıdır |
| Ay başı/ortası/sonu, haftanın günü | Median polish (grup ≥3) | Faturalar ay başında yığılır (ör. SGK ×1,8) |
| Seviye | Son 10 temiz teslimatın medyanı | Kalıcı değişime ("yeni normal") hızlı uyum |
| Yıllık mevsimsellik | Geçen yılın aynı dönemdeki değişimi | Isınma sezonu, okul dönemleri |
| Ölçek | 1,4826·MAD, serbestlik düzeltmeli, %2,5 taban | Stabil kurumlarda %0,5'lik oynamaya alarm üretmez |
| Tahmin aralığı | Gürültü + seviye ve etki tahmin belirsizliği | Kalibrasyon: temiz veride z std = 1,08 (ideal 1,0) |

Hassasiyet (Düşük/Orta/Yüksek) eşiği 5,5 / 4 / 3 sağlam z olarak belirler. %50'den fazla düşüş veya 2 kattan fazla artış kritik sayılır. Her bulgu "beklenen 182.400 (aralık 165–201 bin), dayanak: ay başı etkisi ×1,55…" biçiminde açıklanır.

**Neden kara kutu ML değil?** Düzenlemeye tabi finansal operasyonlarda model riski yönetimi (doğrulama, açıklanabilirlik, değişiklik kontrolü) her skorun gerekçelendirilmesini ister. Ayrıştırma modeli aynı veriyle bağımsız olarak doğrulanabilir ve analist "neden" sorusunun cevabını ekranda görür. Denetimli bir model (bkz. yol haritası), ancak yeterli etiket biriktiğinde ve aynı kalite kapısından geçerse eklenir.

### 4.3 İçerik kalitesi
`DUPLICATE_FILE` (içerik özeti daha önce görülmüş), `STALE_DATA` (toplamlar önceki teslimatla birebir aynı), `UNIT_SCALE_SUSPECT` (ortalama tutar ×100 veya ×1000 sapmış, kayıt sayısı normal), `ZERO_AMOUNT_RECORDS`, `NEGATIVE_AMOUNTS`, `DUPLICATE_RECORDS`. İçerik kontrolleri takvim dışı dosyalara da uygulanır.

**Kök neden birleştirme:** Birim hatası tutar sapmasını açıklar. Bu durumda aynı sorun için ayrıca "tutar yüksek" uyarısı üretilmez.

### 4.4 Kesin iş kuralları
Öğrenilen beklentiden bağımsız, işin koyduğu sınırlardır (ör. "kayıt sayısı > 2 milyon olamaz: sistem kapasitesi").

### 4.5 Sistemik görünüm
Son 90 dakikada son teslimi dolan teslimatların ≥%50'si (en az 3) gelmediyse **tek bir toplu kesinti olayı** açılır. Kurum olayları ona bağlanır, öncelikleri düşürülür ve bildirimleri bastırılır. Mesaj "önce kendi altyapını kontrol et" der.

## 5. Önceliklendirme

`öncelik = f(şiddet, kurum kritikliği, etkilenen müşteri)`
- **P1:** kritik ve (kritiklik 1 veya ≥50.000 müşteri)
- **P2:** diğer kritikler; kritiklik-1 kurumda geniş etkili uyarılar
- **P3:** uyarılar · **P4:** bilgi (olay açmaz, kayıt tutulur)

Etki tahmini: gelmeyen dosyada son 10 teslimatın medyanı, kısmi dosyada eksik pay, birim hatası ve mükerrer dosyada tüm dosya.

## 6. Öğrenme döngüsü (insan merkezde)

```
Bulgu → Olay → Analist kararı ─┬─ Gerçek sorun / Bilinen olay → teslimat öğrenmeden hariç
                               ├─ Yeni normal → seviye bu teslimattan itibaren yeniden öğrenilir
                               └─ Yanlış alarm → ayar önerisi (eşik/saat/yön)
                                                   ↓
                         Taslak → Geriye dönük test (90 gün, onaylı kararlarla) → Dört göz onayı → Yürürlük
```

Karar verirken açıklama zorunludur (yanlış alarm, yeni normal, bilinen olay). Denetim izi ve öğrenme bu notlara dayanır.

## 7. Yapay zekâ ilkeleri

1. **Yetkisi yoktur.** Şiddet, öncelik, eşik ve kuralı yalnızca deterministik motor belirler. YZ çıktısı hiçbir zaman otomatik uygulanmaz.
2. **Yalnızca verilen gerçekleri kullanır.** Olay özetinde metindeki her sayı kaynak verilerle karşılaştırılır (`ai/grounding.py`). Doğrulanamayan sayılar ekranda uyarıyla gösterilir.
3. **Her zaman bir yedek vardır.** Kural tabanlı kontrol listesi YZ olmadan da çalışır. YZ kapalıyken veya hata verdiğinde ürün eksiksiz işler.
4. **Doğal dilden sözleşme önerisi** şema doğrulamasından geçer (bir kez otomatik düzeltme denenir). Analist farkları görür, geriye dönük testi çalıştırır, taslağı kaydeder ve başka biri onaylar.
5. **Denetlenebilirdir.** Her çağrı `ai_interactions` tablosuna kaydedilir: kim istedi, prompt özeti, model, yanıt, doğrulama sonucu, süre.
6. **Veri yerinde kalabilir.** Kurum içinde barındırılan model (OpenAI uyumlu sunucu: vLLM vb.) veya Claude (resmî Anthropic SDK, yapılandırılmış çıktı, reddetme yedeği) yapılandırma ile seçilir. YZ'ye ham müşteri verisi gitmez, yalnızca özet metrikler gider.

## 8. Yönetişim ve denetim
- Sözleşme sürümlü ve hash'lidir. Her değerlendirme hangi sözleşme hash'i ve motor sürümüyle çalıştığını kaydeder. `evaluations` tablosu yalnızca eklemeye açıktır.
- Onay sonrası değişiklik geçmişi yeniden yazmaz (`effective_from` en erken bugündür).
- Kimlik kurumsal IdP'den (OIDC) gelir. Rol (Analist / Onaycı / Yönetici) uygulamanın kendi tablosundadır (en az yetki).
- Bakım ve planlı olaylar için **bastırma** tanımlanabilir. Bulgu kaydedilir ama kimse uyarılmaz.

## 9. Ölçülen kalite (sentetik, etiketli veri)

18 kurum arketipi, 480 gün, 3.506 teslimat. Enjekte anomaliler: gelmedi, geç, kısmi, sıçrama, birim hatası, mükerrer, bayat, sıfır/negatif, takvim dışı, toplu kesinti. Zor vakalar da vardır: tarife kaynaklı kalıcı artış, ısınma sezonu, gürültülü kurumlar.

| Ölçü | Değer |
|---|---|
| Genel yakalama oranı | **%97,7** |
| Uyarı kesinliği | **%88** |
| 100 teslimat başına yanlış alarm | **0,48** |
| Gelmedi / geç / mükerrer / birim / bayat / negatif / toplu kesinti | %100 |
| Kısmi dosya | 14/15 · Hacim sıçraması 12/14 |
| Kendiliğinden tamamlanan kısmi dosyada açık kalan uyarı | 0 |

Bu sayılar CI'da **kalite kapısıdır** (`tests/domain/test_quality_regression.py`): yakalama oranı <%93, kesinlik <%80 veya 100 teslimatta >1 yanlış alarm olursa build kırılır. Sentetik veri gerçek dünyanın yerini tutmaz. Canlı ortamda aynı ölçüler analist kararlarından hesaplanır (İçgörü ekranı).

## 10. Beş yıllık yol haritası

| Ufuk | Adım | Gerekçe |
|---|---|---|
| 0–6 ay | Gerçek alım entegrasyonu: SFTP izleyici + dosya ayrıştırıcı. Özet metrikler `POST /ingest/loads` ile gelir. | Ham dosya bu sisteme hiç girmez (veri minimizasyonu) |
| | OIDC/SSO, Teams/e-posta webhook'ları, nöbet planı | Gerçek operasyon |
| | Kurum iletişim kaydı ve kuruma otomatik bilgilendirme taslağı (YZ yazar, insan gönderir) | Kurumla iletişimi hızlandırır |
| 6–18 ay | Dosya içi dağılım metrikleri (bölge, abone grubu, tutar histogramı). Kısmi dosyada **hangi segmentin** eksik olduğu gösterilir. | Kök nedeni dakikalar yerine saniyelerde bulmak |
| | Ödeme tarafıyla bağlantı ("borç bulunamadı" sorgu artışı → dosya sorunu sinyali) | Müşteri etkisinin doğrudan ölçümü |
| | Etiketler biriktikçe denetimli sınıflandırıcı (gradient boosting), mevcut modelle **champion/challenger** ve gölge modunda; aynı kalite kapısından geçmek zorunlu | Model riski yönetimine uygun geçiş |
| 18–36 ay | Olay akışı (Kafka/Debezium) ile anlık değerlendirme. Postgres kuyruğu yerine akış işleme; motor aynı kalır. | Ölçek ve gecikme |
| | Kurumlar arası öğrenme: yeni kurum için sektör ön bilgisi (soğuk başlangıç) | Yeni kurum ilk günden korunur |
| | Kurum portalı: kurum kendi teslim kalitesini ve SLA'sını görür | Sorunu kaynağında azaltmak |
| 36–60 ay | Ajan destekli operasyon: YZ olası nedeni araştırır, kanıt toplar, aksiyon **önerir**. Onay ve yürütme insanda kalır, yetki sınırları politika ile tanımlanır. | Analist zamanını karar vermeye ayırmak |
| | Düzenleyici raporlama ve model envanteri otomasyonu | Denetim maliyetini düşürmek |

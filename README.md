# Toplantı Tutanağı — Faz 1 (ASR + manuel isim seçimi)

Canlı toplantı tutanağı: telefon mikrofonuyla ses kısa parçalar halinde
kaydedilir, backend Türkçe ASR (faster-whisper) ile metne çevirir; kim
konuştuğu ise diarization ile değil, canlı ekranda seçilen "şu an konuşan"
katılımcıyla **manuel** etiketlenir (istenirse sonradan düzeltilebilir).
Toplantı bitince ham konuşma dökümü gösterilir.

Bu aşamada **yok**: otomatik ses-isim eşleştirme (Faz 2), yapay zekâ ile
gündem/karar derlemesi ve imza/PDF akışı (Faz 3).

Kullanıcı hesabı/girişi yok — her toplantı, oluşturma anında bir kere
gösterilen bir **düzenleme anahtarı** ile korunur; tarayıcı bu anahtarı
`localStorage`'da saklar. Anahtarı kaybederseniz o toplantıya bir daha
erişilemez (bkz. üstteki "Anahtar" bağlantısı — anahtarı not almak için).

## Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

`faster-whisper` ağır/opsiyonel bir bağımlılıktır — kurulu değilse veya
model ağırlıkları indirilemiyorsa uygulama yine de açılır, `audio-chunk`
uç noktası sadece `503` döner. Model varsayılan olarak ilk kullanımda
Hugging Face'ten indirilir (`ASR_MODEL_SIZE=small`, Türkçe).

### Ortam değişkenleri (`.env`, bkz. `.env.example`)

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./toplanti.db` | SQLite (Postgres'e geçiş için tek satır değişiklik yeterli) |
| `CORS_ORIGINS` | `https://onurcoskun616.github.io` | İzin verilen ek origin'ler (virgülle ayrılmış); `localhost` her zaman ayrıca izinli |
| `ASR_MODEL_SIZE` | `small` | faster-whisper model boyutu |
| `ASR_DEVICE` | `cpu` | `cpu` / `cuda` |
| `ASR_COMPUTE_TYPE` | `int8` | ctranslate2 hesaplama tipi |
| `ASR_LANGUAGE` | `tr` | ASR dili |

### Testler

```bash
pytest
```

## Frontend

Repo kökündeki `index.html` / `style.css` / `app.js` — build sistemi yok.
**`index.html`'i doğrudan çift tıklayıp açmayın**: `file://` origin'inde
`fetch`/CORS çalışmaz ve `getUserMedia` (mikrofon) güvenli bir bağlam
(secure context) ister. Bunun yerine:

```bash
python3 -m http.server 8080
# tarayıcıda http://localhost:8080 açın
```

ya da doğrudan yayındaki sayfayı kullanın:
**https://onurcoskun616.github.io/toplanti-tutanak/**

Her iki durumda da sayfanın sağ üstündeki **"Ayarlar"** bağlantısından
backend adresini girin (yerelde çalıştırıyorsanız varsayılan
`http://localhost:8000` zaten doğrudur).

## Güvenlik notu

Backend şu an **kimliksiz ve sınırsız**: `POST /api/meetings` herkese açık
ve ASR çağrıları CPU harcar. Yalnızca yerel/kişisel kullanım için uygundur —
sunucuyu bir tünel (ngrok vb.) ile dışarı açmadan önce bir koruma katmanı
eklemeyi düşünün.

# IDE Agent → Telegram (Mac-M4)

IDE’de açılan Agent Chat oturumlarını Telegram’a yansıtır. Limit sorgular; soft-stop ister.
Konularda `/` dışı mesajlar Grok sohbetine gider.

## Ne yapar

| Özellik | Nasıl |
| --- | --- |
| Takip | Cursor user hooks → `127.0.0.1:18765/hook` → Telegram forum konusu |
| `/oturumlar` | Son IDE oturumları (kısa id, proje, topic) |
| `/limit` | Cursor kullanım özeti |
| `/dur` | Oturumu kilitle (tool/shell/MCP/alt-ajan/prompt) |
| `/dur hepsi` | Tüm oturumlar + yeniler kilit |
| `/devam` / `/devam hepsi` | Kilidi kaldır |
| `/ozet` | Tek seferlik Grok özeti; Telegram HTML |
| `/yaz` | IDE agent kutusuna metin yazar, Enter’a basar |
| `/ekran` | Cursor penceresini Telegram canlı yayınına basar |
| `/ekran dur` | Yayını keser |
| Konu sohbeti | `/` ile başlamayan metin → Grok (en üst model), konu hafızası |

Oturum konusunda IDE’ye açıkça mesaj göndermek için `/yaz` kullan.

## Konu sohbeti

- **`/` ile başlayan** mesajlar sohbete gitmez; komut handler’ları çalışır.
- **mac-m4 konusu** (`TELEGRAM_TOPIC_MAC_M4`): meta Grok. Tüm oturumların farkında; doğal dilde `dur` / `devam` / `limit` / `oturumlar` / `ozet` uygulayabilir.
- **Oturum konusu** (IDE mirror’ın açtığı topic): o IDE agent’ın izleri + konu geçmişi. Yalnızca o oturumu `dur`/`devam`/`ozet` edebilir. “şunu yaz / devam et” dersen IDE kutusuna `yaz` aksiyonu gider.
- CLI Grok turları ve IDE alt ajanları yeni Telegram konusu açmaz. Konu yalnız üst IDE oturumunda açılır.
- Hafıza: `data/topic_chats/<topic_id>.jsonl`
- Model: `cursor-agent --list-models` → en yüksek Grok (öncelik: sürüm, sonra xhigh). Cache `data/grok_model_cache.json` (~1 saat). `BILDIRIM_GROK_MODEL` ile kilitle.

## Bileşenler

- LaunchAgent: `local.bildirim.mac-m4` (`scripts/mac-m4-service.sh`)
- Hooks: `~/.cursor/hooks.json` + `scripts/bildirim-mirror.py`
- Durum: `data/cursor_sessions.json`
- Bridge port: `data/bridge.port` (varsayılan 18765)

## Komutlar

Mac-M4 botuna (izinli kullanıcılar):

```text
/ping
/oturumlar
/limit
/dur
/dur a1b2c3d4
/dur hepsi
/devam
/devam hepsi
/ozet
/ozet a1b2c3d4
```

`/dur` ve `/ozet` önce konuya, yoksa aktif oturuma bakar.
`/özet` (Türkçe ö) de özet komutuna düşer.

## IDE’ye yaz (`/yaz`)

`/yaz devam et, şu dosyayı bitir` o konudaki projenin Cursor penceresini bir an öne alır, Agent kutusuna yapıştırır, Enter’a basar, sonra önceki uygulamaya döner. Cursor metin kutusunu arka planda açmadığı için kısa odak gerekir.

Doğal dil de aynı işi yapar: “IDE’ye şunu yaz: …”

## Canlı ekran (`/ekran`)

**Mac-M4 konusunda** `/ekran` veya “ekran paylaşımı aç” yaz. Bot, Mac’in ana ekranı için oturuma özel bir HTTPS bağlantısı verir. Telefonda görüntüye dokunarak tıkla. Dokunma menüsünden çift tıklama, sağ tıklama veya sürüklemeyi seçebilirsin. Klavye ve metin girişi Mac’te odaktaki alana yazar. Asistana mesaj kutusu ekranla ilgili soru ve komutları kabul eder.

**Konuşmayı aç** düğmesine dokun ve telefonun mikrofon iznini ver. Durakladığında soru Mac’e gider. Türkçe yanıt oynatılırken dinleme duraklar ve yanıt bitince yeniden başlar. Konuşma macOS Speech ile metne çevrilir. Ekran sorularını mevcut Cursor/Grok bağlantısı yanıtlar. Mikrofon veya ses oynatma kısıtlamasıyla karşılaşırsan bağlantıyı telefonun tarayıcısında aç. Sayfayı kapatmak veya Telegram’da `/ekran dur` yazmak yayını sonlandırır. Oturumun üst sınırı 15 dakikadır.

Mac-M4 panelinde sesli fare ve klavye için şu ifadeleri kullanabilirsin.

| Söylediğin | Mac’in yaptığı |
| --- | --- |
| Ekranı sağa kaydır | Sağdaki macOS masaüstüne veya tam ekran uygulamaya geçiş ister. |
| Sayfayı sağa kaydır | Uygulamaya yatay kaydırma girdisi iletir. |
| Hangi uygulamalar açık? / Safari’ye geç | Mac’in açık uygulamalarını sayar veya adı geçen uygulamayı öne getirir. |
| İmleci sağa 80 piksel taşı / çift tıkla / kopyala | Fare hareketini veya klavye kısayolunu yerel olarak uygular. |
| Codex’e merhaba yaz | Mevcut sohbet kutusuna taslak yazar. “Şunu yaz” sonrasında dikte edilen metin olduğu gibi kullanılır. |
| Buraya merhaba yaz | Önceden seçtiğin alana karakterleri iletir. |
| Teams’ten Ayşe Yılmaz’a şunu yaz: Yarın görüşelim. | Teams’te kişiyi seçer, hedefi doğrulayınca metni taslağa yazar. Aynı isimde kişiler varsa e-posta ister. |
| Teams’ten birine mesaj yaz | Panel önce alıcıyı, sonra mesajı sorar. Yanıtları 90 saniye bekler. “Vazgeç” ile kapatabilirsin. |

Mac’te Microsoft Teams açıkken alıcının iş e-postasıyla tek kişilik taslak açmayı da isteyebilirsin. Bu yol Teams’in taslak bağlantısını kullanır. [Microsoft’un Teams sohbet bağlantısı belgesi](https://learn.microsoft.com/en-us/microsoftteams/platform/concepts/build-and-test/deep-link-teams). “Gönder” ayrı bir sesli komuttur ve sohbet kutusunun doğrulanmasını gerektirir. Codex metin alanını macOS’a göstermiyorsa panel boş sohbet kutusundaki yer tutucuyu arar. Dolu kutularda düzenleme menüsünü kontrol eder. Metin görüntüde doğrulanınca yazma sonucunu bildirir. Ayrı bir “gönder” komutu için pencere ve taslak yeniden doğrulanır.

**Cursor oturumunun konusunda** `/ekran` o pencereyi Telegram canlı yayınına gönderir. İlk kurulumda şu adımları izle.

1. Grupta canlı yayını başlat, **Başka uygulamayla yayınla**.
2. `.env` içine `TELEGRAM_RTMP_URL` ve `TELEGRAM_RTMP_KEY` yaz.
3. `/ekran`

İlk seferde macOS Ekran Kaydı izni ister. İzin verince ilgili uygulama yeniden başlayabilir. Sonra `/ekran` tekrar. Durdurmak: `/ekran dur`.

## Özet (`/ozet`)

Ayrı bir `cursor-agent` ask turu; model dinamik en üst Grok.
İzler: `data/cursor_traces/` + oturum meta. Cevap Telegram HTML’e çevrilir.

`.env` → `CURSOR_API_KEY=…` (veya `data/cursor_api.key`). `cursor-agent` PATH’te olmalı (`~/.local/bin`).

## Durdurma

IDE’yi uzaktan anında öldüren resmi API yok. `/dur` şunları kilitler (arka plan dahil):

- tool, shell, MCP, dosya okuma, alt-ajan
- yeni prompt ve auto follow-up

O anda akan model cevabı için IDE **Stop**. Sonra tool/alt-ajan yeniden başlamaz; açmak için `/devam`.

## Limit

Kullanım sorgusu isteğe bağlıdır. Kendi Cursor oturum anahtarını yerel `.env` içindeki `CURSOR_SESSION_TOKEN` ayarına gir veya `bildirim cursor-auth` ile gizli istemde kaydet. Dosya yolu `data/cursor_session.token` ve izinleri `0600` olur. Terminalde `bildirim limit` ile dene. Cursor kullanım uç noktası değişirse hesap panelinden kontrol edebilirsin.

## Servis

```bash
scripts/mac-m4-service.sh start
scripts/mac-m4-service.sh status
scripts/mac-m4-service.sh stop
```

Log: `data/logs/mac-m4-bot.out.log`

## Forum konusu

Bot her oturum için `createForumTopic` dener (`proje · shortId`). Yetki yoksa mesajlar `TELEGRAM_TOPIC_MAC_M4` konusuna düşer.

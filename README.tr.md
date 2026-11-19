# Seyir

[English](README.md) · Türkçe

Seyir ile Mac’teki önemli e-postaları ve Cursor oturumlarını özel bir Telegram grubunda takip et. Masandan uzaktayken telefondan ekranı açabilir, Türkçe konuşarak uygulama değiştirebilir veya bir mesaj taslağı yazdırabilirsin.

| Nerede? | Ne yapabilirsin? |
| --- | --- |
| **Mail konusu** | Apple Mail’deki okunmamış iletileri yerel Qwen ile sınıflandır. Toplantının zamanını ve katılımcılarını gör. Önemli bildirime **içerik** diye yanıt vererek kayıtlı gövde önizlemesini al. |
| **Cursor oturumunun konusu** | Agent konuşmasını takip et, `/ozet` iste, `/yaz` ile IDE’ye mesaj gönder, `/dur` ile sonraki araç çağrılarını duraklat. |
| **Mac-M4 konusu** | `/oturumlar` ile oturumları gör. `/ekran` ile masaüstü panelini aç, telefondan fare ve klavye kullan veya **Konuşmayı aç** ile Türkçe sesli komut ver. |

**“Ekranı sağa kaydır”** bir sonraki macOS masaüstüne geçer. **“Sayfayı sağa kaydır”** odaktaki uygulamayı kaydırır. **“Codex’e merhaba yaz”** taslak oluşturur. Telegram’daki **`/yaz merhaba`** ise ilgili Cursor oturumuna mesajı gönderir.

## Kurulum

macOS’ta oturum açmış bir kullanıcı ve Python 3.11 veya üzeri gerekir. Mail ve Mac botlarını ayrı ayrı kurabilirsin.

```sh
git clone https://github.com/enesiyidil/seyir.git
cd seyir
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp -n .env.example .env
chmod 600 .env
seyir --help
```

1. Telegram’da konuları açık **özel bir grup** oluştur. Kullanacağın her rol için BotFather ile ayrı bot oluştur, tokenını `.env` içine yaz ve botu gruba ekle. Cursor botuna **Konuları yönet** yetkisi ver. [Telegram kurulumu](docs/botfather.md)
2. Grupta ilgili konuyu aç. Terminalde `seyir id-helper --role mail` veya `seyir id-helper --role mac-m4` çalışırken o konuda `/id mail` ya da `/id mac-m4` yaz. Çıkan grup, konu ve kendi kullanıcı numaranı `.env` dosyasına kaydet. Ardından yardımcıyı Ctrl+C ile kapat.
3. Aşağıda kullanacağın rolün adımlarını tamamla. Botu önce terminalde çalıştırmak macOS izin pencerelerini ve yapılandırma hatalarını görmeyi kolaylaştırır.

### Mail ve Qwen

Apple Mail’de hesabın eşitlenmiş olmalı. `MAIL_ACCOUNT` ve `MAIL_INBOX` için Mail’de görünen adları yaz. `MAIL_INTERNAL_DOMAINS` virgülle ayrılmış şirket alan adlarını kabul eder. Yerel oMLX sunucusunu başlat, `OMLX_BASE_URL` ve `OMLX_MODEL` değerlerini kendi sunucuna göre ayarla. Anahtar `OMLX_API_KEY` veya yerel oMLX ayarlarından okunur.

```sh
seyir mail
```

İlk tarama gerçek gelen kutusunu işler. Gürültü olarak sınıflandırılan iletiler **okundu** işaretlenir. Önemli iletiler ve toplantılar okunmamış kalır. [Sınıflandırma ve bildirimler](docs/mail-rules.md)

### Cursor ve sesli ekran paneli

Mac’te Cursor ve Apple komut satırı geliştirici araçları gerekir. Masaüstü panelinin HTTPS bağlantısı için `cloudflared`, ses ve pencere yayını için `ffmpeg` gerekir. Homebrew kullanıyorsan `brew install cloudflared ffmpeg` ile kurabilirsin. Ekran soruları, konu sohbeti ve özetler için Cursor CLI (`cursor-agent`) ve `CURSOR_API_KEY` ayarla.

```sh
python scripts/install-hooks.py
seyir agent --role mac-m4
```

Kurucu mevcut Cursor hook’larına Seyir’i ekler ve Mac’e özel bir köprü anahtarı üretir. Cursor’u yeniden açıp bir Agent sohbeti başlat. İlk kullanımda macOS’un istediği Ekran Kaydı, Erişilebilirlik, Otomasyon ve Konuşma Tanıma izinlerini ilgili uygulama veya yardımcı için ver. Mac-M4 konusunda `/ekran` yaz, bağlantıyı telefon tarayıcısında aç ve ses için mikrofon iznini ver. Oturumu `/ekran dur` ile kapatabilirsin. [Komutlar, örnekler ve pencere yayını](docs/cursor-telegram-mirror.md)

### Arka planda çalıştırma

Ön planda başlattığın botu Ctrl+C ile kapat. Etkinleştireceğin rolün komutunu çalıştır.

```sh
scripts/mail-service.sh start
scripts/mac-m4-service.sh start
```

Her iki betik de `status` ve `stop` kabul eder. Günlükler `data/logs/` altındadır. Mac-M1 ve Win11 rolleri bu sürümde yalnızca `/ping` yanıtı verir.

### Önceki kurulumdan güncelleme

Projeyi mevcut klasöründe güncelleyip `.venv/bin/python -m pip install -e .` çalıştır. Yeni komut `seyir`. Önceki `bildirim` komutu ve `BILDIRIM_*` ayarları da desteklenir. Aynı ayarı iki adla verirsen `SEYIR_*` değeri kullanılır. Mevcut Telegram konularını, Cursor hook kayıtlarını ve Mac izinlerini kullanmaya devam edebilirsin.

## Veriler nereye gider?

- Mail sınıflandırması yapılandırdığın model sunucusunda yapılır. Varsayılan adres bu Mac’tedir. Özet ve istenen içerik Telegram grubunun üyelerine görünür.
- Etkin Cursor hook’ları IDE olaylarını ve sohbetten bölümleri Telegram’a aktarır. Konu sohbeti, özetler ve ekranla ilgili açık uçlu sorular, ilgili metni veya ekran görüntüsünü yapılandırılan model hizmetine gönderebilir.
- Mac-M4 paneli ekranı Cloudflare tünelinden sunar. **Geçerli bağlantıyı alan kişi oturum boyunca Mac’i kontrol edebilir.** Bağlantıyı yalnız güvendiğin kişilerin bulunduğu grupta kullan. `/ekran dur` ile erişimi sonlandırabilirsin.
- `.env`, özel ağ ayarları ve `data/` altındaki posta önizlemeleri, oturum izleri, anahtarlar, ekran ve ses dosyaları yereldir. Hata bildirirken kendi verilerini ayıklayarak paylaş.

## Test

```sh
python -m unittest discover -s tests -v
```

Testler örnek verilerle çalışır. Telefon mikrofonunu ve gerçek uygulama izinlerini kendi Mac’inde sınamak için [ilk kullanım kontrolünü](docs/user-checklist.md) izleyebilirsin.

[MIT lisansı](LICENSE)

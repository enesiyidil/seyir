# Veri akışı

```mermaid
flowchart LR
  Mail[Apple Mail] --> Rules[Posta kuralları]
  Rules --> Qwen[Yerel Qwen]
  Qwen --> MailBot[Mail botu]
  MailBot --> Topic[Telegram Mail konusu]
  IDE[Cursor hook] --> Bridge[Yerel HTTP köprüsü]
  Bridge --> Agent[Mac botu]
  Agent --> Topics[Telegram oturum konuları]
  Phone[Telefon tarayıcısı] <-->|HTTPS| Tunnel[Cloudflare tüneli]
  Tunnel <--> Panel[Mac ekran ve ses paneli]
  Panel --> Mac[macOS giriş ve görüntü]
  Panel --> Model[Cursor CLI / Grok]
```

Botlar ayrı süreçlerdir. Sayısal grup ve konu kimlikleri bildirimlerin hedefini, kullanıcı listesi komutları kimin verebildiğini belirler. Masaüstü paneli ayrı bir oturum bağlantısıyla açılır. Cursor oturum izleri ve konu hafızası yerel `data/` dizinindedir.

## Geliştirme geçmişi

| Tarih | Projedeki çalışma |
| --- | --- |
| 17 Kasım 2026 | Apple Mail ve Qwen bildirimleri, Cursor oturumlarının Telegram konularına aktarılması. |
| 18 Kasım 2026 | Mobil ekran paneli, Türkçe sesli giriş ve uygulamalarda taslak yazma testleri. |
| 19 Kasım 2026 | İlk Git kaydı, kişisel yapılandırmanın ayrılması, taşınabilir kurulum ve macOS test iş akışı. |

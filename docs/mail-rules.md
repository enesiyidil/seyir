# Mail sınıflandırması

Tarayıcı, `MAIL_ACCOUNT` hesabındaki `MAIL_INBOX` klasöründen okunmamış iletileri alır. Bilinen otomasyon bildirimleri ve toplantı katılım yanıtları önce kurallarla elenir. Kalan iletilerin göndereni, konusu, tarihi ve gövdesinin ilk 3.000 karakteri yapılandırılan Qwen sunucusuna iletilir. `MAIL_INTERNAL_DOMAINS` dış gönderici ipucunu belirler.

| Sınıf | Telegram’a aktarılan | Apple Mail |
| --- | --- | --- |
| Toplantı | Konu, zaman ve katılımcılar | Okunmamış kalır |
| Önemli | Gönderen ve konu | Okunmamış kalır |
| Gürültü | Bildirim üretilmez | Okundu işaretlenir |
| Belirsiz | Bildirim üretilmez | Okunmamış kalır |

Yerel geçmiş `data/processed_mail.json` içinde tutulur. Önemli iletinin bildirimine **içerik** diye yanıt verdiğinde kayıtlı metinden bir önizleme gönderilir. Konuda tek başına **içerik** yazarsan en son bildirime bakılır. `bildirim mail-once` aynı işlemleri bir kez yapar ve çıkar.

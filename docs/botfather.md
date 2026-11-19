# Telegram botlarını bağlama

1. Telegram’da resmi `@BotFather` sohbetinde `/newbot` yaz. Görünen ad olarak **Seyir Mail** veya **Seyir Mac** kullanabilirsin. Kullanıcı adının benzersiz olması ve `bot` ile bitmesi gerekir.
2. Mail için aldığın tokenı `TELEGRAM_BOT_TOKEN_MAIL`, Mac için aldığını `TELEGRAM_BOT_TOKEN_MAC_M4` olarak yerel `.env` dosyasına kaydet.
3. Botu özel forum grubuna ekle. Mac botunu yönetici yapıp konu yönetme izni ver. Böylece oturum konusu açabilir ve o konudaki düz metni alabilir. Mail botunda mesaj içeriği istemek için bildirime doğrudan yanıt verebilirsin.
4. İlgili konuda `/id mail` veya `/id mac-m4` gönderirken terminalde aynı botla `seyir id-helper --role mail` veya `seyir id-helper --role mac-m4` çalışsın. Komutu belirli bir bota yöneltmek için Telegram’ın sunduğu `/id@bot_kullanici_adi` biçimini kullanabilirsin.
5. Botun raporladığı grup ve konu numaralarını ve erişim vereceğin Telegram kullanıcılarının sayısal kimliklerini kaydet. Yardımcıyı Ctrl+C ile kapat. Aynı tokenla tek bir dinleyici çalıştır.

Bir token paylaşılırsa BotFather ile yenile, yerel ayarı güncelle ve ilgili botu yeniden başlat.

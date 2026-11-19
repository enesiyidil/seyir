# Mac’i çalışma saatlerinde uyanık tutma

Bu isteğe bağlı betik priz, ağ ve saat bilgisini kullanır. `config/awake-policy.env.example` dosyasını `config/awake-policy.env` adıyla kopyala. Kendi ağ adını veya ağ geçidini ve çalışma saatlerini gir.

```sh
scripts/awake-policy.sh status
scripts/awake-policy.sh apply
scripts/awake-policy.sh stop
```

`apply` o andaki koşulları değerlendirir. Belirlenen ağda ve prizdeyken çalışma saatlerinde sistem uykusunu erteler. Saatler dışında çalışan uygulamaların CPU kullanımına bakar. Düzenli yeniden değerlendirme için betiği kendi zamanlayıcından çağırabilirsin. Günlük `data/awake/` altında tutulur.

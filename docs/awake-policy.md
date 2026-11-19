# Keep a Mac awake during work hours

This optional script uses the current network, time, and power source. Copy `config/awake-policy.env.example` to `config/awake-policy.env`. Set your network name or gateway and working hours.

```sh
scripts/awake-policy.sh status
scripts/awake-policy.sh apply
scripts/awake-policy.sh stop
```

`apply` evaluates the current conditions. During working hours, the script keeps the Mac awake while it is plugged in on the configured network. Outside those hours it checks application CPU usage. To repeat the evaluation, call the script from your scheduler. Logs are stored in `data/awake/`.

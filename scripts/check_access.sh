#!/usr/bin/env bash
# Run on the VPS: checks that every external API is reachable over HTTPS.
# Usage: bash check_access.sh
hosts=(
  "https://api.telegram.org"
  "https://ngw.devices.sberbank.ru:9443"
  "https://gigachat.devices.sberbank.ru"
  "https://api.giga.chat/v1/models"
  "https://openrouter.ai/api/v1/models"
  "https://fal.run"
  "https://queue.fal.run"
)
for url in "${hosts[@]}"; do
  # -k: Sber endpoints use the Russian Trusted Root CA, which is absent by default; here we test reachability only
  out=$(curl -sk -o /dev/null -w "%{http_code} %{time_total}s" --max-time 10 "$url" 2>&1) || out="FAIL ($out)"
  printf "%-45s %s\n" "$url" "$out"
done
echo "Any HTTP code (even 401/404) = reachable. 000/FAIL = blocked or down."

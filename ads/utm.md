# Deep links (attribution)

The `start` payload is written to `users.source` on the first `/start`.

| Source | Link |
|---|---|
| Ads c1 | https://t.me/imgrsz_bot?start=tgads_c1 |
| Ads c2 | https://t.me/imgrsz_bot?start=tgads_c2 |
| Ads c3 | https://t.me/imgrsz_bot?start=tgads_c3 |
| Ads c4 | https://t.me/imgrsz_bot?start=tgads_c4 |
| Ads c5 | https://t.me/imgrsz_bot?start=tgads_c5 |
| Landing hero / prices / nav | `landing_hero` · `landing_prices` · `landing_nav` |
| Case page | `case` · `case_proto` · `case_footer` |
| Friends / manual | https://t.me/imgrsz_bot?start=friends |

Payload rules: `[a-zA-Z0-9_-]`, ≤64 chars.

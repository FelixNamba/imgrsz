# PRODUCT — imgrsz

Requirements and metrics: `AI/PRD.md`. Texts: `bot/app/texts.py`. Prices: `bot/app/config.py`.

## User flow
```mermaid
flowchart TD
  S[/start + source/] --> B{New?}
  B -- yes --> W[+500 р. welcome]
  B -- no --> H[welcome back]
  W & H --> I[Sends image]
  I --> C{Caption?}
  C -- no --> Q[Ask: what to do?] --> T[User text]
  C -- yes --> T
  T --> L[GigaChat brief + plan]
  L --> R{Result}
  R -- refuse --> X[🚫 reason, job refused]
  R -- question --> Q2[❓ question] --> E[User answer] --> L
  R -- plan --> BR[📝 Brief + price + ✅/✏️]
  BR -- ✏️ --> E
  BR -- ✅ --> M{Balance ≥ price?}
  M -- no --> N[Not enough р.]
  M -- yes --> P[AI edit? → Pillow ops] --> D[📎 File + charge + disclaimer]
  P -- error --> F[Failed, no charge]
```
Edit loop limit: 5 iterations per image.

## Pricing
Brief 0 р. · technical 5 р. · AI 30 р. · welcome 500 р. Charged only after successful delivery.

## Supported tasks (examples users write)
| Request | Plan |
|---|---|
| «квадрат для госуслуг до 1 МБ» | crop_ratio 1:1 → max_size_kb 1000 |
| «фото 35×45 для визы» | print_size 35×45@300dpi → jpeg |
| «расширь до 16:9 для обложки» | AI outpaint (ai_ratio 16:9) → resize |
| «сделай белый фон» | AI background replace → jpeg |
| «HEIC в JPG, убери метаданные» | format jpeg |
| «до 200 КБ, ширина 800» | resize fit 800 → max_size_kb 200 |

## Bot profile (set in @BotFather)
- **Name:** Поправь размер картинки (landing brand: Image resizer)
- **About (≤120):** Подгоню фото под требования формы: размер, вес, формат, пропорции, без метаданных. Расширю и улучшу с ИИ.
- **Description (≤512):** Картинка не грузится? Пришлите её и напишите своими словами, что нужно: «1080×1080 до 500 КБ», «расширь до 16:9», «фото 35×45 на белом фоне». Я составлю бриф, вы подтвердите — и получите готовый файл. 🎁 500 р. на старте.
- **Commands:** `start - Начать`, `help - Как это работает`, `balance - Баланс`

# Lavender Hill Clothing — Backend

Django 5.2 + DRF API for the Next.js storefront, plus a custom staff dashboard
(Django templates + HTMX, **not** `django.contrib.admin`).

Built to `BACKEND_IMPL_GUIDE.md`. The API contract in §8 of that guide is the
source of truth shared with `FRONTEND_IMPL_GUIDE.md`.

## Running locally (Windows / PowerShell)

```powershell
cd backend
docker compose up -d db          # Postgres 16 on host port 5433
.\.venv\Scripts\Activate.ps1     # or use .\.venv\Scripts\python.exe directly
py manage.py migrate
py manage.py seed_demo           # 24 products, colours, stock, content
py manage.py seed_dummy          # customers, order history, reviews, enquiries
py manage.py runserver
```

> **Port 5433, not 5432.** This machine already runs a native PostgreSQL
> service on 5432, so the container maps to 5433 to avoid clashing with it.
> `DATABASE_URL` in `.env` points there. To go back to zero-setup dev, set
> `DATABASE_URL=sqlite:///db.sqlite3`.

| What | Where |
|---|---|
| API root | http://127.0.0.1:8000/api/v1/ |
| Swagger UI | http://127.0.0.1:8000/api/v1/docs/ |
| OpenAPI schema | http://127.0.0.1:8000/api/v1/schema/ |
| Staff dashboard | http://127.0.0.1:8000/dashboard/ |
| Media (dev) | http://127.0.0.1:8000/media/ |

Demo logins created by `seed_demo`:

| Role | Email | Password |
|---|---|---|
| Staff (dashboard) | `staff@lavenderhill.test` | `lavender123` |
| Customer | `hello@lavenderhill.test` | `lavender123` |

Demo promo codes: `SOFT10` (10% off), `WELCOME15` (£15 off over £120).

For your own superuser: `py manage.py createsuperuser`.

## Layout

```
backend/
├─ config/              settings (env-driven), urls, wsgi/asgi
├─ apps/
│  ├─ core/             TimeStamped base, slug/money helpers
│  ├─ accounts/         email-login User, Address, JWT auth views
│  ├─ catalog/          Category, Collection, Fabric, Size, Product,
│  │                    ProductColour, ProductImage, ProductVariant, Review
│  ├─ cart/             Cart/CartItem + guest cart-token resolution
│  ├─ orders/           Discount, Order, OrderItem, checkout service, payments seam
│  ├─ wishlist/         WishlistItem
│  ├─ marketing/        Journal, Newsletter, SiteSettings, HomeSection, Contact
│  ├─ api/              DRF router aggregating every viewset → /api/v1/
│  └─ dashboard/        staff views, forms, HTMX endpoints
├─ templates/dashboard/ base + one folder per screen
├─ static/dashboard/    dashboard.css, dashboard.js
├─ media/               uploaded product images (dev)
└─ tests/               pytest-django suite (116 tests)
```

## Seed data

Two commands, deliberately separate — one builds the shop, the other simulates
it trading.

| Command | Creates |
|---|---|
| `seed_demo` | Catalogue and content: sizes, fabrics, categories, collections, 24 products with 2–4 colourways each, per-size stock, generated placeholder imagery, journal posts, site settings, homepage blocks, discount codes. |
| `seed_dummy` | Trading activity: customers with addresses, 80 backdated orders across every status, wishlists, reviews (some awaiting moderation), contact enquiries, newsletter subscribers. |
| `seed_images` | Swaps the generated placeholder cards for real photographs of people modelling clothing, downloaded into `MEDIA_ROOT`. Needs network; imagery only — never touches orders or stock. |

```powershell
py manage.py seed_demo  --flush            # rebuild the catalogue from scratch
py manage.py seed_dummy --flush            # clear and regenerate the activity
py manage.py seed_dummy --customers 60 --orders 150 --days 180
```

`seed_dummy` backdates `created_at` on orders and reviews so the dashboard's
revenue KPIs, "new customers this week" and moderation queue all have a
believable shape. Historical orders **do not** decrement live stock — they
represent trading that already settled, so inventory keeps showing what is on
the shelf today. Only real checkout moves stock.

Every generated account uses an `@example.com` address (which is how `--flush`
finds them again) and the password `lavender123`.

### Imagery

`seed_demo` draws flat, branded placeholder cards with Pillow so the store works
with no network at all. `seed_images` then replaces them with curated
photographs of people modelling clothing — the catalogue is womenswear, so the
imagery should show garments being worn:

```powershell
py manage.py seed_images                  # everything
py manage.py seed_images --only products  # or categories|fabrics|collections|journal|home
py manage.py seed_images --force          # re-download
```

Photos are chosen per category (a dress product gets dress shots) and each
colourway gets a different one, so clicking a swatch visibly changes the gallery.
The pool lives in `apps/catalog/imagery.py` with a description per photo, used as
alt text. Downloads land in `MEDIA_ROOT`, so it only needs network once.

These are Unsplash placeholders standing in until real product photography is
shot — replace them per product in the dashboard's product editor, not here.

## The inventory model

**SKU = colour × size.** This is the rule everything else follows:

- *Stock left for a SKU* → `ProductVariant.stock_quantity`
- *Stock for a colour* → `ProductColour.stock` (sum of its active variants)
- *Product in stock* → any active variant with stock > 0 (`Product.in_stock`)
- *Total units* → `Product.total_stock`

Stock is decremented at **order placement**, inside `transaction.atomic()` with
`select_for_update()` on every variant, so two concurrent checkouts can never
both take the last item (`tests/test_cart_checkout.py::test_two_checkouts_cannot_both_take_the_last_item`).
Cancel and refund put it back exactly once via `Order.restock()`.

## The product editor

`/dashboard/products/{id}/edit/` is the screen the whole model is arranged around:

- **Details** — name, copy, category, fabrics, collections, prices, badges, SEO.
- **Colours available** — an inline formset of colourways (name + swatch picker
  + order + active), saved with the product.
- Per colour, two live panels driven by HTMX:
  - **Images** — drag-and-drop multi-upload, thumbnails, set-primary, delete.
    Images hang off the *colour*, so the PDP gallery swaps with the swatch.
  - **Stock left by size** — a row per `Size` with an editable quantity, an
    auto-generated SKU (`LH-{product}-{colour}-{size}`), an optional price
    override and an active toggle. The colour subtotal updates live as you type.
    Blanking a quantity stops offering that colour in that size.

`/dashboard/inventory/` is the cross-product view of the same data, with
low/out-of-stock filters, inline row saves and a bulk save.

## Payments

Checkout calls `apps/orders/payments.py::create_payment(order)`, which returns a
`payment_ref`, a `client_secret` and a status. `MockProvider` marks the order paid
immediately; `StripeProvider` is stubbed for M10. Switch with `PAYMENT_PROVIDER`
in `.env` — no changes to checkout or order code.

## Environment

Copy `.env.example` to `.env`. Key settings:

| Var | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `postgres://…@127.0.0.1:5433/lavenderhill` | the compose container; `sqlite:///db.sqlite3` also works |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000` | the Next.js origin |
| `FREE_SHIPPING_THRESHOLD` | `50` | £ — above this, shipping is free |
| `STANDARD_SHIPPING_FEE` / `EXPRESS_SHIPPING_FEE` | `3.95` / `6.95` | |
| `TAX_RATE` | `0` | percent; VAT-inclusive pricing for now |
| `PAYMENT_PROVIDER` | `mock` | `mock` \| `stripe` |
| `JWT_ACCESS_MINUTES` / `JWT_REFRESH_DAYS` | `30` / `7` | |
| `SEED_DEMO` | `0` | what `runserver` does to the DB on boot — see below |

### `SEED_DEMO` — seeding on server start

| Value | On every `runserver` start |
|---|---|
| `0` | Nothing. The database is left exactly as it is. |
| `1` | Wipe all data, then run `seed_demo`. Re-runs on **every autoreload restart**, so each code edit costs ~6s and throws away any test orders you placed. |
| `2` | Run `seed_demo` only if the catalogue has no products; otherwise do nothing. |
| `3` | Wipe all data and stop — no demo content. Staff accounts are kept (and `staff@lavenderhill.test` / `lavender123` is created if none exists) so `/dashboard/` is still reachable, and the default size chart (XS–XL, One Size) is restored because stock is held per size — with no `Size` rows the product editor's stock grid has no rows to fill in. |

Only `runserver` triggers this — `migrate`, `pytest`, `shell` and any WSGI/ASGI
server are unaffected. Under the autoreloader it runs once per restart, in the
serving child process only. To apply the policy by hand:

```powershell
py manage.py apply_seed_policy             # use SEED_DEMO from .env
py manage.py apply_seed_policy --mode 3    # override for one run
```

Wiping clears database rows only; previously generated files under `media/` stay
on disk. Logic lives in `apps/core/seeding.py`.

A wipe waits at most 5s for a database lock (`lock_timeout`). If something else
is holding one — a second `runserver`, a **pgAdmin query tab**, an open `psql`
transaction — the wipe is skipped with a warning and the server starts anyway,
rather than hanging before it binds a port. Close the other session and restart.

## Frontend integration

The Next.js storefront in `../frontend` consumes this API directly from Server
Components (`BACKEND_URL`, server-only) and places real orders through its
`/api/checkout` BFF route. Start this backend first — the storefront has no mock
fallback for catalogue data. See `../frontend/README.md`.

## Auth

- Storefront: JWT (`/api/v1/auth/login|register|refresh`). Access + refresh
  tokens are meant to live in httpOnly cookies set by the Next.js BFF.
- Guests: an `X-Cart-Token` header (or `cart-token` cookie) identifies the cart.
  On login or register the guest cart is merged into the user's cart automatically.
- Dashboard: Django session auth, staff-only, with its own login page.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest          # 116 tests
.\.venv\Scripts\python.exe -m pytest -k stock # just the stock rules
```

Covers stock properties and oversell prevention, PLP filters/pagination, PDP
nesting, cart stock validation, discounts, the checkout transaction, review
approval → rating recompute, dashboard permission gating, and the product-editor
save paths.

## Frontend integration

1. Backend running on `http://127.0.0.1:8000` (seeded).
2. Frontend `.env.local`: `BACKEND_URL=http://127.0.0.1:8000`,
   `NEXT_PUBLIC_MEDIA_URL=http://127.0.0.1:8000/media`.
3. `next.config.ts` → `images.remotePatterns` allowing `127.0.0.1:8000/media/**`.
4. `GET /api/v1/content/home` drives the homepage; `/content/site` drives the
   announcement bar, USPs, footer and FAQs.

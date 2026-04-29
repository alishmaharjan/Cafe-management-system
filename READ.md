# Chiya Garden — Cafe Management System

A full-featured point-of-sale and cafe management system built with Django, designed specifically for **Chiya Garden** (चिया Garden). Covers everything from table management and order-taking to payments, inventory tracking, shift management, and daily reports.

---

## Features

- **POS Terminal** — 3-panel layout: table map, menu browser, live cart. Supports dine-in (17 tables) and takeaway orders.
- **Cash & FonePay QR payments** — Cash with change calculation; FonePay with merchant QR display.
- **Per-item order cancellation** — Remove individual items from an active order without cancelling the whole table.
- **Discount support** — Apply NPR discounts per order at checkout.
- **Dashboard** — Live stats: today's revenue, orders, top products, activity feed.
- **Inventory** — Track ingredient stock levels, low-stock alerts, purchase and adjustment logs.
- **Reports** — Daily sales, inventory usage, and day-close summary. CSV export available.
- **Shift Management** — Open/close staff shifts with opening and closing cash tracking.
- **Role-based access** — Admin (is_staff) sees everything; regular staff only see POS and Shifts.
- **Django Admin** — Manage menu, tables, orders, payments, and ingredients from a clean admin panel.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django 6.0.4 |
| Database | SQLite (file: `chiya_garden.sqlite3`) |
| Frontend | Bootstrap 5.3 + Bootstrap Icons + Vanilla JS |
| Auth | Django built-in auth |
| Timezone | Asia/Kathmandu |
| Python | 3.12 |

---

## Project Structure

```
Cafe-management-system/
├── READ.md
└── A-cafe/
    ├── requirements.txt
    ├── venv/
    └── cafe_system/
        ├── manage.py
        ├── chiya_garden.sqlite3
        ├── cafe_system/          ← Django project config
        │   ├── settings.py
        │   └── urls.py
        └── core/                 ← Main application
            ├── models.py
            ├── views.py
            ├── admin.py
            ├── urls.py
            ├── services.py
            ├── templates/core/
            │   ├── base.html
            │   ├── login.html
            │   ├── pos.html
            │   ├── dashboard.html
            │   ├── inventory.html
            │   ├── reports.html
            │   └── shifts.html
            ├── static/core/
            │   ├── style.css
            │   ├── pos.js
            │   ├── logo.png
            │   └── fonepay_qr.png
            └── management/commands/
                ├── setup_tables.py   ← creates T01–T17
                └── seed_menu.py      ← seeds full Chiya Garden menu
```

---

## Setup & Run

### 1. Clone and enter the project

```bash
git clone <repo-url>
cd Cafe-management-system/A-cafe
```

### 2. Create and activate virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run migrations

```bash
cd cafe_system
python manage.py migrate
```

### 5. Create an admin (superuser) account

```bash
python manage.py createsuperuser
```

### 6. Seed tables and menu

```bash
python manage.py setup_tables   # creates T01–T17
python manage.py seed_menu      # loads all categories and ~93 products
```

### 7. Start the server

```bash
python manage.py runserver
```

Open `http://127.0.0.1:8000` in your browser and log in.

> **Note:** Always use the full venv python path if `python` is not aliased:
> `/home/<user>/cg/Cafe-management-system/A-cafe/venv/bin/python`

---

## User Roles

| Role | How to create | Access |
|---|---|---|
| Admin | `createsuperuser` or Django admin → mark `is_staff = True` | POS, Dashboard, Inventory, Reports, Shifts, Admin panel |
| Staff | Django admin → create user, leave `is_staff = False` | POS and Shifts only |

---

## Pages

| URL | Page | Access |
|---|---|---|
| `/` or `/pos/` | POS Terminal | All staff |
| `/dashboard/` | Live dashboard & stats | Admin |
| `/inventory/` | Ingredient stock tracker | Admin |
| `/reports/` | Sales & day-close reports | Admin |
| `/shifts/` | Shift open/close | All staff |
| `/admin/` | Django admin panel | Admin |
| `/login/` | Staff login | Public |

---

## API Endpoints

All endpoints are prefixed with `/api/`.

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/tables` | List tables with live status |
| GET | `/api/categories` | Menu categories |
| GET | `/api/products` | Products (filter by `?category_id=`) |
| GET/POST | `/api/orders` | List open orders / create order |
| GET | `/api/orders/<id>` | Order detail with items |
| POST | `/api/orders/<id>/items` | Add item to order |
| PATCH/DELETE | `/api/orders/<id>/items/<item_id>` | Update qty / remove item |
| POST | `/api/orders/<id>/checkout` | Pay and close order |
| POST | `/api/orders/<id>/cancel` | Cancel entire order |
| GET | `/api/dashboard/overview` | Dashboard stats |
| GET | `/api/dashboard/activity-logs` | Recent activity feed |
| GET | `/api/inventory/ingredients` | Ingredient list |
| GET | `/api/inventory/ingredients/low-stock` | Low stock alert list |
| POST | `/api/inventory/purchase` | Record stock purchase |
| POST | `/api/inventory/adjustment` | Manual stock adjustment |
| GET | `/api/reports/sales` | Sales report (date range) |
| GET | `/api/reports/day-close` | Day-close summary |
| GET | `/api/shifts/current` | Current open shift |
| POST | `/api/shifts/open` | Open a shift |
| POST | `/api/shifts/<id>/close` | Close a shift |

---

## Menu

The full Chiya Garden menu is seeded via `python manage.py seed_menu`. It covers 15 categories and ~93 products:

| Category | Examples |
|---|---|
| Black Chiya | Black Tea, Masala Black Chiya, Lemon Chiya |
| Milk Chiya | Classic Chiya, Masala Chiya, Peach Tea |
| Coffee | Black Coffee, Milk Cold Coffee |
| Lemon Drinks | Cold Lemon, Hot Lemon with Honey |
| Lassi | Plain Lassi, Banana Lassi |
| Chiya ko Sathi | Aalu Chop, Pakoda, Samosa |
| Sadeko | Wai Wai, Chicken, Sukuti |
| Veg Fry | French Fry, Masala French Fry |
| Chilly | Buff, Pork, Chicken Chilly |
| Meat & Fry | Pork Fry, Chicken Drumstick, Lollipop |
| MoMo | Buff/Chicken × Steam/Fry/C.MoMo/Jhol, Kurkure |
| Noodles | Chowmien, Thukpa, Keema Noodles |
| Fried Rice | Veg, Egg, Buff, Chicken, Pork, Mix |
| Soft Drinks | Coke, Fanta, Slice, Real Juice |
| Energy Drinks | Red Bull, X-Treme |

To add or edit products after seeding, use the Django admin panel at `/admin/`.

---

## Payments

**Cash** — Enter amount tendered; change is calculated automatically.

**FonePay QR** — The merchant QR is displayed from:
```
core/static/core/fonepay_qr.png
```
Replace this file with your actual FonePay merchant QR image. If the file is missing the modal shows a placeholder and the app continues to work.

---

## Branding

Brand colors are defined as CSS variables in `core/static/core/style.css`:

```css
--cg-dark:   #1a0800   /* navbar / dark backgrounds */
--cg-orange: #c85a00   /* primary brand color       */
--cg-amber:  #e87a1e   /* hover states              */
--cg-gold:   #d4a017   /* borders / headings        */
--cg-green:  #2d7a35   /* free table / success      */
```

The cafe logo is loaded from `core/static/core/logo.png`. An icon fallback is shown if the file is missing.

---

## License

Private — Chiya Garden internal use only.

# Kijiji Tanzania — Neon PostgreSQL + Cloudflare R2

## Environment variables (Render → Environment)

| KEY | Value |
|-----|--------|
| `DATABASE_URL` | Neon connection string (`postgresql://...`) |
| `SECRET_KEY` | Random long secret for Flask sessions |
| `BREVO_API_KEY` | Brevo API key |
| `MAIL_FROM_EMAIL` | Verified sender on Brevo |
| `MAIL_FROM_NAME` | Kijiji Tanzania (optional) |
| `R2_ACCESS_KEY_ID` | Cloudflare R2 access key |
| `R2_SECRET_ACCESS_KEY` | Cloudflare R2 secret |
| `R2_BUCKET_NAME` | Bucket name |
| `R2_ENDPOINT_URL` | `https://<ACCOUNT_ID>.r2.cloudflarestorage.com` |
| `R2_PUBLIC_URL` | Public base URL e.g. `https://pub-xxxx.r2.dev` (no trailing slash) |
| `VAPID_PRIVATE_KEY` / `VAPID_PUBLIC_KEY` | Web Push (optional) |
| `GOOGLE_CLIENT_ID` | (optional, or keep in code) |

## What changed

1. **db.py** — SQLite → Neon PostgreSQL (`psycopg2`). Compatibility layer keeps `?` placeholders and `lastrowid`.
2. **storage.py** — All media uploads go to Cloudflare R2; DB stores the **public URL**.
3. **helpers.py** — `avatar_url` uses R2 URLs; OTP email uses **Brevo** (`email_service.py`).
4. **posts / profile / chat / linkup / kijiji / account** — `file.save(...)` replaced with `upload_werkzeug_file(...)`.
5. **requirements.txt** — added `psycopg2-binary`, `boto3`, etc.

## Deploy steps

1. Create Neon project → copy connection string → set `DATABASE_URL` on Render.
2. Create R2 bucket + API token → set all `R2_*` vars. Enable public access / r2.dev URL.
3. Deploy these Python files (replace existing ones). Keep `templates/`, `static/` (icons, sw, music) from zip.
4. First boot runs `init_db()` and creates all tables on Neon (empty database).
5. Test: register (OTP via Brevo), create post with image → should appear with R2 URL in `posts.file_path`.

## Notes

- Old SQLite `database.db` is **not** migrated automatically. Start fresh on Neon unless you run a one-time migration.
- Legacy local filenames in DB will resolve via `media_url()` only if still on disk; new uploads are full R2 URLs.
- Render free tier blocks SMTP; always use Brevo HTTPS.

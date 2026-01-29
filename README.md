# simple-notes-app-312508-312525

## Database schema initialization (SQLite)

The SQLite schema is initialized and migrated by:

- `database/init_db.py`

It is safe and deterministic to run multiple times:
- Creates the `notes` table if it does not exist.
- If the table exists but is missing required columns, it **adds them non-destructively**.
- Maintains `notes.updated_at` automatically using an SQLite trigger (SQLite does not support `ON UPDATE` column clauses).

To (re)initialize or recover a missing table, run from the `database/` directory:

```bash
python3 init_db.py
```

You can inspect tables/columns using the helper shell:

```bash
python3 db_shell.py
```
#!/usr/bin/env python3
from webapp_migration import create_tables

print("Running database migration...")
create_tables()
print("Migration complete. Added retry columns to signals table.") 
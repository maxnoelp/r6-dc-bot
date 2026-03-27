"""
db package — Database layer for the R6 tracking bot.

Exposes:
- database.py: asyncpg pool initialisation and accessor.
- models.py: all SQL query functions (upsert/get for users, configs, snapshots).
"""

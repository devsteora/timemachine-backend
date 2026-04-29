-- One-time setup for local dev. Run as superuser:
--   psql -U postgres -d postgres -f setup_local_postgres.sql
-- Align with DATABASE_URL: postgresql://admin:adminpassword@localhost:5432/timetracker

CREATE ROLE admin WITH LOGIN PASSWORD 'adminpassword';
CREATE DATABASE timetracker OWNER admin;

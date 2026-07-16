-- Migration: Make user email column nullable
-- Date: 2026-06-18
-- Description: Modify users table to make email column nullable to support optional email during user creation

ALTER TABLE users ALTER COLUMN email DROP NOT NULL;

-- Notes:
-- This migration allows users to be created without an email address.
-- The email field remains unique when provided.

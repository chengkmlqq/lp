-- Add avatar_path column to users table
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS avatar_path VARCHAR(500);

-- Create storage bucket for token images with public access
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
  'token-images',
  'token-images',
  true,
  5242880,
  ARRAY['image/png', 'image/jpeg', 'image/webp', 'image/gif']
)
ON CONFLICT (id) DO UPDATE SET
  public = true,
  file_size_limit = 5242880,
  allowed_mime_types = ARRAY['image/png', 'image/jpeg', 'image/webp', 'image/gif'];

-- Allow public read access to token-images bucket
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE schemaname = 'storage' AND tablename = 'objects' AND policyname = 'Public token images are accessible by everyone'
  ) THEN
    CREATE POLICY "Public token images are accessible by everyone"
    ON storage.objects FOR SELECT
    USING (bucket_id = 'token-images');
  END IF;
END $$;

-- Allow uploads to token-images bucket
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE schemaname = 'storage' AND tablename = 'objects' AND policyname = 'Allow uploads to token-images'
  ) THEN
    CREATE POLICY "Allow uploads to token-images"
    ON storage.objects FOR INSERT
    WITH CHECK (bucket_id = 'token-images');
  END IF;
END $$;

-- Allow updates to token-images bucket
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE schemaname = 'storage' AND tablename = 'objects' AND policyname = 'Allow updates to token-images'
  ) THEN
    CREATE POLICY "Allow updates to token-images"
    ON storage.objects FOR UPDATE
    USING (bucket_id = 'token-images');
  END IF;
END $$;

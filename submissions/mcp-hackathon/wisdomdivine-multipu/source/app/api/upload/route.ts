import { getAuth, getClientIp } from "@/lib/auth";
import { uploadLimiter } from "@/lib/rate-limit";
import { MAX_IMAGE_SIZE, ALLOWED_IMAGE_TYPES } from "@/lib/validations";
import { createAdminSupabase } from "@/lib/supabase/server";
import { assertTrustedOrigin } from "@/lib/request-security";

/**
 * POST /api/upload — Upload a token image.
 *
 * Accepts multipart/form-data with a single "file" field.
 * Stores in Supabase Storage bucket "token-images".
 * Returns the public URL.
 *
 * Production: replace with Arweave upload via Irys for permanent storage.
 */
export async function POST(request: Request) {
  const originError = assertTrustedOrigin(request);
  if (originError) {
    return Response.json({ error: originError }, { status: 403 });
  }

  const ip = getClientIp(request);
  if (!uploadLimiter.check(ip)) {
    return Response.json(
      { error: "Upload rate limited. Try again shortly." },
      { status: 429 }
    );
  }

  const auth = await getAuth(request);
  if (!auth.isLoggedIn) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const formData = await request.formData();
    const file = formData.get("file") as File | null;

    if (!file) {
      return Response.json({ error: "No file provided" }, { status: 400 });
    }

    // Validate file type
    if (!ALLOWED_IMAGE_TYPES.includes(file.type as typeof ALLOWED_IMAGE_TYPES[number])) {
      return Response.json(
        { error: `Invalid file type. Allowed: ${ALLOWED_IMAGE_TYPES.join(", ")}` },
        { status: 400 }
      );
    }

    // Validate file size
    if (file.size > MAX_IMAGE_SIZE) {
      return Response.json(
        { error: `File too large. Max ${MAX_IMAGE_SIZE / 1024 / 1024}MB` },
        { status: 400 }
      );
    }

    const supabase = createAdminSupabase();

    // Generate unique filename (sanitize wallet address prefix)
    const ext = file.name.split(".").pop()?.toLowerCase() || "png";
    const cleanWallet = auth.walletAddress.replace(/[^a-zA-Z0-9]/g, "_");
    const filename = `${cleanWallet}/${Date.now()}-${crypto.randomUUID()}.${ext}`;

    const buffer = Buffer.from(await file.arrayBuffer());

    const { error: uploadError } = await supabase.storage
      .from("token-images")
      .upload(filename, buffer, {
        contentType: file.type,
        upsert: true,
      });

    if (uploadError) throw uploadError;

    // Get public URL
    const { data: urlData } = supabase.storage
      .from("token-images")
      .getPublicUrl(filename);

    return Response.json({ url: urlData.publicUrl }, { status: 201 });
  } catch (err) {
    console.error("[API] POST /upload error:", err);
    return Response.json(
      { error: "Upload failed" },
      { status: 500 }
    );
  }
}

import { getAuth, getClientIp } from "@/lib/auth";
import { apiLimiter } from "@/lib/rate-limit";
import { createAdminSupabase } from "@/lib/supabase/server";
import { randomBytes } from "crypto";

export async function GET(request: Request) {
  const ip = getClientIp(request);
  if (!apiLimiter.check(ip)) {
    return Response.json({ error: "Rate limited" }, { status: 429 });
  }

  const auth = await getAuth(request);
  if (!auth.isLoggedIn) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const supabase = createAdminSupabase();
    const { data: keys, error } = await supabase
      .from("developer_api_keys")
      .select("id, name, api_key, created_at, revoked")
      .eq("wallet_address", auth.walletAddress)
      .eq("revoked", false)
      .order("created_at", { ascending: false });

    if (error) throw error;

    // Mask key except first 8 characters (e.g. mp_abcde...)
    const maskedKeys = (keys ?? []).map((k) => ({
      id: k.id,
      name: k.name,
      api_key: k.api_key.substring(0, 8) + "..." + k.api_key.substring(k.api_key.length - 4),
      created_at: k.created_at,
      revoked: k.revoked,
    }));

    return Response.json({ keys: maskedKeys });
  } catch (err) {
    console.error("[API] GET /developer/api-keys error:", err);
    return Response.json({ error: "Failed to fetch API keys" }, { status: 500 });
  }
}

export async function POST(request: Request) {
  const ip = getClientIp(request);
  if (!apiLimiter.check(ip)) {
    return Response.json({ error: "Rate limited" }, { status: 429 });
  }

  const auth = await getAuth(request);
  if (!auth.isLoggedIn) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const { name } = await request.json();
    if (!name || typeof name !== "string") {
      return Response.json({ error: "Key name is required" }, { status: 400 });
    }

    const supabase = createAdminSupabase();

    // Get user id
    const { data: user, error: userError } = await supabase
      .from("users")
      .select("id")
      .eq("wallet_address", auth.walletAddress)
      .single();

    if (userError || !user) {
      return Response.json({ error: "User record not found" }, { status: 404 });
    }

    // Generate api key
    const rawKey = "mp_" + randomBytes(24).toString("hex");

    const { data: newKey, error: insertError } = await supabase
      .from("developer_api_keys")
      .insert({
        user_id: user.id,
        wallet_address: auth.walletAddress,
        name: name.trim(),
        api_key: rawKey,
        revoked: false,
      })
      .select()
      .single();

    if (insertError) throw insertError;

    return Response.json({ key: newKey }, { status: 201 });
  } catch (err) {
    console.error("[API] POST /developer/api-keys error:", err);
    return Response.json({ error: "Failed to create API key" }, { status: 500 });
  }
}

export async function DELETE(request: Request) {
  const ip = getClientIp(request);
  if (!apiLimiter.check(ip)) {
    return Response.json({ error: "Rate limited" }, { status: 429 });
  }

  const auth = await getAuth(request);
  if (!auth.isLoggedIn) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const { searchParams } = new URL(request.url);
    const keyId = searchParams.get("id");

    if (!keyId) {
      return Response.json({ error: "Key ID is required" }, { status: 400 });
    }

    const supabase = createAdminSupabase();

    // Check key ownership first
    const { data: key, error: checkError } = await supabase
      .from("developer_api_keys")
      .select("id")
      .eq("id", keyId)
      .eq("wallet_address", auth.walletAddress)
      .single();

    if (checkError || !key) {
      return Response.json({ error: "API key not found or unauthorized" }, { status: 404 });
    }

    // Revoke key
    const { error: revokeError } = await supabase
      .from("developer_api_keys")
      .update({ revoked: true })
      .eq("id", keyId);

    if (revokeError) throw revokeError;

    return Response.json({ success: true });
  } catch (err) {
    console.error("[API] DELETE /developer/api-keys error:", err);
    return Response.json({ error: "Failed to revoke API key" }, { status: 500 });
  }
}

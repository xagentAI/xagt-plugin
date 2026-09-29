import { apiRoute, jsonResponse } from "@/lib/http";
import { getContainer } from "@/server/container";
import { parseEvidenceQuery, toEvidenceResponse } from "@/validation/evidence";
import { parsePaymentIntentId } from "@/validation/payment-intents";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export const GET = apiRoute(
  "/v1/payment-intents/[id]/evidence",
  async ({ request, requestId }, context: RouteContext<"/v1/payment-intents/[id]/evidence">) => {
    const { id } = await context.params;
    const query = parseEvidenceQuery(new URL(request.url).searchParams);
    const page = await getContainer().getPaymentEvidence(parsePaymentIntentId(id), query);
    return jsonResponse(toEvidenceResponse(page), { requestId });
  },
);

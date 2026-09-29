import { apiRoute, jsonResponse } from "@/lib/http";
import { getContainer } from "@/server/container";
import { parsePaymentIntentId, toPaymentIntentResponse } from "@/validation/payment-intents";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export const GET = apiRoute(
  "/v1/payment-intents/[id]",
  async ({ requestId }, context: RouteContext<"/v1/payment-intents/[id]">) => {
    const { id } = await context.params;
    const intent = await getContainer().getPaymentIntent(parsePaymentIntentId(id));
    return jsonResponse(toPaymentIntentResponse(intent), { requestId });
  },
);

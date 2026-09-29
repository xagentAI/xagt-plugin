import { apiRoute, jsonResponse } from "@/lib/http";
import { readJsonBody } from "@/lib/request-body";
import { getContainer } from "@/server/container";
import { parseCreatePaymentIntentRequest, toPaymentIntentResponse } from "@/validation/payment-intents";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export const POST = apiRoute("/v1/payment-intents", async ({ request, requestId, log }) => {
  const body = await readJsonBody(request);
  const input = parseCreatePaymentIntentRequest(body, new Date());
  const intent = await getContainer().createPaymentIntent(input);
  log.info("payment intent created", { intentIdPrefix: intent.id.slice(0, 11) });
  return jsonResponse(toPaymentIntentResponse(intent), { requestId, status: 201 });
});

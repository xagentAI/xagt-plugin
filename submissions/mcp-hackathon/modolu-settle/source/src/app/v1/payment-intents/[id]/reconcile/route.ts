import { apiRoute, jsonResponse } from "@/lib/http";
import { assertNoRequestBody } from "@/lib/request-body";
import { getContainer } from "@/server/container";
import { parsePaymentIntentId, toPaymentIntentResponse } from "@/validation/payment-intents";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export const POST = apiRoute(
  "/v1/payment-intents/[id]/reconcile",
  async ({ request, requestId, log }, context: RouteContext<"/v1/payment-intents/[id]/reconcile">) => {
    const { id } = await context.params;
    const intentId = parsePaymentIntentId(id);
    await assertNoRequestBody(request);
    const outcome = await getContainer().reconcilePaymentIntent(intentId, requestId);
    log.info("payment intent reconciled", {
      intentIdPrefix: outcome.intent.id.slice(0, 11),
      resultStatus: outcome.intent.status,
      candidateCount: outcome.candidateCount,
      latestBlock: outcome.latestBlock,
      applied: outcome.applied,
    });
    return jsonResponse(toPaymentIntentResponse(outcome.intent), { requestId });
  },
);

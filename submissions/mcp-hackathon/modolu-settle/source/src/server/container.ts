/**
 * Composition root: wires concrete adapters (Alchemy, Drizzle/pg) into the
 * application services. Built once per process; route handlers call
 * `getContainer()` and never construct pools, clients or repositories.
 */
import "server-only";

import { getDatabase } from "@/db/client";
import type { CreatePaymentIntentInput, PaymentIntent } from "@/domain/payment-intent";
import { createAlchemyBaseProvider } from "@/integrations/chain/alchemy-base-provider";
import { getConfig } from "@/lib/config";
import type { EvidencePage } from "@/ports/payment-repository";
import { createDrizzlePaymentRepository } from "@/repositories/drizzle-payment-repository";
import { createPaymentIntent } from "@/services/create-payment-intent";
import { getPaymentEvidence, type GetPaymentEvidenceOptions } from "@/services/get-payment-evidence";
import { getPaymentIntent } from "@/services/get-payment-intent";
import { reconcilePaymentIntent, type ReconcileOutcome } from "@/services/reconcile-payment-intent";

export interface Container {
  createPaymentIntent(input: CreatePaymentIntentInput): Promise<PaymentIntent>;
  getPaymentIntent(id: string): Promise<PaymentIntent>;
  reconcilePaymentIntent(id: string, requestId: string): Promise<ReconcileOutcome>;
  getPaymentEvidence(id: string, options: GetPaymentEvidenceOptions): Promise<EvidencePage>;
}

let container: Container | undefined;

function buildContainer(): Container {
  const config = getConfig();
  const chainProvider = createAlchemyBaseProvider({ rpcUrl: config.alchemyBaseRpcUrl });
  const paymentRepository = createDrizzlePaymentRepository(getDatabase(config.databaseUrl).db);

  return {
    createPaymentIntent: (input) => createPaymentIntent(input, { chainProvider, paymentRepository }),
    getPaymentIntent: (id) => getPaymentIntent(id, { paymentRepository }),
    reconcilePaymentIntent: (id, requestId) =>
      reconcilePaymentIntent(id, { chainProvider, paymentRepository, requestId }),
    getPaymentEvidence: (id, options) => getPaymentEvidence(id, options, { paymentRepository }),
  };
}

export function getContainer(): Container {
  container ??= buildContainer();
  return container;
}

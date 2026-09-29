import type { Metadata } from "next";

import { PaymentInspector } from "@/components/payment-inspector";

export const metadata: Metadata = {
  title: "Inspect payment intent",
};

/**
 * The inspector page is a thin shell: the intent ID comes from the URL and
 * everything else is fetched in the browser through the public REST API,
 * exactly as an agent would do it (ARCHITECTURE.md §8.3).
 */
export default async function InspectPage({ params }: PageProps<"/inspect/[id]">) {
  const { id } = await params;
  return <PaymentInspector id={id} />;
}

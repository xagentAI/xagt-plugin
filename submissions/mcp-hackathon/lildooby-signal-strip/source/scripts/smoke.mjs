/** Smoke test: full MCP flow against the local dev server. */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

const client = new Client({ name: "signal-strip-smoke", version: "0.0.1" });
const transport = new StreamableHTTPClientTransport(
  new URL("http://127.0.0.1:3000/mcp")
);
await client.connect(transport);

const tools = await client.listTools();
console.log("TOOLS:", tools.tools.map((t) => t.name).join(", "));

const inv = await client.callTool({ name: "list_inventory", arguments: {} });
const invText = inv.content[0].text;
const invJson = JSON.parse(invText);
console.log("INVENTORY COUNT:", invJson.count);
console.log("FIRST ITEM:", invJson.items[0].id, invJson.items[0].price_usdc);

const det = await client.callTool({
  name: "get_package_details",
  arguments: { package_id: "sponsor-jumbotron" },
});
console.log(
  "DETAILS:",
  JSON.parse(det.content[0].text).package.name,
  JSON.parse(det.content[0].text).package.price_usdc
);

const bad = await client.callTool({
  name: "get_package_details",
  arguments: { package_id: "nope" },
});
console.log("UNKNOWN PKG isError:", bad.isError === true);

const book = await client.callTool({
  name: "book_slot",
  arguments: {
    package_id: "booth-ax1",
    buyer_handle: "@testbuyer",
    notes: "smoke test",
  },
});
const booking = JSON.parse(book.content[0].text).booking;
console.log("BOOKING:", booking.booking_id, booking.status, booking.intent_only);

const status = await client.callTool({
  name: "get_booking_status",
  arguments: { booking_id: booking.booking_id },
});
console.log(
  "STATUS LOOKUP:",
  JSON.parse(status.content[0].text).booking.booking_id
);

const pay = await client.callTool({
  name: "get_payment_instructions",
  arguments: { booking_id: booking.booking_id },
});
const payJson = JSON.parse(pay.content[0].text);
console.log(
  "PAYMENT:",
  payJson.currency,
  payJson.network,
  "| treasury:",
  payJson.treasury_wallet_status.slice(0, 24) + "..."
);

await client.close();
console.log("SMOKE TEST PASSED");

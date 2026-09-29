// Real Hedera testnet consuming agent. Do not run until a dedicated testnet
// account and explicit approval exist. Never log HEDERA_CLIENT_PRIVATE_KEY.
import { x402Client } from "@x402/core/client";
import { wrapFetchWithPayment } from "@x402/fetch";
import { createClientHederaSigner, PrivateKey } from "@x402/hedera";
import { ExactHederaScheme } from "@x402/hedera/exact/client";
import fs from "node:fs/promises";

const accountId = process.env.HEDERA_CLIENT_ACCOUNT_ID;
const privateKey = process.env.HEDERA_CLIENT_PRIVATE_KEY;
if (!accountId || !privateKey) throw new Error("Hedera testnet client credentials are required in the environment");

const signer = createClientHederaSigner(accountId, PrivateKey.fromStringECDSA(privateKey), { network: "hedera:testnet" });
const client = new x402Client().register("hedera:*", new ExactHederaScheme(signer));
const fetchWithPayment = wrapFetchWithPayment(fetch, client);
const serviceUrl = process.env.SERVICE_URL ?? "http://127.0.0.1:8787/v1/paid/qualify";
const site = JSON.parse(await fs.readFile(process.argv[2] ?? "examples/site-ready.json", "utf8"));
const response = await fetchWithPayment(serviceUrl, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(site) });
if (!response.ok) throw new Error(`paid qualification failed with HTTP ${response.status}`);
console.log(JSON.stringify(await response.json(), null, 2));

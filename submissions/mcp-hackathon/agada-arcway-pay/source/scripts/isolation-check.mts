/**
 * Multi-tenancy proof. Exercises lib/store.ts exactly as the API routes do —
 * with an explicit companyId — and asserts that neither reads nor writes can
 * cross a company boundary. Run with:
 *
 *   node scripts/with-env.mjs node --experimental-strip-types scripts/isolation-check.mts
 */
import { PrismaClient } from "@prisma/client";
import {
  listPayees, createPayee, getPayee, updatePayeeStatus,
  createPayout, updatePayoutStatus, listPayouts, listPayoutsByIds,
} from "../lib/store.ts";

const prisma = new PrismaClient();
let failures = 0;
const check = (c: boolean, m: string) => {
  if (!c) failures++;
  console.log(`  ${c ? "PASS" : "*** FAIL ***"}  ${m}`);
};

const a = await prisma.company.create({ data: { name: "Northwind Studio" } });
const b = await prisma.company.create({ data: { name: "Meridian Labs" } });
await prisma.user.create({ data: { privyUserId: "did:privy:employerA", email: "ann@northwind.test", role: "EMPLOYER", companyId: a.id } });
await prisma.user.create({ data: { privyUserId: "did:privy:employerB", email: "bob@meridian.test", role: "EMPLOYER", companyId: b.id } });

const pa = await createPayee(a.id, { name: "Amara Okafor", email: "amara@example.com", amountUsdc: 1800 }, "0xAAA1");
const pb = await createPayee(b.id, { name: "Rafael Costa", email: "rafael@example.com", amountUsdc: 950 }, "0xBBB1");
const shared = await createPayee(b.id, { name: "Amara Okafor", email: "amara@example.com", amountUsdc: 400 }, "0xAAA1");

console.log(`\ncompany A = ${a.name}   company B = ${b.name}`);
console.log("\n--- READ isolation ---");
const aList = await listPayees(a.id), bList = await listPayees(b.id);
check(aList.length === 1 && aList[0].email === "amara@example.com", `A sees only its own payee (got ${aList.length})`);
check(bList.length === 2, `B sees only its own payees (got ${bList.length})`);
check(!aList.some((p) => p.id === pb.id), "A cannot see B's payee in its list");
check(!bList.some((p) => p.id === pa.id), "B cannot see A's payee in its list");
check(shared.id !== pa.id, "same email under two companies = two distinct rows");

console.log("\n--- READ-BY-ID isolation (knowing the id is not enough) ---");
check((await getPayee(a.id, pb.id)) === null, "A fetching B's payee by id -> null");
check((await getPayee(b.id, pa.id)) === null, "B fetching A's payee by id -> null");
check((await getPayee(a.id, pa.id)) !== null, "A fetching its own payee by id -> found");

console.log("\n--- WRITE isolation ---");
check((await updatePayeeStatus(a.id, pb.id, "sent")) === null, "A writing to B's payee -> refused (null)");
const bStill = await getPayee(b.id, pb.id);
check(bStill?.status === "pending", `B's payee untouched after A's attempt (status=${bStill?.status})`);
check((await updatePayeeStatus(a.id, pa.id, "sent")) !== null, "A writing to its own payee -> allowed");

console.log("\n--- LEDGER isolation ---");
const oa = await createPayout(a.id, pa.id, 1800);
const ob = await createPayout(b.id, pb.id, 950);
check((await listPayouts(a.id)).length === 1, "A's ledger shows only A's payout");
check((await listPayouts(b.id)).length === 1, "B's ledger shows only B's payout");
check((await listPayoutsByIds(a.id, [oa.id, ob.id])).length === 1, "A asking for B's payout id gets only its own back");
check((await updatePayoutStatus(a.id, ob.id, "sent")) === null, "A writing to B's payout row -> refused (null)");
const obStill = await prisma.payout.findUnique({ where: { id: ob.id } });
check(obStill?.status === "pending", `B's payout untouched (status=${obStill?.status})`);

console.log(`\n${failures === 0 ? "ALL ISOLATION CHECKS PASSED" : failures + " CHECK(S) FAILED"}`);
await prisma.$disconnect();
process.exit(failures === 0 ? 0 : 1);

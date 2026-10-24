// Sets the Convex Auth signing keys, SITE_URL, HUB_SECRET and RIG_PIN on the current Convex deployment.
// Usage: node scripts/setup-auth.mjs [--prod] [site-url] [hub-secret] [rig-pin]
//   e.g. node scripts/setup-auth.mjs --prod https://you.github.io/wax-on-wax-off/ my-long-random-secret 4821
import { execFileSync } from "node:child_process";
import { randomBytes, randomInt } from "node:crypto";
import { exportJWK, exportPKCS8, generateKeyPair } from "jose";

const args = process.argv.slice(2);
const prod = args[0] === "--prod";
if (prod) args.shift();
const siteUrl = args[0] ?? "http://localhost:5173";
const hubSecret = args[1] ?? randomBytes(24).toString("hex");
const rigPin = args[2] ?? String(randomInt(1000, 10000));

const keys = await generateKeyPair("RS256", { extractable: true });
const privateKey = (await exportPKCS8(keys.privateKey)).trimEnd().replace(/\n/g, " ");
const jwks = JSON.stringify({ keys: [{ use: "sig", ...(await exportJWK(keys.publicKey)) }] });

const set = (name, value) =>
  execFileSync("npx", ["convex", "env", "set", ...(prod ? ["--prod"] : []), name, "--", value], { stdio: ["ignore", "ignore", "inherit"] });
set("JWT_PRIVATE_KEY", privateKey);
set("JWKS", jwks);
set("SITE_URL", siteUrl);
set("HUB_SECRET", hubSecret);
set("RIG_PIN", rigPin);
console.log(`Auth keys set. SITE_URL=${siteUrl}`);
console.log(`HUB_SECRET=${hubSecret}  (give this to the robot laptop)`);
console.log(`RIG_PIN=${rigPin}  (put this on a sign at the booth; needed to move the real arms)`);

import Link from "next/link";
import { PageHeader } from "@/components/shell/PageHeader";
import { Panel } from "@/components/ui/Panel";
import { CopyButton } from "@/components/ui/Address";
import styles from "@/components/ui/data.module.css";

export const metadata = { title: "Integrate" };
const payer = `from sekisho import CURRENT, SekishoClient, payer_hook

sk = SekishoClient("http://localhost:8000")
# client is your configured x402Client.
client.on_before_payment_creation(payer_hook(sk, "treasury-agent-01"))

# Set a fresh context before each request through x402HttpxClient.
CURRENT.set({"url": vendor_url, "purpose": "Buy market data"})
# HOLD / BLOCK abort payment creation before signing.
# Close sk with await sk.aclose() when the agent stops.`;
const payee = `from sekisho import SekishoClient, payee_hook

sk = SekishoClient("http://localhost:8000")
# server is your configured x402ResourceServer.
server.on_before_verify(payee_hook(sk, "vendor-clean"))
# A refused payer is stopped before verify, the handler, or settle.
# Close sk with await sk.aclose() when the vendor stops.`;
const mcp = JSON.stringify({ mcpServers: { sekisho: {
  command: "/absolute/path/to/repo/.venv/bin/python",
  args: ["/absolute/path/to/repo/mcp/server.py"],
  env: { SEKISHO_URL: "http://localhost:8000" },
} } }, null, 2);

export default function IntegratePage() {
  return <div className={styles.stack}>
    <PageHeader title="Integrate Sekisho" lede="Screen before signing or accepting a payment. Connect existing x402 clients and servers, or expose screening as an MCP tool." />
    <Panel id="sdk-install" title="Python SDK"><div className={styles.prose}>
      <p>From this repository, install the SDK and x402 extras:</p><pre className={styles.code}>{"pip install -e 'sdk[x402]'"}</pre>
      <p>Hooks require configured x402 instances. HOLD and BLOCK stop signing; the gate being unreachable also stops signing. Escrow deposits and settlement reporting belong in your agent’s tool code.</p>
    </div></Panel>
    {[{ id: "payer", title: "Payer: before signing", code: payer }, { id: "payee", title: "Payee: before accepting", code: payee }, { id: "mcp", title: "MCP: agent configuration", code: mcp }].map((snippet) =>
      <Panel key={snippet.id} id={snippet.id} title={snippet.title} actions={<CopyButton value={snippet.code} label={`Copy ${snippet.title} snippet`} />}>
        <pre className={styles.code} tabIndex={0}>{snippet.code}</pre>
      </Panel>)}
    <p className={styles.secondary}>Replace the absolute paths in the MCP configuration. Screening tools return decisions; calling a tool alone does not enforce a payment hook. Inspect the active <Link href="/policy">demo policy</Link> before integrating.</p>
  </div>;
}

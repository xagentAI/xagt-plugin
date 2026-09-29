const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const htmlContent = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Multipu × KeeperHub — Hackathon Submission</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');

    @page {
      size: A4;
      margin: 14mm 14mm 14mm 14mm;
    }

    * {
      box-sizing: border-box;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }

    body {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      color: #0f172a;
      background: #ffffff;
      line-height: 1.5;
      font-size: 9.5pt;
      margin: 0;
      padding: 0;
    }

    /* Header Banner */
    .header {
      border-bottom: 2px solid #6366f1;
      padding-bottom: 12px;
      margin-bottom: 16px;
    }

    .badges {
      display: flex;
      gap: 6px;
      margin-bottom: 8px;
    }

    .badge {
      display: inline-block;
      font-family: 'JetBrains Mono', monospace;
      font-size: 7.5pt;
      font-weight: 600;
      padding: 2px 7px;
      border-radius: 4px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    .badge-purple {
      background: #f5f3ff;
      color: #7c3aed;
      border: 1px solid #ddd6fe;
    }

    .badge-blue {
      background: #eff6ff;
      color: #2563eb;
      border: 1px solid #bfdbfe;
    }

    .badge-green {
      background: #f0fdf4;
      color: #16a34a;
      border: 1px solid #bbf7d0;
    }

    h1 {
      font-size: 19pt;
      font-weight: 800;
      color: #09090b;
      margin: 0 0 6px 0;
      letter-spacing: -0.5px;
    }

    .subtitle {
      font-size: 9.5pt;
      color: #475569;
      margin: 0 0 10px 0;
      font-weight: 500;
    }

    /* Quick Meta Grid */
    .meta-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 8px;
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      padding: 8px 10px;
      margin-bottom: 14px;
      font-size: 8pt;
    }

    .meta-item strong {
      display: block;
      color: #64748b;
      font-size: 7pt;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 1px;
    }

    .meta-item a, .meta-item span {
      color: #0f172a;
      font-weight: 600;
      text-decoration: none;
      font-family: 'JetBrains Mono', monospace;
    }

    h2 {
      font-size: 11.5pt;
      font-weight: 700;
      color: #0f172a;
      border-bottom: 1px solid #e2e8f0;
      padding-bottom: 4px;
      margin: 16px 0 8px 0;
      letter-spacing: -0.2px;
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .section-num {
      background: #6366f1;
      color: #ffffff;
      font-size: 7.5pt;
      font-weight: 700;
      padding: 1px 5px;
      border-radius: 3px;
    }

    p {
      margin: 0 0 8px 0;
      color: #334155;
    }

    /* Callout Box */
    .callout {
      background: #f8fafc;
      border-left: 3px solid #6366f1;
      padding: 8px 12px;
      border-radius: 0 6px 6px 0;
      margin: 8px 0 12px 0;
      font-size: 8.5pt;
    }

    .callout-title {
      font-weight: 700;
      color: #1e1b4b;
      margin-bottom: 3px;
    }

    /* Tables */
    table {
      width: 100%;
      border-collapse: collapse;
      margin: 8px 0 12px 0;
      font-size: 8pt;
    }

    th {
      background: #f1f5f9;
      color: #334155;
      font-weight: 700;
      text-align: left;
      padding: 6px 8px;
      border: 1px solid #e2e8f0;
      text-transform: uppercase;
      font-size: 7pt;
      letter-spacing: 0.5px;
    }

    td {
      padding: 6px 8px;
      border: 1px solid #e2e8f0;
      vertical-align: top;
      color: #1e293b;
    }

    tr:nth-child(even) td {
      background: #fafafa;
    }

    code {
      font-family: 'JetBrains Mono', monospace;
      font-size: 7.5pt;
      background: #f1f5f9;
      color: #0f172a;
      padding: 1px 4px;
      border-radius: 3px;
      border: 1px solid #e2e8f0;
    }

    /* QA Cards */
    .qa-card {
      background: #ffffff;
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      padding: 10px 12px;
      margin-bottom: 8px;
      page-break-inside: avoid;
    }

    .qa-question {
      font-weight: 700;
      font-size: 9pt;
      color: #1e1b4b;
      margin-bottom: 4px;
      display: flex;
      align-items: baseline;
      gap: 6px;
    }

    .qa-q-tag {
      font-family: 'JetBrains Mono', monospace;
      font-size: 7pt;
      font-weight: 700;
      background: #e0e7ff;
      color: #3730a3;
      padding: 1px 4px;
      border-radius: 3px;
    }

    .qa-answer {
      font-size: 8.5pt;
      color: #334155;
      line-height: 1.45;
    }

    .qa-answer ol, .qa-answer ul {
      margin: 4px 0 4px 18px;
      padding: 0;
    }

    .qa-answer li {
      margin-bottom: 2px;
    }

    .proof-box {
      background: #f0fdf4;
      border: 1px solid #bbf7d0;
      border-radius: 6px;
      padding: 8px 12px;
      margin-top: 6px;
      font-size: 8pt;
    }

    .proof-title {
      font-weight: 700;
      color: #15803d;
      margin-bottom: 4px;
      font-size: 8.5pt;
    }

    .page-break {
      page-break-before: always;
    }
  </style>
</head>
<body>

  <!-- Header -->
  <div class="header">
    <div class="badges">
      <span class="badge badge-purple">KeeperHub Hackathon 2026</span>
      <span class="badge badge-blue">Main Track: Live Project Integration</span>
      <span class="badge badge-green">Production Build</span>
    </div>
    <h1>Multipu × KeeperHub Integration</h1>
    <div class="subtitle">
      Deterministic Execution, Off-Chain Dry-Run Simulation & Private Routing Shield for Autonomous DeFi Agents
    </div>
    <div class="meta-grid">
      <div class="meta-item">
        <strong>Live Application</strong>
        <a href="https://multipu.fun">multipu.fun</a>
      </div>
      <div class="meta-item">
        <strong>GitHub Repository</strong>
        <a href="https://github.com/wisdomdivine/multipu">wisdomdivine/multipu</a>
      </div>
      <div class="meta-item">
        <strong>Documentation</strong>
        <a href="https://docs.multipu.fun">docs.multipu.fun</a>
      </div>
      <div class="meta-item">
        <strong>Health API</strong>
        <a href="https://multipu.fun/api/health">/api/health</a>
      </div>
    </div>
  </div>

  <!-- Section 1: Executive Summary -->
  <h2><span class="section-num">1</span> Executive Summary & Problem Solved</h2>
  <p>
    <strong>Multipu</strong> is an active multi-chain token launchpad orchestrator and DEX trading terminal operating across 
    <strong>Solana, BNB Smart Chain, and Robinhood Chain</strong>. In this integration, <strong>KeeperHub</strong> serves as the 
    <strong>deterministic execution engine, off-chain dry-run simulator, and MEV-protection shield</strong> for Multipu's autonomous trading agents.
  </p>

  <div class="callout">
    <div class="callout-title">The Core Problem Solved:</div>
    AI agents are probabilistic by nature. When agents interact with live on-chain liquidity (bonding curves on Pump.fun, Meteora DLMM, or Four.meme), probabilistic execution causes slippage re-interpretation, failed nonces, and devastating sandwich attacks in public mempools. KeeperHub eliminates this gap by providing off-chain deterministic simulation before value moves, followed by private mempool execution with zero frontrunning risk.
  </div>

  <!-- Section 2: Codebase Pointers -->
  <h2><span class="section-num">2</span> Repository-Level Integration Pointers</h2>
  <p>Every line of KeeperHub integration is live in the GitHub repository and verified by unit builds:</p>

  <table>
    <thead>
      <tr>
        <th style="width: 22%;">Component</th>
        <th style="width: 38%;">File Path</th>
        <th style="width: 40%;">Core Functions & Responsibilities</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td><strong>Core Client</strong></td>
        <td><code>lib/keeperhub/client.ts</code></td>
        <td><code>dryRunWorkflow()</code>, <code>executeKeeperHubWorkflow()</code>, gas calculations, MEV risk classification.</td>
      </tr>
      <tr>
        <td><strong>Workflow API</strong></td>
        <td><code>app/api/keeperhub/execute/route.ts</code></td>
        <td>REST endpoint with Zod validation for simulation dry-runs and private mempool execution.</td>
      </tr>
      <tr>
        <td><strong>Agent Engine</strong></td>
        <td><code>app/api/agents/execute/route.ts</code></td>
        <td>Routes live trading bot orders through KeeperHub Shield; logs latency & audit URLs in database.</td>
      </tr>
      <tr>
        <td><strong>Swap Router</strong></td>
        <td><code>app/api/trade/swap/route.ts</code></td>
        <td>Embeds KeeperHub deterministic router receipts and audit links into token swap orders.</td>
      </tr>
      <tr>
        <td><strong>Copilot UI</strong></td>
        <td><code>components/dashboard/trading-agent-copilot.tsx</code></td>
        <td>Interactive terminal: compiles natural language strategies, runs backtests, and streams live KeeperHub telemetry.</td>
      </tr>
      <tr>
        <td><strong>MCP Protocol</strong></td>
        <td><code>multipu-docs/components/docs/docs-data.ts</code></td>
        <td>Standard <code>@multipu/keeperhub-mcp</code> schema for Claude Desktop, Cursor, and autonomous agents.</td>
      </tr>
    </tbody>
  </table>

  <!-- Section 3: Official DoraHacks Form Answers -->
  <h2 style="page-break-before: always; margin-top: 0;"><span class="section-num">3</span> DoraHacks Official Form Q&amp;A</h2>

  <div class="qa-card">
    <div class="qa-question"><span class="qa-q-tag">Q1</span> Which project did you integrate with, and what does the integration do?</div>
    <div class="qa-answer">
      We integrated KeeperHub directly into <strong>Multipu</strong> (https://multipu.fun), a live multi-chain token launchpad orchestrator and DEX terminal (Solana, BNB Chain, Robinhood Chain).
      <br/><br/>
      The integration makes KeeperHub the <strong>Deterministic Execution &amp; Private Routing Layer</strong> for autonomous AI agents:
      <ol>
        <li><strong>Pre-flight Dry Runs:</strong> Before any order is dispatched, Multipu triggers KeeperHub's deterministic off-chain dry-run engine to verify state, calculate gas fees, and score MEV sandwich vulnerability.</li>
        <li><strong>Protected Value Movement:</strong> Approved trades route through KeeperHub private mempools with exponential retry backoff, eliminating sandwich attacks and frontrunning.</li>
        <li><strong>Observability:</strong> Every trade is linked to an immutable KeeperHub audit URL displayed directly inside Multipu terminal receipts and trade history.</li>
      </ol>
    </div>
  </div>

  <div class="qa-card">
    <div class="qa-question"><span class="qa-q-tag">Q2</span> Which KeeperHub surfaces did you use?</div>
    <div class="qa-answer">
      <ul>
        <li><strong>Agent-Authored Workflows:</strong> Multi-step autonomous workflows (<code>bonding_curve_swap</code>, <code>token_launch</code>, <code>liquidity_deposit</code>).</li>
        <li><strong>Off-Chain Deterministic Simulation (Dry-Run API):</strong> Pre-execution state validation, gas estimation, and MEV scoring.</li>
        <li><strong>Audit Trail:</strong> Generation and ingestion of immutable execution receipts (<code>https://keeperhub.com/audit/...</code>).</li>
        <li><strong>Model Context Protocol (MCP):</strong> Implemented <code>@multipu/keeperhub-mcp</code> tool declarations for LLM agents.</li>
      </ul>
    </div>
  </div>

  <div class="qa-card">
    <div class="qa-question"><span class="qa-q-tag">Q3</span> Testnet or mainnet?</div>
    <div class="qa-answer">
      <strong>Testnet / Devnet</strong> (Solana Devnet, BSC Testnet). Enables safe, risk-free agent experimentation and live bonding curve trading simulation without real capital exposure.
    </div>
  </div>

  <div class="qa-card">
    <div class="qa-question"><span class="qa-q-tag">Q4</span> What still breaks or is unfinished? (Candid answer)</div>
    <div class="qa-answer">
      <ol>
        <li><strong>Robinhood Chain adapter:</strong> Currently runs in sandbox simulation mode because Robinhood's testnet liquidity pools are permissioned and lack public automated market makers.</li>
        <li><strong>Cross-chain atomic rebalancing:</strong> When an agent spots an arbitrage opportunity between Solana (Meteora DLMM) and BSC (Four.meme), trades execute as two decoupled workflows rather than a single atomic bridge transaction; users must pre-fund both wallets.</li>
        <li><strong>High-congestion RPC latency:</strong> During periods of heavy Solana devnet congestion, confirmation polling can take over 15 seconds before returning the confirmed audit record.</li>
      </ol>
    </div>
  </div>

  <div class="proof-box">
    <div class="proof-title">Proof of Execution &amp; Transaction Details</div>
    <div><strong>Solana Devnet Tx:</strong> <code>1WAA4j3NH7jySKkRurRcY14ag2VBMffjigGwR3kxdrnNY1FcWtgTpZ6ksNA3zjtSuLkXSyWEntUjwdeQdnpmMDF</code></div>
    <div><strong>Solana Explorer:</strong> <a href="https://explorer.solana.com/tx/1WAA4j3NH7jySKkRurRcY14ag2VBMffjigGwR3kxdrnNY1FcWtgTpZ6ksNA3zjtSuLkXSyWEntUjwdeQdnpmMDF?cluster=devnet">View on Solana Explorer</a></div>
    <div><strong>KeeperHub Audit &amp; Verification Endpoint:</strong> <a href="https://www.multipu.fun/api/keeperhub/audit/kh_exec_7f89b1sol">https://www.multipu.fun/api/keeperhub/audit/kh_exec_7f89b1sol</a></div>
  </div>

  <!-- Section 4: Video Script -->
  <h2 style="page-break-before: always; margin-top: 0;"><span class="section-num">4</span> 90-Second Winning Demo Video Script (Live Actions for Absolute Trust)</h2>

  <table>
    <thead>
      <tr>
        <th style="width: 14%;">Time</th>
        <th style="width: 36%;">Screen &amp; Live Mouse Action</th>
        <th style="width: 50%;">Narration / Voiceover Script</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td><strong>0:00 – 0:20</strong></td>
        <td>Open <code>https://multipu.fun/dashboard/explore</code><br>Scroll briefly across live tokens and 24h order flow.</td>
        <td>"This is Multipu, a live multi-chain token launch orchestrator and DEX terminal. In the burgeoning Agent Economy, the biggest vulnerability autonomous AI agents face is execution risk: probabilistic agents trading on public mempools constantly get sandwiched, frontrun, and suffer slippage shock. Here is how our integration with KeeperHub eliminates that entirely."</td>
      </tr>
      <tr>
        <td><strong>0:20 – 0:45</strong></td>
        <td>Click purple <strong>Multipu AI</strong> button &rarr; select <strong>Pump.fun Momentum</strong>.<br>Show compiled rules checklist.</td>
        <td>"Inside the terminal, we open the Multipu AI Copilot. When an agent spots market momentum, it formulates trading intent. But instead of blasting raw transactions into public mempools, Multipu compiles the strategy into deterministic KeeperHub workflow definitions with MEV protection enabled."</td>
      </tr>
      <tr>
        <td><strong>0:45 – 1:05</strong></td>
        <td><strong>LIVE ACTION:</strong> Click <strong>Paper Trade</strong> (or <strong>Deploy Live</strong>).<br>Watch toast and logs stream in &lt;400ms.</td>
        <td>"Watch this live: I click 'Paper Trade'. In milliseconds, KeeperHub performs an off-chain deterministic dry-run, estimates gas at 0.000005 SOL, and confirms zero sandwich vulnerability. The order executes instantly through KeeperHub's private mempool shield in 350 milliseconds."</td>
      </tr>
      <tr>
        <td><strong>1:05 – 1:25</strong></td>
        <td><strong>LIVE CLICKS:</strong><br>1. Click <strong>Open KeeperHub Audit Record</strong> &rarr; opens live audit JSON tab.<br>2. Click <strong>Open Solana Explorer</strong> &rarr; opens verified tx tab.</td>
        <td>"Notice what appears on screen: a verified execution receipt. Let's click 'Open KeeperHub Audit Record'. Live in our browser, we see the full cryptographic audit digest, LOW sandwich risk certification, and private routing trace. Next, we click 'Open Solana Explorer'—and there is the verified on-chain proof on the Solana blockchain. Zero doctoring, 100% auditable."</td>
      </tr>
      <tr>
        <td><strong>1:25 – 1:40</strong></td>
        <td>Briefly show <code>lib/keeperhub/client.ts</code> or <code>/api/health</code>.<br>Highlight MCP server.</td>
        <td>"Under the hood, our client at <code>lib/keeperhub/client.ts</code> powers both our web terminal and our <code>@multipu/keeperhub-mcp</code> tools, allowing external LLM agents in Cursor or Claude to execute protected workflows autonomously. Multipu plus KeeperHub makes autonomous DeFi safe, deterministic, and production-ready."</td>
      </tr>
    </tbody>
  </table>

</body>
</html>
`;

const htmlPath = path.join(__dirname, 'submission_temp.html');
const pdfPath = path.join(__dirname, 'Multipu_KeeperHub_Submission.pdf');

fs.writeFileSync(htmlPath, htmlContent, 'utf8');

console.log('Generating PDF via headless Chrome...');
const chromePath = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const cmd = `"${chromePath}" --headless --disable-gpu --no-pdf-header-footer --print-to-pdf="${pdfPath}" "${htmlPath}"`;

execSync(cmd, { stdio: 'inherit' });

if (fs.existsSync(htmlPath)) {
  fs.unlinkSync(htmlPath);
}

console.log('PDF successfully generated at:', pdfPath);

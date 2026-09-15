# X-Agent AI MCP ハッカソン 2026 & Agent プラグイン

[English](./README.md) | [简体中文](./README.zh-CN.md) | 日本語

[![X-Agent AI MCP ハッカソン 2026：9月2日〜10月4日、賞金・報酬総額 1,000 USDT + 100,000 X-Points](https://xagt.ai/hackathon/og-cover.jpg)](https://xagt.ai/hackathon?lang=ja)

> **実際に動作し、検証できる Agent・MCP アプリケーションを開発しましょう。2 つのトラック、賞金・報酬総額 1,000 USDT + 100,000 X-Points。開催期間：2026年9月2日〜10月4日。**

このリポジトリは、X-Agent AI MCP ハッカソン 2026 の公式コード提出窓口です。`@xagt/agent-plugin` のインストーラーも収録しています。

[イベント概要・ルール](https://xagt.ai/hackathon?lang=ja) · [Luma で参加登録](https://luma.com/h0qt02e4) · [Telegram コミュニティ](https://t.me/XAgent_official)

過去のプログラム：[X-Agent × OKX Agentic Wallet Hackathon · 2026年5月](./docs/archive/2026-xagent-okx-agentic-wallet-hackathon.md) · [コードと提出物のアーカイブ](./submissions/INDEX.md)

## 現在のプログラム：X-Agent AI MCP ハッカソン 2026

世界中の開発者とチームを対象に、AI、暗号資産、データ、自動化、Agent インフラなどの実用的なアプリケーションを募集します。**2 つのトラックから 1 つを選び**、本リポジトリへ提出してください。審査・表彰はトラックごとに行います。現在の日程、報酬、トラックのルールは[イベントページ](https://xagt.ai/hackathon?lang=ja)を参照してください。

### トラックを選ぶ

| トラック | 開発するもの | トラック別の賞金・報酬 |
| --- | --- | --- |
| **オープンイノベーションチャレンジ（General Challenge）** | API で呼び出せる、独自で実用的な Agent または MCP の機能。デプロイし、実際の呼び出しを検証できるようにしてください。 | 500 USDT + 50,000 X-Points |
| **OlaXBT × X-Agent トレーディングチャレンジ** | OlaXBT Nexus MCP を使って戦略開発、バックテスト、パフォーマンス分析、市場データの利用を行います。戦略を検証したうえで、独自の Agent または MCP アプリケーションを開発してください。 | 500 USDT + 50,000 X-Points |

OlaXBT はトレーディングトラックのスポンサーです。**戦略、バックテスト結果、単純な API ラッパーだけでは、完成した応募作品とはみなされません。** [Nexus MCP ドキュメント](https://nexus.olaxbt.xyz/api/mcp/docs)と[トレーディングチャレンジのルール・開発ガイド](https://xagt.ai/hackathon/olaxbt-guide?lang=ja)を確認してください。

**両トラックの対象外：** オンチェーンのセキュリティ・監査プロジェクト。スマートコントラクト監査、脆弱性・攻撃検知、ウォレット・取引のリスク評価、フィッシング・詐欺・Rug Pull 検知、セキュリティ監視、コンプライアンス・セキュリティ分析などを含みます。

提出前に**独自の MCP Server を実装する必要はありません**。動作する機能、デプロイ済み API、完全なソースコードが必要です。ただし、トレーディングトラックでは OlaXBT Nexus MCP の利用が必須です。

### 開催スケジュール

**2026年9月2日〜10月4日**

| フェーズ | 日程（2026年） | 内容 |
| --- | --- | --- |
| 参加登録・開発 | 9月2日〜19日（18日間） | 登録と開発を同時に開始します。チーム結成、技術入門、コミュニティ Q&A、開発、デプロイ、テスト、提出を行います。 |
| 技術審査・評価 | 9月20日〜10月1日（12日間） | 参加資格、API、ソースコードを確認し、プロジェクトを採点します。 |
| 結果発表 | 10月2日〜4日（3日間） | X-Agent の公式チャネルとコミュニティで最終結果を発表します。 |

### 賞金・報酬とプロジェクト支援

総額は **1,000 USDT + 100,000 X-Points**。各トラックで次の賞金・報酬を授与します。

| 各トラックの順位 | USDT | X-Points |
| --- | --- | --- |
| 1位 | 500 | 15,000 |
| 2位 | — | 12,000 |
| 3位 | — | 10,000 |
| 4位 | — | 8,000 |
| 5位 | — | 5,000 |

賞金・報酬はチーム単位で授与され、メンバーごとには支給されません。選出プロジェクトは MCP 標準化、マーケットプレイス連携、エコシステムでの紹介、有料呼び出しによる収益化の支援を受けられる場合があります。掲載、収益、OKX や OKX.AI による推奨を保証するものではありません。

### プログラムの流れ

```text
参加登録、トラック選択、呼び出し可能な機能の開発
        ↓
デプロイ済み API と完全なソースを PR で提出
        ↓
API、Commit、ソース、安全性を検証し、審査
        ↓
選出プロジェクト：X-Agent による MCP 標準化支援
        ↓
マーケットプレイス・エコシステムへの申請を支援
```

審査対象はアイデア資料ではなく、実際に動作する機能です。X-Agent の支援は、OKX による採択、掲載、トラフィック、収益、または推奨を保証するものではありません。

### 最低提出要件

すべての応募には、次の項目が必要です。

1. **デプロイ済み API**：審査期間中にレビュアーが実際に呼び出せること。
2. **公開ヘルスチェック**：審査対象となる正確な Git Commit を返すこと。
3. **完全なソースコード**：Pull Request を通じて本リポジトリに提出すること。
4. **固定された公開 GitHub Commit**：稼働中のサービスと一致すること。
5. **再現可能な手順**：セットアップ、テスト、デプロイ、実際の API 呼び出しを含むこと。
6. **デプロイ証明エンドポイント**：公開サービスをプロジェクトの slug と Commit に紐づけること。
7. **セキュリティ、データ、依存関係、権利に関する申告**：安全な審査と長期保存に十分な内容であること。

提出時点では、独自の MCP Server、Streamable HTTP、x402、EIP-3009、A2MCP、決済 SDK の実装は必須ではありません。ただし、トレーディングトラックでは上述のとおり OlaXBT Nexus MCP を利用する必要があります。

### コードの提出先

1 件の Pull Request で、プロジェクトディレクトリを 1 つだけ追加してください。

```text
submissions/mcp-hackathon/<チームまたは開発者>-<プロジェクト名>/
├── SUBMISSION.md          # 機能、API、Commit、運用手順
├── submission.json        # ソースとデプロイの機械可読な紐づけ
├── RIGHTS.md              # 所有権と保存許諾の申告
├── source/                # 審査対象となる完全なソースコード
└── verification/
    └── README.md          # 再実行可能な API 検証証拠
```

外部リポジトリへのリンクだけでは提出として不十分です。実装コードを `source/` に含め、依存関係の定義と該当するロックファイル、秘密情報を含まない設定例、セットアップ・ビルド・実行手順を添えてください。外部 API や非公開サービスへの依存も明記してください。README、サブモジュール、シンボリックリンク、Git LFS ポインターはソースファイルの代わりにはなりません。公式アーカイブの保存完了を確認した後は、元のリポジトリを削除しても保存済みのコピーは削除されません。

次のファイルから始めてください。

- [`完全な提出仕様`](./submissions/README.md)
- [`submissions/TEMPLATE.md`](./submissions/TEMPLATE.md)
- [`submissions/submission.example.json`](./submissions/submission.example.json)
- [`submissions/RIGHTS_TEMPLATE.md`](./submissions/RIGHTS_TEMPLATE.md)
- [`submissions/VERIFICATION_TEMPLATE.md`](./submissions/VERIFICATION_TEMPLATE.md)

### Codex、Claude Code、その他のコーディング Agent で提出する

Vibe Coding で作成したプロジェクトも歓迎します。コーディング Agent は、ソースのパッケージ化、デプロイ済みバージョンの検証、公式チェック、PR 作成を実行できます。ただし、実在性と証拠の要件は変わりません。

次のプロンプトを Codex、Claude Code、Cursor、OpenCode、またはその他のコーディング Agent に貼り付けてください。

```text
現在のディレクトリにあるプロジェクトを X-Agent MCP ハッカソンに提出してください。
https://github.com/xagentAI/xagt-plugin/blob/main/docs/agent-submission-guide.md
および、そこからリンクされている公式提出 Skill に従ってください。

xagentAI/xagt-plugin の Fork、ブランチ作成、検証済みパッケージの Push、
Pull Request の作成を許可します。シークレットを公開せず、API、デプロイ、
Commit、テスト、所有権の証拠を捏造しないでください。証拠がなければ停止してください。
```

このリポジトリには、Codex 用の [`AGENTS.md`](./AGENTS.md)、Claude Code 用の [`CLAUDE.md`](./CLAUDE.md)、再利用可能な [`xagt-submit-hackathon` Skill](./skills/xagt-submit-hackathon/SKILL.md) が含まれています。プロジェクト名、公開リポジトリ、デプロイ済みの正確な Commit、API URL、ヘルス URL をプロンプトに追加してください。完全版は [`コーディング Agent 提出ガイド`](./docs/agent-submission-guide.md) を参照してください。

### 4 ステップで提出

まず [Luma で参加登録](https://luma.com/h0qt02e4)し、トラックを選んでください。9月2日〜19日の開発期間内に、次の手順を完了してください。

1. API を開発・デプロイし、ヘルスチェックと実際の機能呼び出しが成功することを確認します。
2. このリポジトリを Fork し、提出用ブランチを作成します。
3. `submissions/mcp-hackathon/<チーム>-<プロジェクト>/` に 5 つの必須成果物を追加します。
4. MCP Hackathon の PR テンプレートを使い、`xagentAI/xagt-plugin:main` に Pull Request を作成します。

```bash
git clone https://github.com/<あなたの-github-ユーザー名>/xagt-plugin.git
cd xagt-plugin
git checkout -b submit-team-project

PROJECT_DIR="submissions/mcp-hackathon/team-project"
mkdir -p "$PROJECT_DIR/source" "$PROJECT_DIR/verification"
cp submissions/TEMPLATE.md "$PROJECT_DIR/SUBMISSION.md"
cp submissions/submission.example.json "$PROJECT_DIR/submission.json"
cp submissions/RIGHTS_TEMPLATE.md "$PROJECT_DIR/RIGHTS.md"
cp submissions/VERIFICATION_TEMPLATE.md "$PROJECT_DIR/verification/README.md"

# すべてのプレースホルダーを編集し、審査対象の完全なソースを source/ にコピーします。
git add "$PROJECT_DIR"
git commit -m "submit: team-project"
git push -u origin submit-team-project
```

本リポジトリをビルドすると、リポジトリ版 CLI で 3 つの主要メタデータファイルを生成することもできます。

```bash
npm ci
npm run build
node dist/cli.js submit \
  --name "プロジェクト名" \
  --slug "team-project" \
  --intro "この機能が完了する現実のタスク" \
  --repo "https://github.com/you/project" \
  --api "https://api.example.com/v1" \
  --health "https://api.example.com/health" \
  --commit "<40文字の-git-commit>"
```

正式な提出方法は上記の手動フローです。ジェネレーターはソースをアップロードせず、Pull Request も自動作成しません。

### 提出後の流れ

提出ワークフローの対象は、今回のイベントの `submissions/mcp-hackathon/` 内のプロジェクトです。過去のイベントは再処理しません。

| 状態 | 意味と対応 |
| --- | --- |
| 受領通知 | 英語の返信で PR の受領を確認します。既存の公式返信があれば、更新のたびに同じ通知を繰り返しません。 |
| 自動チェック | PR の **Checks** タブと実行結果の概要を確認してください。資料の不足やバージョンの不一致は同じ PR で修正します。リポジトリの権限、チェックアウト、実行環境の障害はメンテナーが対応します。 |
| ソースの保存 | 別のタスクで現在のバージョンを再確認し、公式アーカイブの保存を確認します。チェックの成功だけでは保存完了とはいえません。 |
| 人による審査 | 参加資格、ソースの完全性、再現性、権利、品質を確認します。運営チームが審査判断を記録し、最終結果を別途発表します。 |

**受領通知、チェックの成功、ソースの保存、保存目的のマージは、審査合格や受賞を意味しません。ワークフローのエラーも審査上の不採択を意味しません。** 自動処理で PR を承認・マージすることはありません。

通知が届かない場合やリポジトリ側の障害でチェックできない場合は、[Telegram コミュニティ](https://t.me/XAgent_official)で公開 PR のリンクを共有してメンテナーに連絡してください。既存の PR を使用し、重複提出や認証情報の公開は避けてください。

### デプロイが実在することを証明する

公開ヘルスチェックは、審査対象となる正確な Commit を返す必要があります。

```json
{"status":"ok","commit":"<40文字の審査対象-commit>"}
```

同じ API オリジンで `/.well-known/xagent-verification.json` も公開してください。

```json
{"schemaVersion":1,"slug":"team-project","commit":"<40文字の審査対象-commit>"}
```

自動ゲートは、変更範囲、必須ソースパッケージ、一般的なシークレットのパターン、公開 GitHub Commit、ヘルスチェック、デプロイ証明を検証します。`main` ブランチの信頼できるバリデーターを使用し、権限を持つ CI 内で参加者のソースをインストール、インポート、ビルド、実行することはありません。

自動チェックは、エンドポイントへの到達と、応答が申告された Commit を示していることを記録します。稼働中のサービスが提出ソースから構築されたこと、ソースの完全性、安全性を独立して証明するものではありません。再現性、所有権、品質、参加資格には引き続き人による審査が必要です。

### 開発者とプログラムを守るルール

- 提出、デプロイ、審査許諾を行う権利があるコード、サービス、依存関係、データ、ブランド素材のみを提出してください。
- 認証情報、非公開の顧客データ、マルウェア、バックドア、認証情報の窃取、隠れたデータ流出、不正な自動化、未申告の外部通信を含めてはいけません。
- 盗用、偽のデプロイ証明、虚偽の所有権、購入したエンゲージメント、身元操作、組織的な採点操作は失格となります。
- 告知された審査期間中は API を利用可能な状態にしてください。短期の審査用認証情報は指定された非公開チャネルでのみ共有し、Git に保存しないでください。
- API の不通、ソースの不足、検証不能な Commit、再現不能なデプロイ、重大な安全上の懸念がある場合、採択されません。
- マージ前に PR を閉じると辞退扱いになります。マージされ報酬を受けた応募は、提出された権利申告に基づき公式アーカイブに保持されます。

### 更新、保存、報酬の支払い

提出期間中は、同じ PR に更新を追加できます。

1. 新しいバージョンは新たなチェックを開始します。保存タスクが現在のバージョンを独立して再確認してから公式アーカイブを作成します。更新で置き換わったバージョンや閉じられた PR はスキップします。保存タスクが失敗した場合、保存は未完了です。
2. 以前のチェック結果は変更後のコードには適用されません。レビュアーは正確な現在のバージョンを確認し、審査した Commit を記録します。
3. 完全なソースのマージはメンテナーが判断します。保存目的のマージは審査判断の代わりにはならず、受賞を意味しません。
4. 最終審査の判断を記録した後、メンテナーが保存済みソースとマージ後のソースを照合し、稼働中のサービスの証拠を再確認して、ソースと整合性確認記録を含む変更不可能な受入 Release を公開します。
5. 受入成果物の封印と独立バックアップが完了した後にのみ、報酬を承認します。
6. 以後の改善は新しい PR と Release を使用し、報酬対象のスナップショットを上書きしません。

公式保存の完了が確認された後は、Fork や外部リポジトリを削除しても保存済みの公式コピーは削除されません。独立バックアップは別途実施する必要があり、チェックの成功や同じ GitHub リポジトリ内のアーカイブでは代替できません。詳細は [`提出物の保持と報酬支払いポリシー`](./docs/submission-retention-and-reward.md) を参照してください。

### 審査方法

| 必須ゲート | 確認内容 |
| --- | --- |
| 呼び出し可能 | API とヘルスチェックが応答し、文書化されたタスクを実行できること。 |
| 実在し保守可能 | ソース、固定 Commit、依存関係、手順がデプロイ済みサービスと一致すること。 |
| 再現可能 | 提出資料から機能を理解、テスト、再デプロイできること。 |
| 安全に審査可能 | シークレット漏えい、悪意ある動作、重大な不正アクセス、隠れたデータフローがないこと。 |
| Agent に有用 | 入力、出力、エラー、制限、機能境界が MCP 標準化に十分明確であること。 |

結果は **合格**、**条件付き合格**、**不採択** のいずれかです。すべての必須ゲートを通過した後にのみ採点を行い、レビュアーは証拠に基づく [`審査スコアカード`](./docs/review-scorecard.md) を使用します。

選出チームは MCP プロダクト化に進みます。X-Agent は、ツール境界、Schema、認可、エラー、制限、可観測性、および OKX 向け申請パッケージの設計を支援します。

## Agent プラグインのセットアップ

プラグインのインストールは、現在の MCP ハッカソンへの提出条件ではありません。Cursor、Claude Code、Codex、OpenCode、AgentSkills 互換ランタイムをサポートします。

```bash
npx @xagt/agent-plugin@latest setup --target all
xagt-plugin doctor
```

Node `>= 18.17` が必要です。

## リポジトリ開発

```bash
npm ci
npm run lint
npm test
npm run build
npm run validate:submission -- --dir submissions/mcp-hackathon/<チーム>-<プロジェクト>
npm run validate:submission -- --dir submissions/mcp-hackathon/<チーム>-<プロジェクト> --online
```

ライセンス：UNLICENSED — 別途書面による許諾がない限り、プログラム関連の利用に限定されます。

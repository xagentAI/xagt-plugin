# X-Agent MCP ハッカソン & Agent プラグイン

[English](./README.md) | [简体中文](./README.zh-CN.md) | 日本語

> **現在のプログラム：実際に呼び出せる機能を提出してください。X-Agent が API とソースコードを検証し、選出されたプロジェクトを MCP ツールとして標準化したうえで、OKX Agent エコシステムへの申請を支援します。**

このリポジトリは、現在開催中の X-Agent MCP ハッカソンにおける公式コード提出窓口です。`@xagt/agent-plugin` のインストーラーも収録しています。

過去のプログラム：[X-Agent × OKX Agentic Wallet Hackathon · 2026年5月](https://xagt.ai/hackathon) · [コードと提出物のアーカイブ](./submissions/INDEX.md)

## 現在のプログラム：X-Agent MCP ハッカソン

本ハッカソンでは、トラック、言語、フレームワーク、プロジェクト形式を限定しません。AI Agent から呼び出すことができ、現実のタスクを解決する有用な機能であれば提出できます。

応募時点で **MCP を実装する必要はありません**。動作する機能、デプロイ済み API、完全なソースコードを提出してください。検証後、X-Agent が選出チームとともに MCP 標準化を進めます。

### プログラムの流れ

```text
実際に呼び出せる機能
        ↓
デプロイ済み API と完全なソースを PR で提出
        ↓
API、Commit、ソース、安全性を検証
        ↓
X-Agent が MCP として標準化
        ↓
OKX Agent エコシステムへの申請を支援
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

提出時点では、MCP、Streamable HTTP、x402、EIP-3009、A2MCP、決済 SDK の実装は必須ではありません。

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

外部リポジトリへのリンクだけでは提出として不十分です。審査対象の完全なソースコードを `source/` に含めてください。提出者が後から Fork や外部リポジトリを削除しても、公式記録は残ります。

次のファイルから始めてください。

- [`完全な提出仕様`](./submissions/README.md)
- [`submissions/TEMPLATE.md`](./submissions/TEMPLATE.md)
- [`submissions/submission.example.json`](./submissions/submission.example.json)
- [`submissions/RIGHTS_TEMPLATE.md`](./submissions/RIGHTS_TEMPLATE.md)
- [`submissions/VERIFICATION_TEMPLATE.md`](./submissions/VERIFICATION_TEMPLATE.md)

### 4 ステップで提出

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

自動検証の合格は、到達可能性とバージョンの紐づけを証明するだけです。品質、所有権、安全性、最終的な参加資格は別途、人による審査が必要です。

### 開発者とプログラムを守るルール

- 提出、デプロイ、審査許諾を行う権利があるコード、サービス、依存関係、データ、ブランド素材のみを提出してください。
- 認証情報、非公開の顧客データ、マルウェア、バックドア、認証情報の窃取、隠れたデータ流出、不正な自動化、未申告の外部通信を含めてはいけません。
- 盗用、偽のデプロイ証明、虚偽の所有権、購入したエンゲージメント、身元操作、組織的な採点操作は失格となります。
- 告知された審査期間中は API を利用可能な状態にしてください。短期の審査用認証情報は指定された非公開チャネルでのみ共有し、Git に保存しないでください。
- API の不通、ソースの不足、検証不能な Commit、再現不能なデプロイ、重大な安全上の懸念がある場合、採択されません。
- マージ前に PR を閉じると辞退扱いになります。マージされ報酬を受けた応募は、提出された権利申告に基づき公式アーカイブに保持されます。

### 更新、保存、報酬の支払い

開発者は未マージの PR に修正を追加できます。急いでマージする必要はありません。

1. 新しい PR バージョンごとに検証を再実行し、検証に成功した各バージョンを固有の公式参照として保存します。
2. 新しい Push により以前の検証・審査コンテキストは無効になります。X-Agent は正確な最新バージョンのみを審査します。
3. 最終採択バージョンを完全なソースコードとともにマージします。
4. X-Agent がオンライン検証を再実行し、完全性レシートとソースアーカイブを作成して、変更不可能な受入 Release を公開します。
5. 受入成果物の封印と独立バックアップが完了した後にのみ、報酬を承認します。
6. 以後の改善は新しい PR と Release を使用し、報酬対象のスナップショットを上書きしません。

提出者が Fork や外部リポジトリを削除しても、公式コピーは削除できません。詳細は [`提出物の保持と報酬支払いポリシー`](./docs/submission-retention-and-reward.md) を参照してください。

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

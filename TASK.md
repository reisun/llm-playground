# LLM-playground タスク

## プロジェクト概要
ローカルLLM実験環境 + 内部AI系サービスの統合窓口。
Docker Compose で Ollama / Agent Gateway / 内部リバプロを提供する。

## 完了済み

### リポジトリ構築・初期セットアップ (PR #1)
- GitHub リポジトリ `reisun/llm-playground` 作成
- docker-compose.yml (Ollama + Open WebUI)
- .env.example / .gitignore / CLAUDE.md / Makefile
- scripts/health-check.sh
- README.md (セットアップ〜マルチモーダル利用手順)

### Ollama 単体構成への変更 (PR #2)
- Open WebUI を廃止し Ollama 単体構成に変更
- 外部ネットワーク `llm-network` を追加
- discord-yomiage-bot 等から llm-network 経由で利用可能に

### Agent Gateway + 内部リバプロ (PR #3)
- Agent Gateway（FastAPI）: エージェントCLI（Claude Code, Codex）をHTTP APIとしてラップ
  - POST /agent/run: 非同期ジョブ投入（agent, prompt, cwd, model, system_prompt, timeout, permissions）
  - GET /agent/jobs/{id}: ジョブ状態取得
  - GET /agent/jobs: ジョブ一覧
  - DELETE /agent/jobs/{id}: ジョブキャンセル
  - GET /health: ヘルスチェック
  - 同時実行数1、キューで順番待ち
- 内部リバプロ（nginx）: パスベースルーティング
  - /llm/ → Ollama（ローカルLLM推論）
  - /agent/ → Agent Gateway
- Dockerfile: Python 3.12 + Claude Code CLI + Codex CLI + gh CLI
- テスト31件（ruff check + ruff format + pytest）

### 動作確認
- `docker compose up -d` で全サービス起動確認済み
- llama3.2:1b を pull し、日本語チャット応答を確認（推論時間: 約1.7秒/CPU環境）
- llava (マルチモーダル、4.7GB) を pull 済み
- Agent Gateway ヘルスチェック OK（直接 + リバプロ経由）
- 内部リバプロ経由で Ollama API 疎通確認

## 設計方針

### Agent Gateway

#### 背景・経緯
- slack-shape-bot の `run_claude()` が同等の処理を既に持っている
  - CLI子プロセス実行、タイムアウト制御、認証切れ検知・再認証
  - ただし slack-shape-bot に密結合しており、他プロジェクトから使えない
  - これを汎用化して共有サービスにするのが Agent Gateway の目的
- Codex には公式の App Server（JSON-RPC 2.0 / stdio / WebSocket）が存在する
  - https://developers.openai.com/codex/app-server
  - ただしこれをそのまま使うとクライアント側が複雑になりすぎる
- → 両方とも CLI を子プロセスで叩く方式に統一し、シンプルに保つ

#### 対象 CLI の仕様比較
| | Claude Code CLI | Codex CLI |
|---|---|---|
| 非対話モード | `claude -p <prompt>` | `codex exec <prompt>` |
| system-prompt | `--system-prompt "..."` | なし（プロンプト本文に結合） |
| モデル指定 | `--model <model>` | `-m <model>` |
| 作業ディレクトリ | 子プロセスの cwd で制御 | `-C <dir>` |
| 権限スキップ | `--dangerously-skip-permissions` | `--dangerously-bypass-approvals-and-sandbox` |
| 出力形式 | `--output-format json` | `--json`（JSONL） |

#### CLI差異の吸収
| パラメータ | Claude Code | Codex |
|---|---|---|
| `system_prompt` | `--system-prompt "..."` | プロンプト本文の先頭に結合 |
| `model` | `--model <model>` | `-m <model>` |
| `cwd` | 子プロセスの cwd で制御 | `-C <dir>` |
| `permissions: readonly` | オプションなし | オプションなし |
| `permissions: full` | `--dangerously-skip-permissions` | `--dangerously-bypass-approvals-and-sandbox` |

#### 権限制御
- デフォルトは `readonly`（権限スキップなし）。質問やコード生成のみで安全
- `full` を指定した場合のみ権限スキップを有効化し、ファイル編集・コマンド実行を許可

#### 非同期ジョブ方式
- リクエスト受付時にジョブIDを即返却し、HTTPタイムアウトの問題を回避
- クライアントは GET でポーリングして結果を取得
- SSE やWebSocket はタイムアウトやプロキシの問題があるため採用しない

#### 同時実行制御
- 同時実行数を1に制限（キューで順番待ち）
- CLIが共有する認証情報の競合を防止
- APIキーのレート制限への配慮

#### 認証管理
- ホストの認証情報（~/.claude, ~/.config/gh等）をコンテナにマウント
- 認証切れ検知時の再認証フローは slack-shape-bot の方式を参考に設計

## 未着手・検討事項

### Agent Gateway 関連
- [ ] 認証切れ時の再認証フロー実装（Slack通知? 別の手段?）
- [ ] discord-yomiage-bot の接続先変更検討（Ollama直叩き or 内部リバプロ経由）
- [ ] slack-shape-bot のリファクタ（Agent Gateway 導入後に run_claude() を置き換え）
- [ ] 実運用テスト（実際に claude/codex を呼び出すE2Eテスト）

### Ollama / ローカルLLM 関連
- [ ] llava モデルで画像 + テキストのマルチモーダル推論テスト
- [ ] モデル自動ルーティング（テキストのみ → llama、画像あり → llava）
- [ ] GPU パススルー (NVIDIA GPU + nvidia-container-toolkit) の検討
- [ ] より大きなモデル (llama3.2:3B, llama3.1:8B) の評価

### 将来の拡張
- [ ] SSE/WebSocket によるストリーミング
- [ ] Codex App Server プロトコルへの対応
- [ ] UIダッシュボード
- [ ] ジョブ履歴の永続化
- [ ] splatoon-battle-analyzer との連携（画像解析基盤として活用）

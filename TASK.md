# LLM-playground タスク

## プロジェクト概要
Docker Compose で Ollama + Open WebUI をすぐに動かせる LLM 実験環境。
将来的に splatoon-battle-analyzer 等のプロジェクトの基盤としても活用予定。

## 完了済み

### リポジトリ構築・初期セットアップ (PR #1 マージ済み)
- GitHub リポジトリ `reisun/llm-playground` 作成
- docker-compose.yml (Ollama + Open WebUI)
- .env.example / .gitignore / CLAUDE.md / Makefile
- scripts/health-check.sh
- README.md (セットアップ〜マルチモーダル利用手順)

### 動作確認
- `docker compose up -d` でサービス起動確認済み
- llama3.2:1b (テキスト専用、1.3GB) を pull し、日本語チャット応答を確認
  - 推論時間: 約1.7秒 (CPU環境)
- llava (マルチモーダル、4.7GB) を pull 済み
  - 画像認識テストは未実施

## 未着手・検討事項

### 画像認識テスト
- llava モデルで画像 + テキストのマルチモーダル推論を実際にテストする

### モデル切り替えの設計
- テキストのみ → llama3.2:1b (高速)、画像あり → llava (マルチモーダル) の自動ルーティング
- Open WebUI では手動切り替え、自前アプリでは API の model パラメータで制御可能

### パフォーマンス改善
- GPU パススルー (NVIDIA GPU + nvidia-container-toolkit) の検討
- より大きなモデル (llama3.2:3B, llama3.1:8B) の評価

### 将来の拡張
- splatoon-battle-analyzer との連携 (画像解析基盤として活用)
- カスタム API ラッパーやミドルウェアの開発

# llm-playground

Docker Compose で Ollama + Open WebUI をすぐに動かせる LLM 実験環境です。

## 前提条件

- [Docker](https://www.docker.com/) および Docker Compose v2
- WSL2 環境推奨（Windows の場合は Docker Desktop + WSL backend）
- 最低 8GB のメモリ（モデルサイズに応じて増やすこと）

## セットアップ

```bash
# 1. リポジトリをクローン
git clone https://github.com/reisun/llm-playground.git
cd llm-playground

# 2. 環境変数ファイルを作成
cp .env.example .env

# 3. サービスを起動
docker compose up -d

# 4. ブラウザでアクセス
# http://localhost:3000
```

初回起動時は Docker イメージのダウンロードに数分かかります。

## モデルの追加

Ollama コンテナ内でモデルをダウンロードします。

```bash
# Llama 3.2 (3B) をダウンロード
docker compose exec ollama ollama pull llama3.2

# Llama 3.2 (1B, 軽量版)
docker compose exec ollama ollama pull llama3.2:1b

# Gemma 2 (2B)
docker compose exec ollama ollama pull gemma2:2b

# ダウンロード済みモデルの一覧
docker compose exec ollama ollama list
```

ダウンロード後、Open WebUI の画面上部のモデル選択メニューからモデルを選べます。

## マルチモーダル（画像認識）

画像を理解できるモデルを使うと、画像をアップロードして質問できます。

```bash
# LLaVA モデルをダウンロード
docker compose exec ollama ollama pull llava

# より高性能な LLaVA 1.6
docker compose exec ollama ollama pull llava-llama3
```

Open WebUI でモデルを LLaVA に切り替えた後、チャット画面の添付ボタンから画像をアップロードして質問してください。

## ディスク要件

モデルは `ollama-data` Docker volume に保存されます。モデルサイズの目安:

| モデル | パラメータ数 | ディスクサイズ |
|--------|-------------|---------------|
| llama3.2:1b | 1B | 約 1.3GB |
| llama3.2 | 3B | 約 2.0GB |
| gemma2:2b | 2B | 約 1.6GB |
| llava | 7B | 約 4.7GB |
| llama3.1 | 8B | 約 4.7GB |

## 停止・再起動

```bash
# サービスを停止（データは保持）
docker compose stop

# サービスを再起動
docker compose restart

# サービスを起動
docker compose start
```

## 環境変数

`.env` ファイルで以下を設定できます:

| 変数 | デフォルト | 説明 |
|------|-----------|------|
| `WEBUI_PORT` | 3000 | Open WebUI のポート番号 |

## テスト・検証

```bash
# docker-compose.yml の構文チェック
make test

# ヘルスチェック（起動状態の確認）
make health
```

## トラブルシューティング

### Open WebUI にモデルが表示されない

Ollama コンテナが起動しているか確認してください。

```bash
docker compose ps
docker compose logs ollama
```

モデルがダウンロードされているか確認してください。

```bash
docker compose exec ollama ollama list
```

### ポートが既に使用されている

`.env` の `WEBUI_PORT` を別のポートに変更してください。

```bash
# .env を編集
WEBUI_PORT=3001
```

その後、サービスを再起動します。

```bash
docker compose stop
docker compose up -d
```

### Ollama の応答が遅い

CPU のみの環境ではモデルの推論に時間がかかります。軽量なモデル（`llama3.2:1b`, `gemma2:2b`）を使用してください。

### コンテナのログを確認する

```bash
# 全サービスのログ
docker compose logs -f

# 特定のサービスのログ
docker compose logs -f ollama
docker compose logs -f open-webui
```

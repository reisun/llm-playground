Read ~/workspace/AGENTS.md

## プロジェクト概要

Docker Compose で Ollama + Open WebUI を動かす LLM 実験環境。

## 技術スタック

- Docker / Docker Compose
- Ollama (LLM推論サーバー)
- Open WebUI (Web UI)

## 開発ルール

- feature ブランチで作業、main への直接変更禁止
- .env はコミット禁止、.env.example はダミー値のみ
- Docker許可: up, stop, start, restart, ps, logs, build
- Docker要確認: down -v, volume/image削除

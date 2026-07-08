# 荒れるレース検出＆LINE自動通知アプリ

既存の `boat-race-app`（予想アプリ）とは**完全に別の新しいアプリ**です。
コードの重複はありますが、依存関係もリポジトリも独立しています。

## 構成

- `app.py` — Streamlit製のダッシュボード（3タブ構成、詳細は下記「3つのモード」参照）
- `rough_race_scanner.py` — 全24会場を巡回し、締切間際レースを展示タイムでスコアリングする検出ロジック
- `racelist_scanner.py` — 出走表（全国勝率・モーター成績・級別等）から終日レースを事前ランキングするロジック
- `main.py` — ダッシュボードを開かなくても動く、自動スキャン＋LINE通知のヘッドレス実行スクリプト
- `line_notify.py` — LINE Messaging API push送信
- `state_store.py` — 当日の通知済みレース／検出履歴を記録
- `notified_races.json` — 通知済みレースの状態ファイル（重複通知防止用）
- `daily_summary.json` — 当日の検出履歴（ダッシュボードの「本日の検出履歴」タブ用）
- `.github/workflows/rough_race_notify.yml` — JST 9:00〜22:00に5分おき自動実行

**自動通知（GitHub Actions）** と **手動確認用ダッシュボード（Streamlit）** の二本立てです。
ダッシュボードを閉じていても自動通知は動き続けます。

## 3つのモード（ダッシュボードのタブ）

1. **🔎 直前スキャン** — 締切15分前後のレースの展示タイムから荒れ度を判定（従来機能）。
   自動LINE通知もこのロジックを使用。
2. **🌅 事前予想（全レース）** — 展示タイムを待たず、出走表の全国勝率・モーター成績・
   級別・フライング歴から、今日開催される全レースを「荒れそうな順」にランキング。
   締切よりずっと前、朝のうちに今日の狙い目を把握したい場合に使う。
   直前スキャンとは情報源・スコア基準が異なるため単純比較はできない。
3. **📋 本日の検出履歴** — GitHub Actionsが自動スキャンで検出したレースをその日の分だけ
   蓄積した一覧。ダッシュボードを開いていなくても記録される。

## セットアップ手順

### 1. 新しいGitHubリポジトリを作る

GitHub上で新規リポジトリ（例: `rough-race-line-notifier`）を空の状態で作成してください
（READMEやgitignoreは追加しない「Empty repository」でOK）。

このフォルダをそのリポジトリにpushします。

```bash
cd rough_race_notifier_app
git init
git add .
git commit -m "feat: 荒れるレース検出＆LINE通知アプリ 初期版"
git branch -M main
git remote add origin https://github.com/<あなたのGitHubユーザー名>/rough-race-line-notifier.git
git push -u origin main
```

### 2. LINE公式アカウント & Messaging APIチャネルの作成（無料）

1. https://developers.line.biz/console/ にアクセスし、LINEアカウントでログイン
2. 「新規プロバイダー作成」→ 任意の名前で作成
3. プロバイダー内で「Messaging API」チャネルを新規作成（チャネル名等は任意）
4. チャネル管理画面 →「Messaging API設定」タブ →「チャネルアクセストークン（長期）」を発行
   → これが `LINE_CHANNEL_ACCESS_TOKEN`
5. 「応答メッセージ」「Webhookの利用」はオフのままでOK（push通知のみなら不要）

### 3. 自分の userId を取得する

1. チャネル基本設定画面のQRコードを、スマホのLINEアプリで読み取りBotを友だち追加
2. userId（`U`で始まる33文字程度の文字列）の確認は「LINE Messaging API userId 取得方法」で
   検索すると画像付き手順が複数見つかります（Webhookで一時受信して確認するのが確実です）
   → これが `LINE_USER_ID`

### 4. GitHubリポジトリにSecretsを登録（自動通知用）

新しく作ったリポジトリ →「Settings」→「Secrets and variables」→「Actions」→
「New repository secret」で以下2つを登録:

- `LINE_CHANNEL_ACCESS_TOKEN`
- `LINE_USER_ID`

登録後、pushした時点から JST 9:00〜22:00の間は自動で5分おきに動き始めます。
Actionsタブから「Run workflow」で手動実行・動作確認もできます
（`dry_run: true` でLINE送信せずログ確認のみ可能）。

### 5. ダッシュボード（Streamlit）をデプロイ（任意）

自動通知だけで十分ならこの手順は不要です。画面で結果を見たい場合のみ:

1. https://share.streamlit.io にログインし、「New app」
2. リポジトリ: 手順1で作った新リポジトリ、Main file path: `app.py` を指定してデプロイ
3. デプロイ後、アプリ管理画面の「Settings」→「Secrets」に以下をTOML形式で追加

```toml
LINE_CHANNEL_ACCESS_TOKEN = "xxxxxxxxxx"
LINE_USER_ID = "Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

これでダッシュボード上の「📩 LINEに送信」ボタンも使えるようになります。

## ローカルで試す場合

```bash
pip install -r requirements.txt
export LINE_CHANNEL_ACCESS_TOKEN=xxxx
export LINE_USER_ID=Uxxxx
streamlit run app.py
```

ヘッドレス実行（GitHub Actionsと同じ処理）をローカルで試す場合:

```bash
DRY_RUN=true python main.py
```

## 設定の調整

- 通知しきい値: `main.py` の `ROUGH_SCORE_THRESHOLD` 環境変数（デフォルト50 = 「大波乱気配🔥」ライン）。
  展示タイム差0.1秒ごとに20点加算される単純な計算式。20〜49は「波乱含み」。
  ダッシュボードではスライダーで調整可能（表示のみ、実際の自動通知の閾値はActions側の設定）
- 実行間隔・時間帯: `.github/workflows/rough_race_notify.yml` の `cron` を編集
- 特定日をテストする場合: `TARGET_DATE=YYYYMMDD` 環境変数

## 注意

- `notified_races.json` はActionsが通知するたびにリポジトリへcommitされます。
  Streamlit Cloud はリポジトリへのpushで自動再デプロイされる仕様のため、
  通知が発生するたびにダッシュボードが数秒再起動することがあります（実害はありません）
- boatrace.jp公式サイトを直接スクレイピングしています。サイト構造が変わった場合は
  `rough_race_scanner.py` の調整が必要になる可能性があります

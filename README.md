# 荒れるレース検出＆LINE自動通知アプリ

既存の `boat-race-app`（予想アプリ）とは**完全に別の新しいアプリ**です。
コードの重複はありますが、依存関係もリポジトリも独立しています。

## 構成

- `app.py` — Streamlit製のダッシュボード（3タブ構成、詳細は下記「3つのモード」参照）
- `rough_race_scanner.py` — 全24会場を巡回し、締切間際レースを展示タイムでスコアリングする検出ロジック
- `racelist_scanner.py` — 出走表（全国勝率・モーター成績・級別・今節成績＝過去の戦績）から
  終日レースを事前ランキングするロジック
- `main.py` — 直前情報ベースの随時LINE通知（締切15分前後、15分おき）
- `main_daily_preview.py` — 事前予想モードの日次ダイジェストLINE通知（1日1回、朝）
- `line_notify.py` — LINE Messaging API push送信
- `state_store.py` — 通知済みレース／検出履歴／日次通知済みフラグを記録
- `notified_races.json` — 直前通知の重複防止用状態ファイル
- `daily_summary.json` — 当日の検出履歴（ダッシュボードの「本日の検出履歴」タブ用）
- `daily_preview_sent.json` — 事前予想の日次通知が送信済みかの記録
- `.github/workflows/rough_race_notify.yml` — JST 9:00〜22:00に15分おき自動実行（直前通知）
- `.github/workflows/daily_preview_notify.yml` — JST 8:00に1日1回自動実行（事前予想の日次通知）

**自動通知（GitHub Actions・2系統）** と **手動確認用ダッシュボード（Streamlit）** の組み合わせです。
ダッシュボードを閉じていても自動通知は動き続けます。

## 3つのモード（ダッシュボードのタブ）

1. **🔎 直前スキャン** — 締切15分前後のレースの展示タイムから荒れ度を判定（従来機能）。
   `main.py`による自動LINE通知（15分おき）もこのロジックを使用。
2. **🌅 事前予想（全レース）** — 展示タイムを待たず、出走表の全国勝率・モーター成績・
   級別・フライング歴・**今節（当該開催）ここ数走の着順＝過去の戦績**から、
   今日開催される全レースを「荒れそうな順」にランキング。
   締切よりずっと前、朝のうちに今日の狙い目を把握したい場合に使う。
   `main_daily_preview.py`による自動LINE通知（1日1回、朝）もこのロジックを使用。
   直前スキャンとは情報源・スコア基準が異なるため単純比較はできない。
3. **📋 本日の検出履歴** — GitHub Actionsが自動スキャン（直前情報ベース）で検出したレースを
   その日の分だけ蓄積した一覧。ダッシュボードを開いていなくても記録される。

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

### 3.5 複数人に通知したい場合

他の人にも同じ通知を届けたい場合、その人にも公式アカウントを友だち追加してもらい、
userIdを取得してカンマ区切りで追加します。

1. その人にBotのQRコードを送り、LINEアプリで友だち追加してもらう
2. チャネル管理画面 →「Messaging API設定」→「Webhookの利用」を一時的にON、
   Webhook URLに https://webhook.site で発行した一時URLを設定
3. その人にBotへ何かメッセージを送ってもらう
4. webhook.siteの画面に届いたリクエスト内容から `"userId": "Uxxxxxxxx..."` を確認
5. 確認できたら「Webhookの利用」は元に戻してOK（push通知だけなら不要）
6. `LINE_USER_ID` の値を `Uaaaa...,Ubbbb...,Ucccc...` のようにカンマ区切りで複数指定
   （GitHub Secrets・Streamlit Secrets両方とも同じ形式でOK。空白は入れても入れなくても可）

### 4. GitHubリポジトリにSecretsを登録（自動通知用）

新しく作ったリポジトリ →「Settings」→「Secrets and variables」→「Actions」→
「New repository secret」で以下2つを登録:

- `LINE_CHANNEL_ACCESS_TOKEN`
- `LINE_USER_ID`

登録後、pushした時点から以下の2つが自動で動き始めます。
Actionsタブから各ワークフローを「Run workflow」で手動実行・動作確認もできます
（`dry_run: true` でLINE送信せずログ確認のみ可能）。

- **Rough Race LINE Notifier**: JST 9:00〜22:00の間、15分おきに直前情報をスキャンし通知
- **Daily Rough Race Preview (LINE)**: JST 8:00に1日1回、事前予想の上位レースをまとめて通知

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
DRY_RUN=true python main.py                  # 直前情報ベースの随時通知
DRY_RUN=true python main_daily_preview.py    # 事前予想の日次ダイジェスト通知
```

## 設定の調整

- 直前通知のしきい値: `main.py` の `ROUGH_SCORE_THRESHOLD` 環境変数（デフォルト60）。
  展示タイム差0.1秒ごとに20点加算される単純な計算式。score 50以上が「大波乱気配🔥」の目安、20〜49は「波乱含み」。
  ダッシュボードではスライダーで調整可能（表示のみ、実際の自動通知の閾値はActions側の設定）
- 事前予想通知のしきい値: `main_daily_preview.py` の `PRE_RACE_SCORE_THRESHOLD` 環境変数
  （デフォルト45 = 「波乱注意🔥」ライン）
- 事前予想通知の件数上限: `PRE_RACE_TOP_N` 環境変数（デフォルト10件）
- 実行間隔・時間帯: 各 `.github/workflows/*.yml` の `cron` を編集
- 特定日をテストする場合: `TARGET_DATE=YYYYMMDD` 環境変数

## 注意

- `notified_races.json` / `daily_summary.json` / `daily_preview_sent.json` はActionsが
  実行するたびにリポジトリへcommitされます。Streamlit Cloud はリポジトリへのpushで
  自動再デプロイされる仕様のため、通知が発生するたびにダッシュボードが数秒再起動する
  ことがあります（実害はありません）
- boatrace.jp公式サイトを直接スクレイピングしています。サイト構造が変わった場合は
  `rough_race_scanner.py` / `racelist_scanner.py` の調整が必要になる可能性があります
- 事前予想モードはあくまで公表済みの成績データに基づく統計的な目安であり、
  展示タイムのような直前の実測値は反映されていません

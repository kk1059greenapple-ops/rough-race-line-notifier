"""
github_settings_sync.py

ダッシュボード（app.py）から変更した設定（自動通知のしきい値等）を、
GitHub Contents API経由でリポジトリの settings.json に反映するモジュール。
これにより、次回以降のGitHub Actions実行（main.py）が新しい設定を読み込むようになる
（Streamlit Cloudのファイルシステムはリポジトリに書き戻されないため、
このAPI経由の反映が無いとダッシュボード上の変更が自動通知に効かない）。

必要な環境変数（Streamlit Secretsから橋渡しされる想定。app.py参照）:
  GITHUB_PAT   … このリポジトリへの Contents(Read and write) 権限を持つ
                 Fine-grained personal access token
  GITHUB_REPO  … "オーナー名/リポジトリ名"（省略時はDEFAULT_REPOを使用）
"""

import base64
import json
import os

import requests

DEFAULT_REPO = "kk1059greenapple-ops/rough-race-line-notifier"
SETTINGS_PATH = "settings.json"


class GitHubSyncError(Exception):
    pass


def push_settings_to_github(settings: dict, token: str = None, repo: str = None, branch: str = "main") -> None:
    """settings（dict）をリポジトリのsettings.jsonにcommitする。"""
    token = token or os.environ.get("GITHUB_PAT")
    repo = repo or os.environ.get("GITHUB_REPO") or DEFAULT_REPO
    if not token:
        raise GitHubSyncError(
            "GITHUB_PAT が設定されていません。GitHubでこのリポジトリへのContents"
            "（Read and write）権限を持つPersonal Access Tokenを発行し、"
            "Streamlit Secretsに登録してください。"
        )

    api_url = f"https://api.github.com/repos/{repo}/contents/{SETTINGS_PATH}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    # 既存ファイルのshaを取得（無ければ新規作成扱いでsha無しのままPUTする）
    sha = None
    get_resp = requests.get(api_url, headers=headers, params={"ref": branch}, timeout=15)
    if get_resp.status_code == 200:
        sha = get_resp.json().get("sha")
    elif get_resp.status_code != 404:
        raise GitHubSyncError(f"設定の取得に失敗しました: {get_resp.status_code} {get_resp.text}")

    content_str = json.dumps(settings, ensure_ascii=False, indent=2)
    content_b64 = base64.b64encode(content_str.encode("utf-8")).decode("ascii")

    payload = {
        "message": "chore: update settings.json from dashboard",
        "content": content_b64,
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    put_resp = requests.put(api_url, headers=headers, json=payload, timeout=15)
    if put_resp.status_code not in (200, 201):
        raise GitHubSyncError(f"設定の反映に失敗しました: {put_resp.status_code} {put_resp.text}")

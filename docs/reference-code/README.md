# ホットアップデート機構 参考コード

`docs/maya-hot-update-patterns.md` で解説した「ドラッグ 1 回のインストール +
UI の Update ボタンでいつでも最新化」を、**新規 Maya ツール** にそのままコピー
して使えるテンプレート コードです。

## ファイル構成 (最小 2 ファイル)

```
reference-code/
├── README.md      ← このファイル
├── install.py     ← ドラッグ&ドロップ + Script Editor 両対応の installer
└── my_tool.py     ← ツール本体 (__version__ + show() + Update ボタン)
```

**ツール中身のロジックは含みません。** 「配布 & 更新」インフラだけを抜き出した
テンプレートで、`my_tool.py` の `_build_body()` を書き換えれば自分のツールに
なります。

パッケージ化 (`my_tool/__init__.py` + サブモジュール…) は必要になってから
やれば OK。まずは 1 ファイル構成でスタートするのが最小コスト。

---

## 使い方

### 1. コピー

2 ファイルを新ツール用リポジトリ ルートに置く:

```
your-new-tool/
├── install.py
└── my_tool.py     ← 実際のモジュール名にリネーム (paint_tool.py など)
```

### 2. 定数を書き換える

以下 4-5 か所を新ツール名・リポジトリに合わせて置換:

| ファイル | 定数 | 置換内容 |
|---|---|---|
| `install.py` | `_GITHUB_OWNER` | あなたの GitHub アカウント名 |
| `install.py` | `_GITHUB_REPO`  | 新ツールのリポジトリ名 |
| `install.py` | `_MODULE`       | モジュール名 (`.py` 抜き) |
| `install.py` | `_SHELF_BUTTON_LABEL` | シェルフに表示する短いラベル |
| `my_tool.py` | `_GITHUB_OWNER` / `_GITHUB_REPO` / `_PACKAGE` | 同上 |
| `my_tool.py` | `WINDOW` | ツールウィンドウの一意名 (`_MODULE + "Win"` 推奨) |

### 3. `_build_body()` を書き換える

`my_tool.py` の `_build_body()` に自分のコントロールを追加。それ以外
(update 関連関数、`show()` の枠組み、footer) は触らなくて OK。

### 4. GitHub に push

すべて main ブランチにコミット + push。

### 5. エンドユーザーへは `install.py` だけ配布

- GitHub raw URL を伝える → `install.py` をブラウザで保存 → Maya にドラッグ
- 以降は UI 内 [GitHub から更新] ボタンで自動更新

---

## 動作フロー

**初回インストール**:

```
install.py (drag)
   ↓
_fetch_module    ← GitHub API で SHA 取得 → SHA 固定 raw URL でモジュール取得
   ↓
_atomic_write    ← tmp ファイル + os.replace で原子的に上書き
   ↓
_clean_pycache   ← 古い .pyc を削除
   ↓
_flush_imports   ← sys.modules から my_tool を消す
   ↓
_add_shelf_btn   ← 左click=起動 / 右click=Update from GitHub
   ↓
confirmDialog    ← "previous 0.1.0 → current 0.1.3" 表示
```

**アップデート** (シェルフ右click → Update from GitHub、または UI 内ボタン):

```
button click
   ↓
evalDeferred     ← コールバック抜けてから実行
   ↓
_run_update
   ├─ SHA 取得
   ├─ 自分のウィンドウを閉じる
   ├─ install.py を fetch + exec
   │    (install.py が全部やってくれる: 上書き / pycache / shelf)
   └─ sys.modules フラッシュ
   ↓
evalDeferred     ← modal ダイアログ閉じてから
   ↓
_reopen_after_update  ← import my_tool; show()
```

---

## パターンとの対応

このテンプレートで実装済みのパターン (patterns doc の番号):

| # | パターン | 実装箇所 |
|---|---|---|
| 1-3 | Windows read-only ロック | `install.py :: _force_writable` |
| 1-4 | 非原子書き込み | `install.py :: _atomic_write_bytes` |
| 1-5 | `__pycache__` キャッシュ | `install.py :: _clean_pycache` |
| 1-6 | `sys.modules` キャッシュ | `install.py :: _flush_imports` + shelf btn |
| 1-7 | GitHub CDN キャッシュ | `install.py :: _resolve_latest_sha` (SHA URL 固定) |
| 1-8 | Maya ドラッグ 1 回で終わる問題 | `my_tool.py :: update_from_github` + shelf 右click |
| 1-9 | コールバック内で親ウィンドウ削除 | `my_tool.py :: evalDeferred 3 段階` |

---

## 検証チェックリスト

新ツールをセットアップしたら、以下を順に通せば OK。

- [ ] `install.py` を Maya viewport にドラッグ → ダイアログ + シェルフボタン出現
- [ ] シェルフボタン click → UI ウィンドウ開く、タイトルに version 表示
- [ ] `_build_body()` を書き換え → GitHub に version bump 込み push
- [ ] UI 内 [GitHub から更新] click → `previous 0.1.0 → current 0.1.1` ダイアログ
- [ ] Update 後、ウィンドウが自動で再オープンされ、変更した UI が表示される
- [ ] シェルフ右click → Update from GitHub でも同じ挙動
- [ ] Maya を再起動しても同じ最新版が起動する

## デバッグ

「更新されていないように見える」時は `docs/maya-hot-update-patterns.md` §4 の
診断スニペットを Script Editor で実行。
